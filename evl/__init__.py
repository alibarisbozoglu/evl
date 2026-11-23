"""EVL (evaluate) - quick calculations from the command line.

Usage:
    evl 5 + 5                 -> ans: 10
    evl 'x = 4; 5*x + 4'      -> ans: 24
    evl                       -> multiline session; a line without a trailing ';'
                                 prints an answer, an empty line (or Ctrl-D) quits
    evl -f FILENAME           -> evaluate every statement in a file
"""

# Package layout:
#   syntax.py     source rewriting before parsing (plotstyle blocks, f(x) = ..., [a:b], ^, show)
#   evaluator.py  the safe evaluator (Evaluator)
#   names.py      built-in operators, constants, functions, base conversions
#   values.py     Vector, Plot, PlotStyle, Function, ranges, formatting
#   calculus.py   integral / derivative / limit
#   plotting.py   plotstyle, plot(), show, matplotlib windows
#   cli.py        command line modes

from .evaluator import Evaluator
from .values import EvlError

__all__ = ["Evaluator", "EvlError"]
