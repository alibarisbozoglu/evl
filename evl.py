#!/usr/bin/env python3
"""EVL (evaluate) - quick calculations from the command line.

Usage:
    evl 5 + 5                 -> ans: 10
    evl 'x = 4; 5*x + 4'      -> ans: 24
    evl                       -> multiline session; a line without a trailing ';'
                                 prints an answer, an empty line (or Ctrl-D) quits
    evl -f FILENAME           -> evaluate every statement in a file
"""

import ast
import io
import math
import operator
import re
import sys
import tokenize

BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

COMPARE_OPS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

# Names available in every calculation.
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}
FUNCTIONS = {
    name: getattr(math, name)
    for name in (
        "sqrt", "cbrt", "exp", "log", "log2", "log10",
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh", "degrees", "radians",
        "floor", "ceil", "factorial", "gcd", "lcm", "hypot",
    )
    if hasattr(math, name)
}
FUNCTIONS.update({"abs": abs, "round": round, "min": min, "max": max})

# Functions that reduce a range to a single number: sum(x), len(x), ...
REDUCERS = {
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "mean": lambda values: sum(values) / len(values),
}

# Base conversions: bin2dec, hex2bin, dec2oct, ... (every pair of bases).
BASES = {"bin": 2, "oct": 8, "dec": 10, "hex": 16}
BASE_FORMATS = {2: "b", 8: "o", 16: "X"}
CONVERSIONS = {
    f"{src}2{dst}": (BASES[src], BASES[dst])
    for src in BASES
    for dst in BASES
    if src != dst
}

STYLE_FN = "__plotstyle__"  # internal: a plotstyle block becomes `name = __plotstyle__(i)`
SHOW_FN = "__show__"  # internal: `show a b : c` becomes `__show__([[a, b], [c]])`
DEFINE_FN = "__function__"  # internal: `f(x) = body` becomes `f = __function__("f", [x], body)`
CALCULUS_FUNCTIONS = {"integral", "derivative", "limit"}
SPECIAL_FUNCTIONS = {"range", "plot", "show", STYLE_FN, SHOW_FN, DEFINE_FN} | CALCULUS_FUNCTIONS
RESERVED = set(FUNCTIONS) | set(REDUCERS) | set(CONVERSIONS) | set(CONSTANTS) | SPECIAL_FUNCTIONS

MAX_RANGE = 10_000_000

# hex2dec(ff), bin2hex(1011), oct2bin(0o17): the argument is digits, not an
# expression ("ff" would be a variable and "1f" a syntax error), so quote it
# before parsing. dec2* functions take a normal expression and are left alone.
DIGITS_ARG = re.compile(
    r"\b((?:bin|oct|hex)2(?:bin|oct|dec|hex))\(\s*([0-9A-Za-z_]+)\s*\)"
)

# [start:step:end] and [start:end] range literals.
RANGE3 = re.compile(r"\[([^\[\]:]+):([^\[\]:]+):([^\[\]:]+)\]")
RANGE2 = re.compile(r"\[([^\[\]:]+):([^\[\]:]+)\]")

STYLE_HEADER = re.compile(r"^plotstyle\s+([A-Za-z_]\w*)\s*:\s*(#.*)?$")
STYLE_LINE = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(.*)$")

LINESTYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-.", "none": ""}
MARKERS = {
    "none": "", "dot": ".", "circle": "o", "square": "s", "triangle": "^",
    "diamond": "D", "star": "*", "plus": "+", "cross": "x", "x": "x",
}
STYLE_KEYS = (
    "linestyle", "linewidth", "marker", "markersize", "linecolor",
    "markercolor", "xrange", "yrange",
    "title", "xlabel", "ylabel", "grid",
)


class EvlError(Exception):
    pass


class Vector:
    """A list of numbers, e.g. from range(). `domain` is the range it was
    computed from (if any), used as the horizontal axis when plotting.
    `gaps` holds the positions where a comparison removed values just before,
    so plot() doesn't draw a line across them."""

    __slots__ = ("values", "domain", "gaps")

    def __init__(self, values, domain=None, gaps=frozenset()):
        self.values = list(values)
        self.domain = domain
        self.gaps = gaps


class Plot:
    """What plot() returns: one or more (list, style) layers drawn on the
    same axes. Nothing is drawn until it's shown. plot(f) + plot(g) adds layers."""

    def __init__(self, layers):
        self.layers = layers


class Function:
    """f(x) = x^2: a formula with parameters. f(3) computes it with x = 3;
    a plain `f` computes it with the current value of x (e.g. a range)."""

    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

    def __str__(self):
        body = ast.unparse(self.body).replace(" ** ", "^").replace("**", "^")
        return f"{self.name}({', '.join(self.params)}) = {body}"


class PlotStyle:
    def __init__(self, name, options):
        self.name = name
        self.options = options


FUNCTION_DEF = re.compile(
    r"(^|;)([ \t]*)([A-Za-z_]\w*)[ \t]*\(([\w \t,]*)\)[ \t]*=(?!=)", re.MULTILINE
)


def rewrite_function_definitions(source):
    """`f(x, y) = body` -> `f = __function__("f", [x, y], body)`. The body ends
    at the next ';', newline or comment outside brackets and quotes."""
    out, pos = [], 0
    for match in FUNCTION_DEF.finditer(source):
        if match.start() < pos:
            continue
        lead, indent, name, params = match.groups()
        params = [p.strip() for p in params.split(",")] if params.strip() else []
        if not all(re.fullmatch(r"[A-Za-z_]\w*", p) for p in params):
            continue  # not a definition; let the parser report it
        end, depth, quote = match.end(), 0, None
        while end < len(source):
            ch = source[end]
            if quote:
                quote = None if ch == quote else quote
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif depth == 0 and ch in ";\n#":
                break
            end += 1
        body = source[match.end():end]
        out.append(source[pos:match.start()])
        out.append(f'{lead}{indent}{name} = {DEFINE_FN}("{name}", [{", ".join(params)}], {body.strip() or "None"})')
        pos = end
    out.append(source[pos:])
    return "".join(out)


def preprocess_expression(source):
    source = rewrite_function_definitions(source)
    source = RANGE3.sub(r"range(\1,\2,\3)", source)
    source = RANGE2.sub(r"range(\1,1,\2)", source)
    source = DIGITS_ARG.sub(r'\1("\2")', source)
    return source.replace("^", "**")  # allow 2^3 as power


