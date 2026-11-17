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
import math
import operator
import re
import sys

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
SPECIAL_FUNCTIONS = {"range", "plot", STYLE_FN}
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
    "markercolor", "xrange", "yrange", "title", "xlabel", "ylabel", "grid",
)


class EvlError(Exception):
    pass


class Vector:
    """A list of numbers, e.g. from range(). `domain` is the range it was
    computed from (if any), used as the horizontal axis when plotting."""

    __slots__ = ("values", "domain")

    def __init__(self, values, domain=None):
        self.values = list(values)
        self.domain = domain


class PlotStyle:
    def __init__(self, name, options):
        self.name = name
        self.options = options


def preprocess_expression(source):
    source = RANGE3.sub(r"range(\1,\2,\3)", source)
    source = RANGE2.sub(r"range(\1,1,\2)", source)
    source = DIGITS_ARG.sub(r'\1("\2")', source)
    return source.replace("^", "**")  # allow 2^3 as power


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

    def run(self, source):
        """Evaluate ';' / newline separated statements, return the last value."""
        multiline = "\n" in source.strip()
        source, self.styles = extract_plotstyles(source)
        source = preprocess_expression(source)
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
            value = self.eval(stmt.value)
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    raise EvlError("can only assign to simple names")
                if target.id in RESERVED:
                    raise EvlError(f"cannot assign to built-in '{target.id}'")
                self.variables[target.id] = value
            # Defining a plotstyle block isn't a calculation: print nothing.
            return None if isinstance(value, PlotStyle) else value
        if isinstance(stmt, ast.Expr):
            return self.eval(stmt.value)
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
            if isinstance(left, str) or isinstance(right, str):
                raise EvlError(
                    "can't do arithmetic on a bin/oct/hex result; "
                    "convert it to dec first, e.g. hex2dec(...)"
                )
            return self.elementwise(BIN_OPS[type(node.op)], [left, right], "arithmetic")
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            operand = self.eval(node.operand)
            if isinstance(operand, str):
                raise EvlError("can't do arithmetic on a bin/oct/hex result; convert it to dec first")
            return self.elementwise(UNARY_OPS[type(node.op)], [operand], "arithmetic")
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                return self.variables[node.id]
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise EvlError(f"unknown variable '{node.id}'")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.call(node)
        raise EvlError(f"unsupported expression: {ast.unparse(node)}")

    def call(self, node):
        name = node.func.id
        if node.keywords:
            raise EvlError("keyword arguments are not supported")
        if name in CONVERSIONS:
            return self.convert(node)
        if name == STYLE_FN:
            index = node.args[0].value if len(node.args) == 1 and isinstance(node.args[0], ast.Constant) else None
            if not isinstance(index, int) or not 0 <= index < len(self.styles):
                raise EvlError(f"unknown function '{name}'")
            return self.make_style(index)

        args = [self.eval(arg) for arg in node.args]
        if any(isinstance(arg, str) for arg in args):
            raise EvlError(f"{name}: expects numbers, convert bin/oct/hex to dec first")
        if name == "range":
            return make_range(args)
        if name == "plot":
            return self.plot(args)
        if name in REDUCERS and len(args) == 1 and isinstance(args[0], Vector):
            if not args[0].values:
                raise EvlError(f"{name}: the list is empty")
            return REDUCERS[name](args[0].values)
        if any(isinstance(arg, PlotStyle) for arg in args):
            raise EvlError(f"{name}: a plotstyle can only be passed to plot()")

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
            domain = next((v.domain for v in vectors if v.domain is not None), None)
            values = [
                func(*[a.values[i] if isinstance(a, Vector) else a for a in args])
                for i in range(length)
            ]
            return Vector(values, domain)
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
        if isinstance(value, (Vector, PlotStyle)):
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
        style = args[-1] if args and isinstance(args[-1], PlotStyle) else None
        series = args[:-1] if style else args
        if not series:
            raise EvlError("plot: nothing to plot, e.g. plot(f) or plot(f, style)")
        for item in series:
            if isinstance(item, PlotStyle):
                raise EvlError("plot: the plotstyle must be the last argument")
            if not isinstance(item, Vector):
                raise EvlError("plot: expects a range or list, e.g. plot(cos(x))")

        plt = load_pyplot()
        options = style.options if style else {}
        fig, ax = plt.subplots()
        if style:
            fig.canvas.manager.set_window_title(f"evl - {style.name}")

        def points(size):
            number, unit = size
            return number * 72 / fig.dpi if unit == "px" else number

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

        for vector in series:
            xs = vector.domain if vector.domain is not None else list(range(len(vector.values)))
            ax.plot(xs, vector.values, **kwargs)

        if "xrange" in options:
            ax.set_xlim(*options["xrange"])
        if "yrange" in options:
            ax.set_ylim(*options["yrange"])
        for key, setter in (("title", ax.set_title), ("xlabel", ax.set_xlabel),
                            ("ylabel", ax.set_ylabel)):
            if key in options:
                setter(options[key])
        if options.get("grid"):
            ax.grid(True)

        self.figures += 1
        if interactive_session():
            plt.show(block=False)
            plt.pause(0.05)
        return None


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def pick(value, choices):
    key = value.lower()
    if key not in choices:
        raise EvlError(f"'{value}' is not one of: {', '.join(choices)}")
    return choices[key]


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
