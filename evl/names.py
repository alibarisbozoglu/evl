"""Built-in names: operators, constants, functions and base conversions."""

import ast
import math
import operator

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