def rewrite_show_statements(source, multiline):
    """Turn `show a b : c` into `__show__([[a, b], [c]])`, line by line.

    In a show layout, `:` separates columns (left to right) and plots written
    one after another in a column are stacked top to bottom. `+` (overlaying
    plots on the same axes) is ordinary arithmetic on plot values.
    """
    lines = source.split("\n")
    for number, line in enumerate(lines, 1):
        if "show" in line:
            try:
                lines[number - 1] = rewrite_show_line(line)
            except EvlError as exc:
                raise EvlError(f"line {number}: {exc}" if multiline else str(exc)) from None
    return "\n".join(lines)


def rewrite_show_line(line):
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(line).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return line  # let the parser report the problem
    skip = {tokenize.COMMENT, tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER,
            tokenize.INDENT, tokenize.DEDENT}
    tokens = [t for t in tokens if t.type not in skip]

    # Split into statements at ';' outside brackets.
    statements, current, depth = [], [], 0
    for tok in tokens:
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth -= 1
        if depth == 0 and tok.type == tokenize.OP and tok.string == ";":
            statements.append(current)
            current = []
        else:
            current.append(tok)
    statements.append(current)

    replacements = []
    for stmt in statements:
        if len(stmt) < 2 or stmt[0].type != tokenize.NAME or stmt[0].string != "show":
            continue
        if stmt[1].type == tokenize.OP and stmt[1].string not in "([-+:":
            continue  # e.g. `show = 1`: not a show statement (and an error later)
        columns = split_show_layout(stmt[1:], line)
        call = SHOW_FN + "([" + ", ".join("[" + ", ".join(col) + "]" for col in columns) + "])"
        replacements.append((stmt[0].start[1], stmt[-1].end[1], call))

    for start, end, call in reversed(replacements):
        line = line[:start] + call + line[end:]
    return line


def split_show_layout(tokens, line):
    def ends_operand(tok):
        return tok.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING) or tok.string in (")", "]")

    def starts_operand(tok, prev):
        if tok.string in ("(", "["):
            return prev.type != tokenize.NAME and prev.string not in (")", "]")  # f(x) is a call
        return tok.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING)

    columns, column, item, depth, prev = [], [], [], 0, None
    for tok in tokens:
        if depth == 0 and tok.type == tokenize.OP and tok.string == ":":
            if item:
                column.append(item)
            if not column:
                raise EvlError("show: empty column before ':'")
            columns.append(column)
            column, item, prev = [], [], None
            continue
        if depth == 0 and prev is not None and ends_operand(prev) and starts_operand(tok, prev):
            column.append(item)  # `a b`: b goes below a
            item = []
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth -= 1
        item.append(tok)
        prev = tok
    if item:
        column.append(item)
    if not column:
        raise EvlError("show: nothing to show after ':'" if columns else "show: nothing to show")
    columns.append(column)
    return [[line[it[0].start[1]:it[-1].end[1]] for it in col] for col in columns]


