# EVL

EVL (short for *evaluate*) is a small command-line calculator for quick calculations. It's written in Python and has no dependencies beyond the standard library.

```
$ evl 5 + 5
ans: 10
```

## Installation

EVL needs Python 3.9 or newer. Plotting also needs [matplotlib](https://matplotlib.org/) (`pip install --user matplotlib`); everything else works without it. Make the script executable and link it into a folder on your `PATH`:

```sh
chmod +x evl.py
ln -s "$PWD/evl.py" ~/.local/bin/evl
```

Check that `~/.local/bin` is on your `PATH` (`echo $PATH`). Because `evl` is a link, edits to `evl.py` take effect immediately.

## Usage

### One-line mode

Pass the expression as arguments:

```
$ evl 5 + 5
ans: 10

$ evl '2^10'
ans: 1024
```

Separate several statements with `;`. The answer is the value of the last statement:

```
$ evl 'x = 4; 5*x + 4'
ans: 24
```

> **Quote expressions that contain `;`, `*`, `(`, `)` or `^`.** Your shell reads these characters before EVL sees them. Without quotes, `evl x = 4; 5*x + 4` runs `evl x = 4` and then tries to run `5*x + 4` as a separate command. A `*` can also be replaced by matching file names. Single quotes are the safest choice.

### Multiline mode

Run `evl` with no arguments to start a session, then type one statement per line:

- A line ending in `;` is saved without printing anything.
- A line **without** a trailing `;` runs everything saved so far and prints the answer.
- Variables are kept for the rest of the session, so you can keep calculating.
- Press Enter on an **empty line** (or Ctrl-D) to quit.
- A [`plotstyle`](#plotting) block is the exception: an empty line just ends the block, and the session continues.

```
$ evl
y = 10;
x = 5 + y;
x
ans: 15
y + 2
ans: 12

$
```

If a line has an error, EVL prints it and the session continues. Any statements saved since the last answer are discarded, and variables keep the values they had before. If you quit while statements are still waiting for an answer line, EVL runs them and prints their result first.

In a terminal, the arrow keys let you edit the line and go back through earlier lines. You can also pipe input in:

```sh
printf 'r = 3;\npi * r^2\n' | evl
```

When input is piped, the exit status is `1` if any line had an error.

### File mode

Run every statement in a file with `-f` (or `--file`):

```
$ cat circle.evl
# area of a circle
r = 3
area = pi * r^2
round(area, 2)

$ evl -f circle.evl
ans: 28.27
```

In a file, put one statement per line; a trailing `;` is optional. Blank lines and lines starting with `#` are ignored. EVL runs the whole file and prints the value of the last statement. Errors report their line number, e.g. `error: syntax error on line 2: invalid syntax` or `error: line 5: division by zero`.

## Language

### Numbers and operators

| Operator | Meaning           | Example    | Result |
|----------|-------------------|------------|--------|
| `+`      | addition          | `2 + 3`    | `5`    |
| `-`      | subtraction       | `2 - 3`    | `-1`   |
| `*`      | multiplication    | `2 * 3`    | `6`    |
| `/`      | division          | `7 / 2`    | `3.5`  |
| `//`     | floor division    | `7 // 2`   | `3`    |
| `%`      | remainder         | `7 % 2`    | `1`    |
| `^`, `**`| power             | `2 ^ 3`    | `8`    |
| `-x`     | negation          | `-(2 + 3)` | `-5`   |

Use parentheses to group. Integers have unlimited precision, and decimals are standard floating-point numbers. A whole-number result prints without a decimal point, so `10 / 2` prints `5`, not `5.0`.

### Variables

Assign with `=`. A variable lasts until the end of the current `evl` run:

```
$ evl 'price = 40; tax = 0.2; price * (1 + tax)'
ans: 48
```

Names follow Python rules: letters, digits and `_`, not starting with a digit. If the last statement is an assignment, EVL prints the assigned value.

### Constants

`pi`, `e`, `tau`, `inf`

### Functions

| Kind          | Functions |
|---------------|-----------|
| Roots, powers | `sqrt`, `cbrt`, `exp`, `hypot` |
| Logarithms    | `log` (natural; `log(x, base)` for another base), `log2`, `log10` |
| Trigonometry  | `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2` (radians) |
| Hyperbolic    | `sinh`, `cosh`, `tanh` |
| Angles        | `degrees`, `radians` |
| Rounding      | `floor`, `ceil`, `round` (`round(x, digits)`), `abs` |
| Integers      | `factorial`, `gcd`, `lcm` |
| Other         | `min`, `max` |

```
$ evl 'sin(radians(30))'
ans: 0.49999999999999994

$ evl 'round(sqrt(2), 4)'
ans: 1.4142
```

### Number bases

You can type binary, octal and hex numbers straight into any expression with a prefix:

```
$ evl '0xff + 0b1 + 0o10'
ans: 264
```

To convert between bases, use the functions named `<from>2<to>`. All 12 combinations of `bin`, `oct`, `dec` and `hex` exist:

| From \ To | bin       | oct       | dec       | hex       |
|-----------|-----------|-----------|-----------|-----------|
| **bin**   |           | `bin2oct` | `bin2dec` | `bin2hex` |
| **oct**   | `oct2bin` |           | `oct2dec` | `oct2hex` |
| **dec**   | `dec2bin` | `dec2oct` |           | `dec2hex` |
| **hex**   | `hex2bin` | `hex2oct` | `hex2dec` |           |

```
$ evl 'hex2bin(ff)'
ans: 11111111
$ evl 'bin2dec(1011)'
ans: 11
$ evl 'dec2hex(255)'
ans: FF
$ evl 'oct2bin(17)'
ans: 1111
```

**What the argument can be:**

- **`bin2…`, `oct2…` and `hex2…`** take the digits as you would write them: `hex2dec(1f)`, `bin2hex(1011)`. Prefixes (`0x`, `0b`, `0o`), `_` separators (`bin2hex(1111_0000)`) and quotes (`hex2dec("c0ffee")`) are all accepted, and hex digits can be upper or lower case.
- **`dec2…`** takes any normal expression, including variables: `dec2bin(2^8 - 1)`, `dec2hex(x * 3)`. The value must be a whole number (`10.0` is fine, `2.5` is an error).

**What you get back:**

- **`…2dec`** returns a normal number, so you can calculate with it: `hex2dec(ff) + 1` gives `256`.
- **`…2bin`, `…2oct` and `…2hex`** return digits without a prefix; hex is shown in upper case. These results are for reading and can't be used in arithmetic, so `dec2hex(255) + 1` is an error. Convert back first: `hex2dec(dec2hex(255)) + 1`.
- Negative numbers keep their sign: `dec2bin(-5)` gives `-101`.

You can store a converted result and convert it again: `h = dec2hex(171); hex2bin(h)` gives `10101011`. When the argument of a `bin2…`/`oct2…`/`hex2…` function is a single word, EVL first reads it as digits and only falls back to a variable if that fails. So `hex2dec(cafe)` always means the hex number `CAFE`, even if you have a variable called `cafe`.

### Ranges and lists

`range(start, step, end)` makes a list of numbers from `start` to `end`, going up by `step`. The `end` value is included. `[start:step:end]` is a shorter way to write the same thing, and `[start:end]` uses a step of 1:

```
$ evl 'range(-1, 0.1, 1)'
ans: [-1, -0.9, -0.8, -0.7, -0.6, -0.5, -0.4, -0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]

$ evl '[0:5]'
ans: [0, 1, 2, 3, 4, 5]
```

A step can be negative (`[10:-2:0]`). You can also write a list out by hand: `[1, 2, 3]`.

Arithmetic and functions work on every element:

```
$ evl 'x = [0:0.5:2]; x^2 + 1'
ans: [1, 1.25, 2, 3.25, 5]

$ evl 'round(sin([0:0.5:1]), 3)'
ans: [0, 0.479, 0.841]
```

Combining two lists works element by element, and they must have the same length.

These functions turn a list into a single number: `sum`, `len`, `mean`, `min` and `max`. For example, `sum([1:100])` gives `5050`.

### Comparisons

`<`, `<=`, `>` and `>=` compare two values. With plain numbers you get `true` or `false`:

```
$ evl '2 < 3'
ans: true
```

With a range or list, a comparison **keeps the elements that pass** and drops the rest:

```
$ evl
f = [0, 1, 2, 3, 4];
g = f < 3
ans: [0, 1, 2]
```

The list can be on either side: `3 > f` also gives `[0, 1, 2]`.

Chain comparisons to keep values between two limits. Every comparison in the chain must hold:

```
$ evl '2 < [0:10] < 6'
ans: [3, 4, 5]
```

With plain numbers, a chain gives `true` or `false` (`1 < 2 < 3` gives `true`). If more than one side is a list, the first list in the chain is the one filtered: `0 < [1, 2, 3] < [3, 3, 3]` gives `[1, 2]`.

The result is an ordinary list, so `len(f < 3)` counts the values that pass and `sum(f < 3)` adds them up. If nothing passes, you get `[]`.

Answers with more than 50 values are shortened to the first and last 10.

### Calculus

EVL calculates integrals, derivatives and limits numerically. Answers are decimals, accurate to about 10–12 significant digits.

| Function | Meaning | Example | Result |
|----------|---------|---------|--------|
| `integral(expr, x, a, b)` | area under `expr` as `x` goes from `a` to `b` | `integral(x^2, x, 0, 1)` | `0.333333333333` |
| `derivative(expr, x, p)` | slope of `expr` at `x = p` | `derivative(sin(x), x, 0)` | `1` |
| `limit(expr, x, p)` | value `expr` approaches as `x` approaches `p` | `limit(sin(x)/x, x, 0)` | `1` |

The second argument names the variable. It's only used inside the expression and doesn't change a variable with the same name: after `x = 5; integral(x, x, 0, 1)`, `x` is still `5`.

**Integrals**
- Bounds can be infinite: `integral(exp(-x^2), x, -inf, inf)` gives `1.77245385091` (√π).
- If `a > b`, the result is negative, as in maths.
- Integrals that are infinite give an error: `integral(1/x, x, 0, 1)` reports that it doesn't converge.

**Derivatives**
- If the slope is different on each side of the point, there's no derivative, and EVL says so:

  ```
  $ evl 'derivative(abs(x), x, 0)'
  error: derivative: not differentiable at x = 0 (slope -1 from the left, 1 from the right)
  ```

**Limits**
- The point can be `inf` or `-inf`: `limit((1+1/x)^x, x, inf)` gives `2.718281828`.
- Limits can be infinite: `limit(1/x^2, x, 0)` gives `inf`.
- If the left and right limits differ, EVL says so. Add `"+"` (from the right) or `"-"` (from the left) to get one side:

  ```
  $ evl 'limit(1/x, x, 0)'
  error: limit: left and right limits differ (-inf from the left, inf from the right); use limit(expr, x, 0, "+") or "-"
  $ evl 'limit(1/x, x, 0, "+")'
  ans: inf
  ```

- If the expression keeps oscillating, like `sin(1/x)` at 0, EVL reports that it doesn't settle. Some limits approach their value too slowly for a numeric method to confirm, like `sqrt(x)*log(x)` at 0; these also report that they don't settle.

**Many points at once.** If the point or a bound is a range, you get one answer per value, ready to plot:

```
$ evl 'derivative(sin(x), x, [0:0.5:2])'
ans: [1, 0.8775825619, 0.5403023059, 0.07073720167, -0.4161468365]
$ evl 'integral(x^2, x, 0, [0:3])'
ans: [0, 0.333333333333, 2.66666666667, 9]
```

**Lists.** With a single list argument, `derivative` and `integral` work on the list's values directly:

- `derivative(f)` gives the slope at each point of `f`.
- `integral(f)` gives the running area under `f`, starting at 0. The last value is the total area.

```
x = [0:0.1:6]
f = sin(x)
show plot(f) + plot(derivative(f)) + plot(integral(f))
```

These use the points you have (central differences and the trapezoid rule), so finer ranges give more accurate results. Parts of a list removed by a [comparison](#comparisons) aren't bridged: each piece is handled separately.

## Plotting

Plotting has two steps. `plot(...)` describes a plot, and `show` arranges one or more plots in a window. Here's a complete example (`test.evl`):

```
x = range(-1, 0.05, 1)
f = cos(2 * pi * x)
g = -0.5 < f < 0.5
h = -3 < [-5:5] < 2

plotstyle ps:
    linestyle: solid
    linewidth: 2 px
    marker: dot
    linecolor: blue
    markercolor: "#f92200"
    xrange: [-1, 1]
    yrange: [-2, 2]

# This will plot f with ps, add g on top of the same plot and show them
show plot(f, ps) + plot(g)

# This will plot f with ps, and add a g plot BELOW the f plot (seperate plots)
show plot(f, ps) plot(g)

# This will plot f on the left, g on the right
show plot(f) : plot(g)

#This will plot f on top left, h in bottom left, g on the right
show plot(f) plot(h) : plot(g)
```

```sh
evl -f test.evl
```

This opens four windows, one for each `show`.

### plot

`plot(f)` or `plot(f, style)` describes a plot of the list `f`. It takes at most two arguments: the list and, optionally, a [plotstyle](#plotstyle).

`f` is drawn against the range it was calculated from: with `x = [-1:0.05:1]` and `f = cos(2 * pi * x)`, the graph shows `f` over `x` from -1 to 1. A list with no range behind it, like `[3, 1, 4]`, is drawn against its position (0, 1, 2, ...). A [comparison](#comparisons) result keeps each value at its original x position, and the line breaks where values were removed.

To draw several lines in the **same plot**, add plots with `+`:

```
show plot(f, ps) + plot(g)
```

The plot's axis settings (`xrange`, `yrange`, `title`, `xlabel`, `ylabel`, `grid`) come from the first style that sets them. Line and marker options apply to each line separately.

Plots are values, so you can store them: `p = plot(f) + plot(g)`, then `show p`.

### show

`show` opens one window and arranges the plots in it:

| Layout       | Meaning |
|--------------|---------|
| `a + b`      | `a` and `b` in the same plot |
| `a b`        | `a` on top, `b` below it (separate plots) |
| `a : b`      | `a` on the left, `b` on the right |

`+` groups first, then plots written one after another, then `:`. So `show plot(f) plot(h) : plot(g)` gives a left column with `f` above `h`, and `g` on the right at full height:

```
┌─────────┬─────────┐
│    f    │         │
├─────────┤    g    │
│    h    │         │
└─────────┴─────────┘
```

Shortcuts:
- `show f` is short for `show plot(f)`.
- A plot on its own line is shown in its own window, so `plot(f)` alone is the same as `show plot(f)`.

Each `show` opens its own window. With `-f` or a one-line command, EVL waits until you close all the windows before it exits. In multiline mode, the window opens straight away and you can keep typing.

### plotstyle

A `plotstyle NAME:` line starts a style. Its options follow on indented lines, one `option: value` per line, and the block ends at the next line that isn't indented. Every option is optional.

| Option        | Values | Example |
|---------------|--------|---------|
| `linestyle`   | `solid`, `dashed`, `dotted`, `dashdot`, `none` | `linestyle: dashed` |
| `linewidth`   | a size in `px` or `pt` (no unit means px) | `linewidth: 2 px` |
| `marker`      | `none`, `dot`, `circle`, `square`, `triangle`, `diamond`, `star`, `plus`, `cross` | `marker: dot` |
| `markersize`  | a size in `px` or `pt` | `markersize: 8 px` |
| `linecolor`   | a color name or `"#rrggbb"` | `linecolor: blue` |
| `markercolor` | a color name or `"#rrggbb"` | `markercolor: "#f92200"` |
| `xrange`, `yrange` | axis limits `[min, max]`; expressions like `[-pi, pi]` work | `xrange: [-1, 1]` |
| `title`, `xlabel`, `ylabel` | text | `title: cos(x)` |
| `grid`        | `on` or `off` | `grid: on` |

**Put hex colors in quotes.** `#` starts a comment, so `markercolor: #f92200` would leave the value empty. Write `markercolor: "#f92200"` instead.

If you don't set a color, each line gets its own color automatically. A misspelled option, color or value is an error that names the line:

```
error: line 7: plotstyle ps, linecolor: unknown color 'bleu' (use a name like blue or "#rrggbb")
```

## Errors

If something goes wrong, EVL prints a message to stderr and exits with status `1`:

```
$ evl 1/0
error: division by zero

$ evl 'y + 1'
error: unknown variable 'y'

$ evl -f missing.evl
error: cannot read 'missing.evl': No such file or directory
```

## Safety

EVL never runs your input as Python code. It reads the input as a tree of operations and evaluates it itself, and anything other than numbers, the operators above, assignments and the listed functions is rejected. That makes it safe to use on input you didn't write yourself.

## Exit codes

| Code  | Meaning                       |
|-------|-------------------------------|
| `0`   | success (including empty input) |
| `1`   | syntax or evaluation error    |
| `130` | interrupted with Ctrl-C       |
