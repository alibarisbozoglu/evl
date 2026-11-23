"""Plot styles, plot() and show, and keeping matplotlib windows responsive."""

import ast
import math
import re
import sys

from .syntax import parse_style_value, preprocess_expression
from .values import EvlError, Plot, PlotStyle, Vector

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


def pick(value, choices):
    key = value.lower()
    if key not in choices:
        raise EvlError(f"'{value}' is not one of: {', '.join(choices)}")
    return choices[key]



class PlottingMixin:
    """Evaluator methods for plotstyle, plot() and show."""

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


_PYPLOT = None
_INTERACTIVE = False


def interactive_session():
    return _INTERACTIVE


def set_interactive():
    """Called by the multiline session when typing in a terminal."""
    global _INTERACTIVE
    _INTERACTIVE = True


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