def parse_style_value(raw):
    """'"#f92200"  # comment' -> '#f92200'; 'blue # comment' -> 'blue'."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end == -1:
            raise ValueError("missing closing quote")
        rest = raw[end + 1:].strip()
        if rest and not rest.startswith("#"):
            raise ValueError("unexpected text after quoted value")
        return raw[1:end]
    return raw.split("#", 1)[0].strip()


def extract_plotstyles(source):
    """Pull `plotstyle NAME:` blocks out of the source.

    Each header line is replaced with `NAME = __plotstyle__(i)` and its body
    lines with blank lines, so line numbers in error messages stay correct.
    Returns the new source and a list of (name, [(line_no, key, raw_value)]).
    """
    lines = source.split("\n")
    styles = []
    i = 0
    while i < len(lines):
        match = STYLE_HEADER.match(lines[i])
        if not match:
            i += 1
            continue
        name = match.group(1)
        header_no = i + 1
        lines[i] = f"{name} = {STYLE_FN}({len(styles)})"
        entries = []
        i += 1
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            text = lines[i].strip()
            lines[i] = ""
            if text and not text.startswith("#"):
                entry = STYLE_LINE.match(text)
                if not entry:
                    raise EvlError(f"line {i + 1}: expected 'key: value' in plotstyle {name}")
                entries.append((i + 1, entry.group(1), entry.group(2)))
            i += 1
        styles.append((name, header_no, entries))
    return "\n".join(lines), styles


class Evaluator:
    def __init__(self):
        self.variables = {}
        self.styles = []
        self.figures = 0
        self.active = set()  # functions being computed, to catch f(x) = f(x) + 1

    def run(self, source):
        """Evaluate ';' / newline separated statements, return the last value."""
        multiline = "\n" in source.strip()
        source, self.styles = extract_plotstyles(source)
        source = preprocess_expression(source)
        source = rewrite_show_statements(source, multiline)
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            where = f" on line {exc.lineno}" if multiline and exc.lineno else ""
            raise EvlError(f"syntax error{where}: {exc.msg}") from None

        result = None
        for stmt in tree.body:
            try:
                result = self.run_statement(stmt)
            except EvlError as exc:
                if multiline and not str(exc).startswith("line "):
                    raise EvlError(f"line {stmt.lineno}: {exc}") from None
                raise
        return result

    def run_statement(self, stmt):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    raise EvlError("can only assign to simple names")
                if target.id in RESERVED:
                    raise EvlError(f"cannot assign to built-in '{target.id}'")
            try:
                value = self.eval(stmt.value)
            except EvlError as exc:
                unknown = re.fullmatch(r"unknown variable '(\w+)'", str(exc))
                if unknown:  # f = x^2 with x undefined: maybe a function was meant
                    var, target = unknown.group(1), stmt.targets[0].id
                    raise EvlError(f"{exc} (to define a function of {var}, write {target}({var}) = ...)") from None
                raise
            for target in stmt.targets:
                self.variables[target.id] = value
            # Defining a style, a plot or a function isn't a calculation: print nothing.
            return None if isinstance(value, (PlotStyle, Plot, Function)) else value
        if isinstance(stmt, ast.Expr):
            node = stmt.value
            if isinstance(node, ast.Name) and isinstance(self.variables.get(node.id), Function):
                func = self.variables[node.id]
                if any(p not in self.variables for p in func.params):
                    return func  # `f` on its own shows the definition
            value = self.eval(node)
            if isinstance(value, Plot):  # a plot on its own line is shown
                self.show([[value]])
                return None
            return value
        raise EvlError("only expressions and assignments are allowed")

    # ---- expressions -------------------------------------------------------

    def eval(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str)) and not isinstance(node.value, bool):
                return node.value
            raise EvlError(f"unsupported value: {node.value!r}")
        if isinstance(node, ast.List):
            values = [self.eval(item) for item in node.elts]
            if not all(is_number(v) for v in values):
                raise EvlError("a list can only contain numbers")
            return Vector(values)
        if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
            left, right = self.eval(node.left), self.eval(node.right)
            if isinstance(left, Plot) or isinstance(right, Plot):
                if isinstance(node.op, ast.Add) and isinstance(left, Plot) and isinstance(right, Plot):
                    return Plot(left.layers + right.layers)  # draw both on the same axes
                raise EvlError("plots can only be combined with +, e.g. plot(f) + plot(g)")
            if isinstance(left, str) or isinstance(right, str):
                raise EvlError(
                    "can't do arithmetic on a bin/oct/hex result; "
                    "convert it to dec first, e.g. hex2dec(...)"
                )
            return self.elementwise(BIN_OPS[type(node.op)], [left, right], "arithmetic")
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            operand = self.eval(node.operand)
            if isinstance(operand, Plot):
                raise EvlError("can't do arithmetic on a plot")
            if isinstance(operand, str):
                raise EvlError("can't do arithmetic on a bin/oct/hex result; convert it to dec first")
            return self.elementwise(UNARY_OPS[type(node.op)], [operand], "arithmetic")
        if isinstance(node, ast.Compare):
            return self.compare(node)
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                value = self.variables[node.id]
                if isinstance(value, Function):
                    return self.apply(value, None)
                return value
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise EvlError(f"unknown variable '{node.id}'")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.call(node)
        raise EvlError(f"unsupported expression: {ast.unparse(node)}")

    def define_function(self, node):
        """__function__("f", [x, y], body), from the rewritten `f(x, y) = body`."""
        name, params, body = node.args
        if isinstance(body, ast.Constant) and body.value is None:
            raise EvlError(f"{name.value}: missing formula after '='")
        names = [p.id for p in params.elts]
        for param in names:
            if param in RESERVED:
                raise EvlError(f"{name.value}: '{param}' is a built-in name, pick another parameter name")
        if len(set(names)) != len(names):
            raise EvlError(f"{name.value}: parameter names must be different")
        return Function(name.value, names, body)

    def apply(self, func, args):
        """Compute func's formula. args=None (a plain `f`) uses the current
        values of its parameters; otherwise they're bound to args for the call."""
        if args is None:
            missing = [p for p in func.params if p not in self.variables]
            if missing:
                call = f"{func.name}({', '.join('2' for _ in func.params)})"
                raise EvlError(
                    f"'{func.name}' is a function of {', '.join(func.params)}: "
                    f"call it like {call}, or define {missing[0]} first"
                )
        elif len(args) != len(func.params):
            raise EvlError(
                f"{func.name} takes {len(func.params)} argument{'s' * (len(func.params) != 1)}, "
                f"got {len(args)}"
            )
        if func.name in self.active:
            raise EvlError(f"'{func.name}' is defined in terms of itself")

        saved = {p: self.variables.get(p, _MISSING) for p in func.params}
        if args is not None:
            self.variables.update(zip(func.params, args))
        self.active.add(func.name)
        try:
            return self.eval(func.body)
        finally:
            self.active.discard(func.name)
            for param, value in saved.items():
                if value is _MISSING:
                    self.variables.pop(param, None)
                else:
                    self.variables[param] = value

    def compare(self, node):
        """a < b, or a chain like -0.5 < f < 0.5 (every comparison must hold).

        With numbers only, the answer is true / false. With a list, keep the
        elements that pass: [0, 1, 2, 3, 4] < 3 -> [0, 1, 2]. If several sides
        are lists, the first list in the chain is the one filtered.
        """
        if any(type(op) not in COMPARE_OPS for op in node.ops):
            raise EvlError("supported comparisons are <, <=, > and >=")
        operands = [self.eval(node.left)] + [self.eval(c) for c in node.comparators]
        for side in operands:
            if isinstance(side, str):
                raise EvlError("can't compare a bin/oct/hex result; convert it to dec first")
            if isinstance(side, (PlotStyle, Plot)):
                raise EvlError("can only compare numbers, ranges and lists")

        results = [
            self.elementwise(COMPARE_OPS[type(op)], [operands[i], operands[i + 1]], "comparison")
            for i, op in enumerate(node.ops)
        ]
        masks = [r for r in results if isinstance(r, Vector)]
        if not masks:
            return all(results)  # numbers only: true / false
        if not all(results[i] for i in range(len(results)) if not isinstance(results[i], Vector)):
            keep = [False] * len(masks[0].values)  # e.g. 3 < 2 < f: nothing passes
        else:
            if any(len(m.values) != len(masks[0].values) for m in masks):
                raise EvlError("comparison: lists have different lengths")
            keep = [all(m.values[i] for m in masks) for i in range(len(masks[0].values))]
        source = next(side for side in operands if isinstance(side, Vector))
        return filter_vector(source, keep)

    def call(self, node):
        name = node.func.id
        if node.keywords:
            raise EvlError("keyword arguments are not supported")
        if name == DEFINE_FN:
            return self.define_function(node)
        if isinstance(self.variables.get(name), Function):
            args = [self.eval(arg) for arg in node.args]
            if any(isinstance(arg, (str, Plot, PlotStyle, Function)) for arg in args):
                raise EvlError(f"{name}: expects numbers, ranges or lists")
            return self.apply(self.variables[name], args)
        if name in self.variables:
            raise EvlError(f"'{name}' is a variable, not a function")
        if name in CONVERSIONS:
            return self.convert(node)
        if name == STYLE_FN:
            index = node.args[0].value if len(node.args) == 1 and isinstance(node.args[0], ast.Constant) else None
            if not isinstance(index, int) or not 0 <= index < len(self.styles):
                raise EvlError(f"unknown function '{name}'")
            return self.make_style(index)
        if name in CALCULUS_FUNCTIONS and len(node.args) != 1:
            return self.calculus(name, node.args)  # expression form: the expression isn't evaluated yet
        if name == SHOW_FN:
            columns = [[self.eval(item) for item in col.elts] for col in node.args[0].elts]
            return self.show(columns)
        if name == "show":
            raise EvlError("show is a statement on its own, e.g. show plot(f) : plot(g)")

        args = [self.eval(arg) for arg in node.args]
        if any(isinstance(arg, str) for arg in args):
            raise EvlError(f"{name}: expects numbers, convert bin/oct/hex to dec first")
        if name == "range":
            return make_range(args)
        if name in CALCULUS_FUNCTIONS:  # one argument: a list
            return list_calculus(name, args[0])
        if name == "plot":
            return self.plot(args)
        if name in REDUCERS and len(args) == 1 and isinstance(args[0], Vector):
            if not args[0].values:
                raise EvlError(f"{name}: the list is empty")
            return REDUCERS[name](args[0].values)
        if any(isinstance(arg, PlotStyle) for arg in args):
            raise EvlError(f"{name}: a plotstyle can only be passed to plot()")
        if any(isinstance(arg, Plot) for arg in args):
            raise EvlError(f"{name}: expects numbers, not a plot")

        func = FUNCTIONS.get(name)
        if func is None:
            if name in REDUCERS:
                raise EvlError(f"{name} takes a single list or range, e.g. {name}(x)")
            raise EvlError(f"unknown function '{name}'")
        return self.elementwise(func, args, name)

    def elementwise(self, func, args, name):
        """Call func on numbers, or on each element when any arg is a Vector."""
        vectors = [a for a in args if isinstance(a, Vector)]
        try:
            if not vectors:
                return func(*args)
            length = len(vectors[0].values)
            if any(len(v.values) != length for v in vectors):
                sizes = " and ".join(str(len(v.values)) for v in vectors)
                raise EvlError(f"{name}: lists have different lengths ({sizes})")
            with_domain = next((v for v in vectors if v.domain is not None), vectors[0])
            domain, gaps = with_domain.domain, with_domain.gaps
            values = [
                func(*[a.values[i] if isinstance(a, Vector) else a for a in args])
                for i in range(length)
            ]
            return Vector(values, domain, gaps)
        except ZeroDivisionError:
            raise EvlError("division by zero") from None
        except OverflowError:
            raise EvlError("result too large") from None
        except (ValueError, TypeError) as exc:
            raise EvlError(f"{name}: {exc}") from None

    # ---- calculus (numeric) -------------------------------------------------

    def calculus(self, name, arg_nodes):
        usage = {
            "integral": "integral(expr, x, a, b) or integral(f) for a list",
            "derivative": "derivative(expr, x, point) or derivative(f) for a list",
            "limit": 'limit(expr, x, point) or limit(expr, x, point, "+")',
        }[name]
        counts = {"integral": (4,), "derivative": (3,), "limit": (3, 4)}[name]
        if len(arg_nodes) not in counts:
            raise EvlError(f"usage: {usage}")
        expr, var_node, *rest = arg_nodes
        if not isinstance(var_node, ast.Name) or var_node.id in RESERVED:
            raise EvlError(f"{name}: the second argument must be a variable name, e.g. {usage}")
        var = var_node.id

        direction = 0
        if name == "limit" and len(rest) == 2:
            side = self.eval(rest.pop())
            directions = {"+": 1, "right": 1, "-": -1, "left": -1}
            if side not in directions:
                raise EvlError('limit: the direction must be "+" (from the right) or "-" (from the left)')
            direction = directions[side]

        points = [self.eval(n) for n in rest]
        for point in points:
            if not (is_number(point) or isinstance(point, Vector)):
                raise EvlError(f"{name}: points and bounds must be numbers or ranges")

        def f(value):
            saved = self.variables.get(var, _MISSING)
            self.variables[var] = value
            try:
                result = self.eval(expr)
            finally:
                if saved is _MISSING:
                    del self.variables[var]
                else:
                    self.variables[var] = saved
            if not is_number(result):
                raise EvlError(f"{name}: the expression must give a single number for each {var}")
            return float(result)

        if name == "integral":
            compute = lambda a, b: round_sig(integrate(f, a, b, var))
        elif name == "derivative":
            compute = lambda p: round_sig(differentiate(f, p, var), 10)
        else:
            compute = lambda p: round_sig(take_limit(f, p, direction, var), 10)
        return self.elementwise(compute, points, name)  # a range of points gives a list

    def convert(self, node):
        name = node.func.id
        src, dst = CONVERSIONS[name]
        if len(node.args) != 1:
            raise EvlError(f"{name} takes exactly one argument")
        value = self.eval(node.args[0])
        if isinstance(value, (Vector, PlotStyle, Plot)):
            raise EvlError(f"{name}: works on a single number, not a list")

        if src == 10:
            if isinstance(value, str):
                raise EvlError(f"{name}: expects a number, got '{value}'")
            if isinstance(value, float):
                if not value.is_integer():
                    raise EvlError(f"{name}: needs a whole number, got {format_number(value)}")
                value = int(value)
            number = value
        else:
            if not isinstance(value, str):
                raise EvlError(f"{name}: expects {name[:3]} digits, e.g. {name}(1f)")
            try:
                number = int(value, src)  # accepts 0x/0b/0o prefixes and '_'
            except ValueError:
                # Not valid digits: maybe it's a variable holding a converted result.
                stored = self.variables.get(value)
                if isinstance(stored, str):
                    try:
                        number = int(stored, src)
                    except ValueError:
                        number = None
                else:
                    number = None
                if number is None:
                    raise EvlError(f"{name}: '{value}' is not a valid {name[:3]} number") from None

        if dst == 10:
            return number
        return format(number, BASE_FORMATS[dst])

    # ---- plotting ----------------------------------------------------------

    def make_style(self, index):
        name, header_no, entries = self.styles[index]
        options = {}
        for line_no, key, raw in entries:
            try:
                options[key] = self.style_option(key, parse_style_value(raw))
            except (EvlError, ValueError) as exc:
                raise EvlError(f"line {line_no}: plotstyle {name}, {key}: {exc}") from None
        return PlotStyle(name, options)

    def style_option(self, key, value):
        if key not in STYLE_KEYS:
            raise EvlError(f"unknown option (options: {', '.join(STYLE_KEYS)})")
        if not value:
            raise EvlError("missing value")
        if key == "linestyle":
            return pick(value, LINESTYLES)
        if key == "marker":
            return pick(value, MARKERS)
        if key in ("linewidth", "markersize"):
            match = re.fullmatch(r"(\d+(?:\.\d*)?|\.\d+)\s*(px|pt)?", value)
            if not match:
                raise EvlError(f"expected a size like '2 px' or '1.5 pt', got '{value}'")
            return float(match.group(1)), match.group(2) or "px"
        if key in ("linecolor", "markercolor"):
            colors = load_matplotlib_colors()
            if colors and not colors.is_color_like(value):
                raise EvlError(f"unknown color '{value}' (use a name like blue or \"#rrggbb\")")
            return value
        if key in ("xrange", "yrange"):
            limits = self.eval(ast.parse(preprocess_expression(value), mode="eval").body)
            if not isinstance(limits, Vector) or len(limits.values) != 2:
                raise EvlError(f"expected [min, max], got '{value}'")
            low, high = limits.values
            if not low < high:
                raise EvlError("min must be smaller than max")
            return low, high
        if key == "grid":
            return pick(value, {"on": True, "yes": True, "true": True,
                                "off": False, "no": False, "false": False})
        return value  # title, xlabel, ylabel

    def plot(self, args):
        """plot(f) or plot(f, style): describe a plot. Nothing is drawn until shown."""
        if not 1 <= len(args) <= 2:
            raise EvlError("plot takes a list and an optional plotstyle, e.g. plot(f, ps); "
                           "use plot(f) + plot(g) to draw several in one plot")
        data = args[0]
        style = args[1] if len(args) == 2 else None
        if isinstance(data, PlotStyle):
            raise EvlError("plot: the list comes first, then the plotstyle: plot(f, ps)")
        if not isinstance(data, Vector):
            raise EvlError("plot: expects a range or list, e.g. plot(cos(x))")
        if style is not None and not isinstance(style, PlotStyle):
            raise EvlError("plot: the second argument must be a plotstyle; "
                           "use plot(f) + plot(g) to draw several in one plot")
        return Plot([(data, style)])

    def show(self, columns):
        """Open one window: columns left to right, plots in a column top to bottom."""
        for column in columns:
            for i, item in enumerate(column):
                if isinstance(item, Vector):
                    column[i] = Plot([(item, None)])  # `show f` is short for `show plot(f)`
                elif not isinstance(item, Plot):
                    raise EvlError("show: expects plots, e.g. show plot(f) : plot(g)")

        plt = load_pyplot()
        rows = max(len(column) for column in columns)
        width = 6.4 if len(columns) == 1 else min(5.0 * len(columns), 16)
        height = 4.8 if rows == 1 else min(3.2 * rows, 10)
        fig = plt.figure(figsize=(width, height), layout="constrained")
        names = sorted({style.name for column in columns for plot in column
                        for _, style in plot.layers if style is not None})
        fig.canvas.manager.set_window_title("evl" + (f" - {', '.join(names)}" if names else ""))

        grid = fig.add_gridspec(1, len(columns))
        for c, column in enumerate(columns):
            cells = grid[c].subgridspec(len(column), 1)
            for r, plot in enumerate(column):
                self.draw(fig, fig.add_subplot(cells[r]), plot)

        self.figures += 1
        if interactive_session():
            plt.show(block=False)
            plt.pause(0.05)
        return None

    def draw(self, fig, ax, plot):
        def points(size):
            number, unit = size
            return number * 72 / fig.dpi if unit == "px" else number

        axes_options = {}  # xrange, title, ...: the first layer that sets one wins
        for vector, style in plot.layers:
            options = style.options if style else {}
            for key in ("xrange", "yrange", "title", "xlabel", "ylabel", "grid"):
                if key in options:
                    axes_options.setdefault(key, options[key])

            kwargs = {}
            if "linestyle" in options:
                kwargs["linestyle"] = options["linestyle"]
            if "linewidth" in options:
                kwargs["linewidth"] = points(options["linewidth"])
            if "marker" in options:
                kwargs["marker"] = options["marker"]
            if "markersize" in options:
                kwargs["markersize"] = points(options["markersize"])
            if "linecolor" in options:
                kwargs["color"] = options["linecolor"]
            if "markercolor" in options:
                kwargs["markerfacecolor"] = kwargs["markeredgecolor"] = options["markercolor"]

            xs = vector.domain if vector.domain is not None else list(range(len(vector.values)))
            ys = vector.values
            if vector.gaps:  # break the line where a comparison removed values
                xs, ys = list(xs), list(ys)
                for i in sorted(vector.gaps, reverse=True):
                    xs.insert(i, math.nan)
                    ys.insert(i, math.nan)
            ax.plot(xs, ys, **kwargs)

        if "xrange" in axes_options:
            ax.set_xlim(*axes_options["xrange"])
        if "yrange" in axes_options:
            ax.set_ylim(*axes_options["yrange"])
        for key, setter in (("title", ax.set_title), ("xlabel", ax.set_xlabel),
                            ("ylabel", ax.set_ylabel)):
            if key in axes_options:
                setter(axes_options[key])
        if axes_options.get("grid"):
            ax.grid(True)


