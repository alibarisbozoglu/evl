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


def run():
    """Entry point for the evl command."""
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
