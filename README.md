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

Answers with more than 50 values are shortened to the first and last 10.

## Plotting

`plot` opens a window with a graph. Here's a complete example (`test.evl`):

```
x = range(-1, 0.1, 1)
f = cos(x)

plotstyle ps:
    linestyle: solid
    linewidth: 2 px
    marker: dot
    linecolor: blue
    markercolor: "#f92200"
    xrange: [-1, 1]
    yrange: [-2, 2]

# This will plot ps
plot(f, ps)
```

```sh
evl -f test.evl
```

### plot

`plot(f)` draws `f` against the range it was calculated from. Above, `f = cos(x)`, so the graph shows `cos(x)` over `x` from -1 to 1. A list with no range behind it, like `[3, 1, 4]`, is drawn against its position (0, 1, 2, ...).

- `plot(f, g)` draws several lines in one window.
- `plot(f, ps)` uses the plotstyle `ps`. The style always goes last.
- Each `plot` call opens its own window. EVL waits until you close all of them before it exits.
- In multiline mode, the window opens straight away and you can keep typing.

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