_MISSING = object()


def round_sig(value, digits=12):
    """Hide numerical noise: 0.9999999999999998 -> 1.0."""
    if not math.isfinite(value) or value == 0:
        return value
    return float(f"{value:.{digits}g}") + 0.0


# Gauss-Kronrod 7-15 nodes and weights (positive half; node 0 is the center).
GK_NODES = (0.991455371120812639206854697526329, 0.949107912342758524526189684047851,
            0.864864423359769072789712788640926, 0.741531185599394439863864773280788,
            0.586087235467691130294144845693013, 0.405845151377397166906606412076961,
            0.207784955007898467600689403773245, 0.0)
GK_WEIGHTS = (0.022935322010529224963732008058970, 0.063092092629978553290700663189204,
              0.104790010322250183839876322541518, 0.140653259715525918745189590510238,
              0.169004726639267902826583426598550, 0.190350578064785409913256402421014,
              0.204432940075298892414161999234649, 0.209482141084727828012999174891714)
GAUSS_WEIGHTS = (0.129484966168869693270611432679082, 0.279705391489276667901467771423780,
                 0.381830050505118944950369775488975, 0.417959183673469387755102040816327)


class InfiniteValue(EvlError):
    pass


def evaluate_at(f, x, name, var):
    try:
        y = f(x)
    except (ZeroDivisionError, OverflowError):  # e.g. 1 / (1 - t) in an infinite-bound mapping
        raise InfiniteValue(f"{name}: the expression is infinite near {var} = {format_number(round_sig(x))}") from None
    except EvlError as exc:
        if str(exc).startswith(name + ":"):
            raise
        raise EvlError(f"{name}: can't evaluate at {var} = {format_number(round_sig(x))} ({exc})") from None
    if not math.isfinite(y):
        raise InfiniteValue(f"{name}: the expression is infinite at {var} = {format_number(round_sig(x))}")
    return y


