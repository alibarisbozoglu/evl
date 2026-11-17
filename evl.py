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

# Base conversions: bin2dec, hex2bin, dec2oct, ... (every pair of bases).
BASES = {"bin": 2, "oct": 8, "dec": 10, "hex": 16}
BASE_FORMATS = {2: "b", 8: "o", 16: "X"}
CONVERSIONS = {
    f"{src}2{dst}": (BASES[src], BASES[dst])
    for src in BASES
    for dst in BASES
    if src != dst
}

# hex2dec(ff), bin2hex(1011), oct2bin(0o17): the argument is digits, not an
# expression ("ff" would be a variable and "1f" a syntax error), so quote it
# before parsing. dec2* functions take a normal expression and are left alone.
DIGITS_ARG = re.compile(
    r"\b((?:bin|oct|hex)2(?:bin|oct|dec|hex))\(\s*([0-9A-Za-z_]+)\s*\)"
)


class EvlError(Exception):
    pass


class Evaluator:
    def __init__(self):
        self.variables = {}

    def run(self, source):
        """Evaluate ';' / newline separated statements, return the last value."""
        source = DIGITS_ARG.sub(r'\1("\2")', source)
        source = source.replace("^", "**")  # allow 2^3 as power
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            where = f" on line {exc.lineno}" if "\n" in source.strip() and exc.lineno else ""
            raise EvlError(f"syntax error{where}: {exc.msg}") from None

        result = None
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                value = self.eval(stmt.value)
                for target in stmt.targets:
                    if not isinstance(target, ast.Name):
                        raise EvlError("can only assign to simple names")
                    if target.id in FUNCTIONS or target.id in CONVERSIONS or target.id in CONSTANTS:
                        raise EvlError(f"cannot assign to built-in '{target.id}'")
                    self.variables[target.id] = value
                result = value
            elif isinstance(stmt, ast.Expr):
                result = self.eval(stmt.value)
            else:
                raise EvlError("only expressions and assignments are allowed")
        return result

    def eval(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str)) and not isinstance(node.value, bool):
                return node.value
            raise EvlError(f"unsupported value: {node.value!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
            left, right = self.eval(node.left), self.eval(node.right)
            if isinstance(left, str) or isinstance(right, str):
                raise EvlError(
                    "can't do arithmetic on a bin/oct/hex result; "
                    "convert it to dec first, e.g. hex2dec(...)"
                )
            try:
                return BIN_OPS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise EvlError("division by zero") from None
            except OverflowError:
                raise EvlError("result too large") from None
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            operand = self.eval(node.operand)
            if isinstance(operand, str):
                raise EvlError("can't do arithmetic on a bin/oct/hex result; convert it to dec first")
            return UNARY_OPS[type(node.op)](operand)
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                return self.variables[node.id]
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise EvlError(f"unknown variable '{node.id}'")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in CONVERSIONS:
                return self.convert(node)
            func = FUNCTIONS.get(node.func.id)
            if func is None:
                raise EvlError(f"unknown function '{node.func.id}'")
            if node.keywords:
                raise EvlError("keyword arguments are not supported")
            args = [self.eval(arg) for arg in node.args]
            if any(isinstance(arg, str) for arg in args):
                raise EvlError(f"{node.func.id}: expects numbers, convert bin/oct/hex to dec first")
            try:
                return func(*args)
            except (ValueError, TypeError, OverflowError) as exc:
                raise EvlError(f"{node.func.id}: {exc}") from None
        raise EvlError(f"unsupported expression: {ast.unparse(node)}")

    def convert(self, node):
        name = node.func.id
        src, dst = CONVERSIONS[name]
        if len(node.args) != 1 or node.keywords:
            raise EvlError(f"{name} takes exactly one argument")
        value = self.eval(node.args[0])

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


def format_number(value):
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return str(value)


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
        print(f"ans: {format_number(result)}")
    return True


def multiline_session():
    """Interactive mode: lines ending in ';' are collected, a line without one
    evaluates everything collected so far and prints the answer. Variables
    persist between answers. An empty line (or Ctrl-D) ends the session.
    """
    if sys.stdin.isatty():
        try:
            import readline  # noqa: F401  (arrow keys and history for input())
        except ImportError:
            pass

    evaluator = Evaluator()
    pending = []
    ok = True
    while True:
        try:
            line = input()
        except EOFError:
            break
        stripped = line.strip()
        if not stripped:
            break
        pending.append(line)
        if not stripped.endswith(";"):
            ok = evaluate_and_print(evaluator, "\n".join(pending)) and ok
            pending = []

    # Don't silently drop statements still waiting for an answer line.
    if pending:
        ok = evaluate_and_print(evaluator, "\n".join(pending)) and ok
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

    return 0 if evaluate_and_print(Evaluator(), source) else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
