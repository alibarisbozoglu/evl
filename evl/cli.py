"""Command line: one-line, file and multiline modes."""

import sys

from .evaluator import Evaluator
from .plotting import remove_input_hook, set_interactive, show_plots
from .syntax import STYLE_HEADER
from .values import EvlError, format_value


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
    if sys.stdin.isatty():
        set_interactive()
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


HELP = """\
evl - quick calculations from the command line

usage:
  evl EXPRESSION      evaluate and print the answer, e.g. evl 5 + 5
  evl -f FILE         run every statement in FILE
  evl                 multiline mode: lines ending in ';' are collected, a line
                      without ';' prints the answer, an empty line quits
  evl -h, --help      show this help

  Quote expressions that contain ; * ( ) or ^, e.g. evl 'x = 4; 5*x + 4'

language:
  + - * / // % ^ (or **)      arithmetic, 2^10
  x = 4; 5*x + 4              variables, statements separated by ; or newlines
  pi e tau inf                constants
  sqrt sin log exp abs ...    math functions (log(x, base) for other bases)
  hex2dec(ff) dec2bin(10)     base conversions between bin, oct, dec and hex
  [0:0.1:1] range(0, 0.1, 1)  ranges (start:step:end, end included); [1, 2, 3] lists
  sum mean min max len        reduce a list to one number
  f < 3   -1 < f < 1          keep the list values that pass the comparison
  f(x) = x^2; f(3)            define and call your own functions
  integral(x^2, x, 0, 1)      numeric calculus; also derivative(expr, x, point),
  limit(sin(x)/x, x, 0)       limit(..., "+") / "-", derivative(f) / integral(f) of a list
  plot(f) plot(f, style)      plot a list (needs matplotlib)
  show plot(f) + plot(g)      + overlays, a space stacks plots, ':' starts a column
  plotstyle NAME:             indented 'key: value' lines: linestyle, linewidth,
                              marker, markersize, linecolor, markercolor,
                              xrange, yrange, title, xlabel, ylabel, grid
  # comment

See README.md in the evl project folder for details.
"""


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(HELP, end="")
        return 0
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


def run():
    """Entry point for the evl command."""
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