def integrate(f, a, b, var):
    """Adaptive Gauss-Kronrod integration; infinite bounds are mapped to finite ones."""
    import heapq

    if a == b:
        return 0.0
    if a > b:
        return -integrate(f, b, a, var)
    if math.isinf(a) and math.isinf(b):
        g = lambda t: f(t / (1 - t * t)) * (1 + t * t) / (1 - t * t) ** 2
        lo, hi = -1.0, 1.0
    elif math.isinf(b):
        g = lambda t: f(a + t / (1 - t)) / (1 - t) ** 2
        lo, hi = 0.0, 1.0
    elif math.isinf(a):
        g = lambda t: f(b - (1 - t) / t) / (t * t)
        lo, hi = 0.0, 1.0
    else:
        g, lo, hi = f, a, b

    def gauss_kronrod(lo, hi):
        center, half = (lo + hi) / 2, (hi - lo) / 2
        mid = evaluate_at(g, center, "integral", var)
        kronrod, gauss = GK_WEIGHTS[7] * mid, GAUSS_WEIGHTS[3] * mid
        magnitude[0] += GK_WEIGHTS[7] * abs(mid) * half
        for i in range(7):
            left = evaluate_at(g, center - half * GK_NODES[i], "integral", var)
            right = evaluate_at(g, center + half * GK_NODES[i], "integral", var)
            kronrod += GK_WEIGHTS[i] * (left + right)
            magnitude[0] += GK_WEIGHTS[i] * (abs(left) + abs(right)) * half
            if i % 2 == 1:
                gauss += GAUSS_WEIGHTS[i // 2] * (left + right)
        return kronrod * half, abs((kronrod - gauss) * half)

    magnitude = [0.0]  # roughly the area of |f| (summed over all evaluations)

    def result(total):  # sin over a full period gives 1e-16: that's 0
        return 0.0 if abs(total) <= 1e-13 * magnitude[0] else total

    def diverges():
        return EvlError("integral: doesn't converge (the area may be infinite)")

    try:
        value, error = gauss_kronrod(lo, hi)
    except InfiniteValue:
        raise diverges() from None
    heap = [(-error, lo, hi, value)]
    total, total_error = value, error
    for _ in range(3000):
        if total_error <= max(1e-15, 1e-13 * abs(total)):
            return result(total)
        neg_error, lo, hi, value = heapq.heappop(heap)
        mid = (lo + hi) / 2
        if mid in (lo, hi):
            break  # can't split any further
        try:
            left, left_error = gauss_kronrod(lo, mid)
            right, right_error = gauss_kronrod(mid, hi)
        except InfiniteValue:
            raise diverges() from None
        total += left + right - value
        total_error += left_error + right_error + neg_error
        heapq.heappush(heap, (-left_error, lo, mid, left))
        heapq.heappush(heap, (-right_error, mid, hi, right))
    if total_error <= max(1e-9, 1e-8 * abs(total)):
        return result(total)  # not to full precision, but close enough to be useful
    raise diverges()


def differentiate(f, x, var):
    """Ridders' method: central differences with Richardson extrapolation."""
    if not math.isfinite(x):
        raise EvlError("derivative: the point must be a finite number")
    fx = evaluate_at(f, x, "derivative", var)

    # A kink (like abs(x) at 0) has different slopes on each side.
    h = 1e-6 * max(1.0, abs(x))
    try:
        forward = (evaluate_at(f, x + h, "derivative", var) - fx) / h
        backward = (fx - evaluate_at(f, x - h, "derivative", var)) / h
    except EvlError:
        raise EvlError(f"derivative: the expression isn't defined on both sides of "
                       f"{var} = {format_number(x)}") from None
    if abs(forward - backward) > 1e-2 * max(1.0, abs(forward), abs(backward)):
        raise EvlError(f"derivative: not differentiable at {var} = {format_number(x)} "
                       f"(slope {format_number(round_sig(backward, 6))} from the left, "
                       f"{format_number(round_sig(forward, 6))} from the right)")

    def central(step):
        try:
            estimate = (f(x + step) - f(x - step)) / (2 * step)
        except EvlError:
            return None
        return estimate if math.isfinite(estimate) else None

    # Start with a step that stays well inside where the expression is defined
    # (e.g. sqrt near 0).
    start = 0.1 * abs(x) if x != 0 else 0.1  # don't reach across 0, e.g. 1/x at 0.001
    step = start
    while central(step) is None and step > h:
        step /= 10
    if step < start:
        step /= 4

    shrink, best, best_error, table = 1.4, None, math.inf, []
    for i in range(12):
        estimate = central(step)
        if estimate is None:
            break
        row = [estimate]
        factor = shrink * shrink
        for j in range(1, len(table) + 1):
            row.append((row[j - 1] * factor - table[-1][j - 1]) / (factor - 1))
            factor *= shrink * shrink
            err = max(abs(row[j] - row[j - 1]), abs(row[j] - table[-1][j - 1]))
            if err <= best_error:
                best, best_error = row[j], err
        if table and abs(row[-1] - table[-1][-1]) >= 2 * best_error:
            break
        table.append(row)
        step /= shrink
    if best is None:
        if table:
            return table[-1][0]
        raise EvlError(f"derivative: can't evaluate near {var} = {format_number(x)}")
    if best_error > 1e-6 * max(1.0, abs(best)):
        raise EvlError(f"derivative: can't be computed reliably at {var} = {format_number(x)}")
    return best


def one_sided_limit(f, point, side, var):
    """Limit of f approaching point from one side (side = +1 right, -1 left).
    Returns None when f isn't defined on that side."""
    def g(h):
        if math.isinf(point):
            return f(math.copysign(1 / h, point))  # x = 10, 20, 40, ... towards +-inf
        return f(point + side * h)

    hs = [0.1 * max(1.0, abs(point) if math.isfinite(point) else 1.0) * 0.5 ** k for k in range(26)]
    samples = []
    for h in hs:
        try:
            y = g(h)
        except EvlError:
            continue
        if math.isnan(y):
            continue
        samples.append((h, y))
    if len(samples) < 4:
        return None

    # Growing without bound: the limit is infinite. Each halving of the distance
    # moves the value at least as much as the last one did (a converging
    # function moves less and less: about half as much each time).
    tail = [y for _, y in samples[-8:]]
    if all(math.isinf(y) for y in tail[-3:]):
        return math.copysign(math.inf, tail[-1])
    steps = [b - a for a, b in zip(tail, tail[1:])]
    if (all(math.copysign(1, y) == math.copysign(1, tail[-1]) for y in tail)
            and all(abs(b) > abs(a) for a, b in zip(tail, tail[1:]))
            and all(abs(b) >= 0.9 * abs(a) for a, b in zip(steps, steps[1:]))
            and abs(tail[-1]) > 10):
        return math.copysign(math.inf, tail[-1])

    # Richardson extrapolation to h = 0 (expansion in powers of h). Only the
    # larger steps are used: very small ones lose precision to cancellation,
    # as in (1 - cos(x)) / x^2.
    best, best_error, table = None, math.inf, []
    for h, y in samples[:10]:
        row = [y]
        for j in range(1, len(table) + 1):
            row.append((row[j - 1] * 2 ** j - table[-1][j - 1]) / (2 ** j - 1))
            err = max(abs(row[j] - row[j - 1]), abs(row[j] - table[-1][j - 1]))
            if err <= best_error:
                best, best_error = row[j], err
        table.append(row)
    largest = max(abs(y) for _, y in samples)

    def clean(value):  # 1e-43 when the samples were ~0.1: the limit is 0
        return 0.0 if abs(value) <= 1e-9 * largest else value

    if best is not None and math.isfinite(best) and best_error <= 1e-9 * max(1.0, abs(best)):
        return clean(best)

    # Fallback for values that approach like sqrt(h) or h * log(h): repeated
    # Aitken's delta-squared on all samples.
    values = [y for _, y in samples]
    last = values[-6:]
    spread = max(last) - min(last)
    estimates = []
    for _ in range(4):  # deeper levels amplify noise into fake agreement
        accelerated = []
        for a, b, c in zip(values, values[1:], values[2:]):
            denom = (c - b) - (b - a)
            if denom != 0:
                accelerated.append(c - (c - b) ** 2 / denom)
        values = [v for v in accelerated if math.isfinite(v)]
        if len(values) < 3:
            break
        estimates.append((max(values[-3:]) - min(values[-3:]), values[-1]))
    # Accept only if it agrees with where the samples are heading.
    candidates = [(err, value) for err, value in estimates
                  if err <= 1e-9 * max(1.0, abs(value)) and abs(value - last[-1]) <= 10 * spread + 1e-12]
    if candidates:
        return clean(min(candidates)[1])

    # The samples themselves have settled (e.g. x * sin(1/x) at 0): use the
    # last one, rounded to the precision the spread allows.
    if spread <= 1e-6 * max(1.0, largest):
        if spread == 0:
            return clean(last[-1])
        return clean(round(last[-1], -math.floor(math.log10(spread)) - 1))
    if best is not None and math.isfinite(best) and best_error <= 1e-6 * max(1.0, abs(best)):
        return clean(best)
    raise EvlError(f"limit: doesn't settle on a value as {var} approaches "
                   f"{format_number(point)} (it may not exist)")


def take_limit(f, point, direction, var):
    sides = [direction] if direction else ([-1] if point == math.inf else [1] if point == -math.inf else [1, -1])
    results = {side: one_sided_limit(f, point, side, var) for side in sides}
    found = {side: value for side, value in results.items() if value is not None}
    if not found:
        raise EvlError(f"limit: the expression isn't defined near {var} = {format_number(point)}")
    if len(found) == 2:
        right, left = found[1], found[-1]
        same = right == left or (math.isfinite(right) and math.isfinite(left)
                                 and abs(right - left) <= 1e-6 * max(1.0, abs(right), abs(left)))
        if not same:
            raise EvlError(f"limit: left and right limits differ ({format_number(round_sig(left))} "
                           f"from the left, {format_number(round_sig(right))} from the right); "
                           f'use limit(expr, {var}, {format_number(point)}, "+") or "-"')
        return (right + left) / 2 if math.isfinite(right) else right
    return next(iter(found.values()))


def list_calculus(name, f):
    """derivative(f) / integral(f) for a list: slope at each point / running area."""
    if name == "limit":
        raise EvlError('limit needs an expression: limit(expr, x, point)')
    if not isinstance(f, Vector):
        raise EvlError(f"{name}: expects a range or list, or {name}(expr, x, ...)")
    xs = f.domain if f.domain is not None else list(range(len(f.values)))
    ys = f.values
    # Points separated by a gap (removed by a comparison) aren't connected.
    segments, start = [], 0
    for i in range(1, len(ys) + 1):
        if i == len(ys) or i in f.gaps:
            segments.append((start, i))
            start = i

    out = []
    if name == "derivative":
        for lo, hi in segments:
            if hi - lo < 2:
                raise EvlError("derivative: needs at least 2 neighbouring points")
            for i in range(lo, hi):
                if i == lo:
                    out.append((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]))
                elif i == hi - 1:
                    out.append((ys[i] - ys[i - 1]) / (xs[i] - xs[i - 1]))
                else:  # central difference, also correct for uneven spacing
                    h1, h2 = xs[i] - xs[i - 1], xs[i + 1] - xs[i]
                    out.append((h1 * h1 * ys[i + 1] - h2 * h2 * ys[i - 1] + (h2 * h2 - h1 * h1) * ys[i])
                               / (h1 * h2 * (h1 + h2)))
    else:
        area = 0.0
        for lo, hi in segments:
            for i in range(lo, hi):
                if i > lo:
                    area += (xs[i] - xs[i - 1]) * (ys[i] + ys[i - 1]) / 2  # trapezoid rule
                out.append(area)
    return Vector([round_sig(v) for v in out], f.domain, f.gaps)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def pick(value, choices):
    key = value.lower()
    if key not in choices:
        raise EvlError(f"'{value}' is not one of: {', '.join(choices)}")
    return choices[key]


