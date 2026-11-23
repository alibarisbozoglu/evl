"""The evaluator: walks the parsed statements and computes them safely
(only whitelisted syntax, names and functions)."""

import ast
import re

from .calculus import CalculusMixin, list_calculus
from .names import (
    BASE_FORMATS, BIN_OPS, CALCULUS_FUNCTIONS, COMPARE_OPS, CONSTANTS, CONVERSIONS,
    DEFINE_FN, FUNCTIONS, REDUCERS, RESERVED, SHOW_FN, STYLE_FN, UNARY_OPS,
)
from .plotting import PlottingMixin
from .syntax import extract_plotstyles, preprocess_expression, rewrite_show_statements
from .values import (
    _MISSING, EvlError, Function, Plot, PlotStyle, Vector,
    filter_vector, format_number, is_number, make_range,
)


class Evaluator(CalculusMixin, PlottingMixin):
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
