"""Values a calculation can produce, and how they're printed."""

import ast
import math


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


MAX_RANGE = 10_000_000


_MISSING = object()


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