def filter_vector(vector, keep):
    """The elements of vector where keep is true, with their x positions."""
    kept = [i for i, ok in enumerate(keep) if ok]
    gaps = frozenset(
        j for j, i in enumerate(kept)
        if j > 0 and (i != kept[j - 1] + 1 or i in vector.gaps)
    )
    # A plain list is plotted against positions 0, 1, 2, ...: keep the originals.
    domain = kept if vector.domain is None else [vector.domain[i] for i in kept]
    return Vector([vector.values[i] for i in kept], domain, gaps)


def make_range(args):
    """range(start, step, end): start, start+step, ..., end (end included)."""
    if len(args) != 3 or not all(is_number(a) for a in args):
        raise EvlError("range takes three numbers: range(start, step, end)")
    start, step, end = args
    if step == 0:
        raise EvlError("range: step can't be 0")
    count = math.floor((end - start) / step + 1e-9) + 1
    if count <= 0:
        raise EvlError(f"range: can't get from {format_number(start)} to "
                       f"{format_number(end)} with step {format_number(step)}")
    if count > MAX_RANGE:
        raise EvlError(f"range: too many values ({count}), the limit is {MAX_RANGE}")
    values = []
    for i in range(count):
        value = start + i * step
        if isinstance(value, float):
            value = round(value, 12) + 0.0  # 0.30000000000000004 -> 0.3, -0.0 -> 0.0
        values.append(value)
    vector = Vector(values)
    vector.domain = vector.values  # a range is its own horizontal axis
    return vector


