"""Numeric integrals, derivatives and limits."""

import ast
import math

from .names import RESERVED
from .values import _MISSING, EvlError, Vector, format_number, is_number


class CalculusMixin:
    """Evaluator methods for integral / derivative / limit with an expression."""

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