_PYPLOT = None
_INTERACTIVE = False


def interactive_session():
    return _INTERACTIVE


def load_matplotlib_colors():
    try:
        import matplotlib.colors
    except ImportError:
        return None
    return matplotlib.colors


def load_pyplot():
    global _PYPLOT
    if _PYPLOT is None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            raise EvlError("plot needs matplotlib: pip install --user matplotlib") from None
        _PYPLOT = plt
        if _INTERACTIVE:
            install_input_hook()
    return _PYPLOT


# While readline waits for a keypress it calls PyOS_InputHook (every 0.1 s, and
# with the GIL released). Nothing else runs the GUI event loop at that point,
# so without a hook the plot windows freeze until the next line is entered.
_INPUT_HOOK = None
_SAVED_TERMINAL = None


def _pump_plot_events():
    """Process plot window events until a key is pressed or all plots are closed."""
    import select
    from matplotlib._pylab_helpers import Gcf

    fd = sys.stdin.fileno()
    while True:
        managers = Gcf.get_all_fig_managers()
        if not managers:
            return
        for manager in managers:
            manager.canvas.flush_events()
        ready, _, _ = select.select([fd], [], [], 0.02)
        if ready:
            return


def _input_hook():
    try:
        _pump_plot_events()
    except KeyboardInterrupt:
        # Ctrl-C arrives here, inside a C callback where an exception can't
        # propagate. Exit like Ctrl-C does elsewhere, restoring the terminal
        # that readline put in raw mode.
        if _SAVED_TERMINAL is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _SAVED_TERMINAL)
        sys.stdout.write("\n")
        sys.stdout.flush()
        sys.stderr.flush()
        import os
        os._exit(130)
    except Exception:
        pass  # never let a plotting problem break line input
    return 0


def install_input_hook():
    global _INPUT_HOOK, _SAVED_TERMINAL
    if _INPUT_HOOK is not None:
        return
    try:
        import ctypes
        import termios
        _SAVED_TERMINAL = termios.tcgetattr(sys.stdin.fileno())
        _INPUT_HOOK = ctypes.CFUNCTYPE(ctypes.c_int)(_input_hook)
        ctypes.c_void_p.in_dll(ctypes.pythonapi, "PyOS_InputHook").value = (
            ctypes.cast(_INPUT_HOOK, ctypes.c_void_p).value
        )
    except Exception:
        _INPUT_HOOK = None  # plots still work, they just freeze between lines


def remove_input_hook():
    global _INPUT_HOOK
    if _INPUT_HOOK is None:
        return
    import ctypes
    ctypes.c_void_p.in_dll(ctypes.pythonapi, "PyOS_InputHook").value = None
    _INPUT_HOOK = None


def show_plots(evaluator):
    """Keep plot windows open until the user closes them."""
    if evaluator.figures and _PYPLOT is not None and _PYPLOT.get_fignums():
        if _PYPLOT.get_backend().lower() in ("agg", "pdf", "ps", "svg", "cairo", "template"):
            print("warning: no display available, plot windows can't be shown", file=sys.stderr)
            return
        _PYPLOT.show()


# ---- output ----------------------------------------------------------------

def format_number(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return str(value)


def format_value(value):
    if isinstance(value, Vector):
        items = [format_number(v) for v in value.values]
        if len(items) > 50:
            items = items[:10] + ["..."] + items[-10:]
            return f"[{', '.join(items)}] ({len(value.values)} values)"
        return f"[{', '.join(items)}]"
    if isinstance(value, PlotStyle):
        return f"plotstyle {value.name}"
    if isinstance(value, Plot):
        return "plot"
    if isinstance(value, Function):
        return str(value)
    return format_number(value)


def evaluate_and_print(evaluator, source):
    """Run source, print the answer or the error. Return True on success.

    On error, variables are rolled back so a failed block has no effect.
    """
    saved = dict(evaluator.variables)
    try:
        result = evaluator.run(source)
    except EvlError as exc:
        evaluator.variables = saved
        print(f"error: {exc}", file=sys.stderr)
        return False
    if result is not None:
        print(f"ans: {format_value(result)}")
    return True


# ---- input modes -----------------------------------------------------------

def multiline_session():
    """Interactive mode: lines ending in ';' are collected, a line without one
    evaluates everything collected so far and prints the answer. Variables
    persist between answers. An empty line (or Ctrl-D) ends the session.

    A `plotstyle NAME:` line starts a block of indented lines, ended by an
    empty line or the next unindented line.
    """
    global _INTERACTIVE
    if sys.stdin.isatty():
        _INTERACTIVE = True
        try:
            import readline  # noqa: F401  (arrow keys and history for input())
        except ImportError:
            pass

    def read_line():
        try:
            return input()
        except EOFError:
            return None

    evaluator = Evaluator()
    pending = []
    ok = True
    line = read_line()
    while line is not None:
        stripped = line.strip()
        if not stripped:
            break
        if STYLE_HEADER.match(line):
            block = [line]
            line = read_line()
            while line is not None and line.strip() and line[0] in " \t":
                block.append(line)
                line = read_line()
            ok = evaluate_and_print(evaluator, "\n".join(pending + block)) and ok
            pending = []
            if line is not None and not line.strip():
                line = read_line()  # an empty line only closes the block
            continue
        pending.append(line)
        if not stripped.endswith(";"):
            ok = evaluate_and_print(evaluator, "\n".join(pending)) and ok
            pending = []
        line = read_line()

    # Don't silently drop statements still waiting for an answer line.
    if pending:
        ok = evaluate_and_print(evaluator, "\n".join(pending)) and ok
    remove_input_hook()
    show_plots(evaluator)
    return 0 if ok else 1


def read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise EvlError(f"cannot read '{path}': {exc.strerror}") from None
    except UnicodeDecodeError:
        raise EvlError(f"cannot read '{path}': not a text file") from None


def main(argv):
    try:
        if argv and argv[0] in ("-f", "--file"):
            if len(argv) != 2:
                raise EvlError("usage: evl -f FILENAME")
            source = read_file(argv[1])
        elif argv:
            source = " ".join(argv)
        else:
            return multiline_session()
    except EvlError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not source.strip():
        return 0

    evaluator = Evaluator()
    ok = evaluate_and_print(evaluator, source)
    show_plots(evaluator)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
