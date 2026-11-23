"""Source rewriting done before Python's parser sees the text:
plotstyle blocks, f(x) = ... definitions, [a:b] ranges, ^ and show statements."""

import io
import re
import tokenize

from .names import DEFINE_FN, SHOW_FN, STYLE_FN
from .values import EvlError

# hex2dec(ff), bin2hex(1011), oct2bin(0o17): the argument is digits, not an
# expression ("ff" would be a variable and "1f" a syntax error), so quote it
# before parsing. dec2* functions take a normal expression and are left alone.
DIGITS_ARG = re.compile(
    r"\b((?:bin|oct|hex)2(?:bin|oct|dec|hex))\(\s*([0-9A-Za-z_]+)\s*\)"
)

# [start:step:end] and [start:end] range literals.
RANGE3 = re.compile(r"\[([^\[\]:]+):([^\[\]:]+):([^\[\]:]+)\]")
RANGE2 = re.compile(r"\[([^\[\]:]+):([^\[\]:]+)\]")

STYLE_HEADER = re.compile(r"^plotstyle\s+([A-Za-z_]\w*)\s*:\s*(#.*)?$")
STYLE_LINE = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(.*)$")


FUNCTION_DEF = re.compile(
    r"(^|;)([ \t]*)([A-Za-z_]\w*)[ \t]*\(([\w \t,]*)\)[ \t]*=(?!=)", re.MULTILINE
)


def rewrite_function_definitions(source):
    """`f(x, y) = body` -> `f = __function__("f", [x, y], body)`. The body ends
    at the next ';', newline or comment outside brackets and quotes."""
    out, pos = [], 0
    for match in FUNCTION_DEF.finditer(source):
        if match.start() < pos:
            continue
        lead, indent, name, params = match.groups()
        params = [p.strip() for p in params.split(",")] if params.strip() else []
        if not all(re.fullmatch(r"[A-Za-z_]\w*", p) for p in params):
            continue  # not a definition; let the parser report it
        end, depth, quote = match.end(), 0, None
        while end < len(source):
            ch = source[end]
            if quote:
                quote = None if ch == quote else quote
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif depth == 0 and ch in ";\n#":
                break
            end += 1
        body = source[match.end():end]
        out.append(source[pos:match.start()])
        out.append(f'{lead}{indent}{name} = {DEFINE_FN}("{name}", [{", ".join(params)}], {body.strip() or "None"})')
        pos = end
    out.append(source[pos:])
    return "".join(out)


def preprocess_expression(source):
    source = rewrite_function_definitions(source)
    source = RANGE3.sub(r"range(\1,\2,\3)", source)
    source = RANGE2.sub(r"range(\1,1,\2)", source)
    source = DIGITS_ARG.sub(r'\1("\2")', source)
    return source.replace("^", "**")  # allow 2^3 as power


def rewrite_show_statements(source, multiline):
    """Turn `show a b : c` into `__show__([[a, b], [c]])`, line by line.

    In a show layout, `:` separates columns (left to right) and plots written
    one after another in a column are stacked top to bottom. `+` (overlaying
    plots on the same axes) is ordinary arithmetic on plot values.
    """
    lines = source.split("\n")
    for number, line in enumerate(lines, 1):
        if "show" in line:
            try:
                lines[number - 1] = rewrite_show_line(line)
            except EvlError as exc:
                raise EvlError(f"line {number}: {exc}" if multiline else str(exc)) from None
    return "\n".join(lines)


def rewrite_show_line(line):
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(line).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return line  # let the parser report the problem
    skip = {tokenize.COMMENT, tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER,
            tokenize.INDENT, tokenize.DEDENT}
    tokens = [t for t in tokens if t.type not in skip]

    # Split into statements at ';' outside brackets.
    statements, current, depth = [], [], 0
    for tok in tokens:
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth -= 1
        if depth == 0 and tok.type == tokenize.OP and tok.string == ";":
            statements.append(current)
            current = []
        else:
            current.append(tok)
    statements.append(current)

    replacements = []
    for stmt in statements:
        if len(stmt) < 2 or stmt[0].type != tokenize.NAME or stmt[0].string != "show":
            continue
        if stmt[1].type == tokenize.OP and stmt[1].string not in "([-+:":
            continue  # e.g. `show = 1`: not a show statement (and an error later)
        columns = split_show_layout(stmt[1:], line)
        call = SHOW_FN + "([" + ", ".join("[" + ", ".join(col) + "]" for col in columns) + "])"
        replacements.append((stmt[0].start[1], stmt[-1].end[1], call))

    for start, end, call in reversed(replacements):
        line = line[:start] + call + line[end:]
    return line


def split_show_layout(tokens, line):
    def ends_operand(tok):
        return tok.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING) or tok.string in (")", "]")

    def starts_operand(tok, prev):
        if tok.string in ("(", "["):
            return prev.type != tokenize.NAME and prev.string not in (")", "]")  # f(x) is a call
        return tok.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING)

    columns, column, item, depth, prev = [], [], [], 0, None
    for tok in tokens:
        if depth == 0 and tok.type == tokenize.OP and tok.string == ":":
            if item:
                column.append(item)
            if not column:
                raise EvlError("show: empty column before ':'")
            columns.append(column)
            column, item, prev = [], [], None
            continue
        if depth == 0 and prev is not None and ends_operand(prev) and starts_operand(tok, prev):
            column.append(item)  # `a b`: b goes below a
            item = []
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth -= 1
        item.append(tok)
        prev = tok
    if item:
        column.append(item)
    if not column:
        raise EvlError("show: nothing to show after ':'" if columns else "show: nothing to show")
    columns.append(column)
    return [[line[it[0].start[1]:it[-1].end[1]] for it in col] for col in columns]


def parse_style_value(raw):
    """'"#f92200"  # comment' -> '#f92200'; 'blue # comment' -> 'blue'."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end == -1:
            raise ValueError("missing closing quote")
        rest = raw[end + 1:].strip()
        if rest and not rest.startswith("#"):
            raise ValueError("unexpected text after quoted value")
        return raw[1:end]
    return raw.split("#", 1)[0].strip()


def extract_plotstyles(source):
    """Pull `plotstyle NAME:` blocks out of the source.

    Each header line is replaced with `NAME = __plotstyle__(i)` and its body
    lines with blank lines, so line numbers in error messages stay correct.
    Returns the new source and a list of (name, [(line_no, key, raw_value)]).
    """
    lines = source.split("\n")
    styles = []
    i = 0
    while i < len(lines):
        match = STYLE_HEADER.match(lines[i])
        if not match:
            i += 1
            continue
        name = match.group(1)
        header_no = i + 1
        lines[i] = f"{name} = {STYLE_FN}({len(styles)})"
        entries = []
        i += 1
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            text = lines[i].strip()
            lines[i] = ""
            if text and not text.startswith("#"):
                entry = STYLE_LINE.match(text)
                if not entry:
                    raise EvlError(f"line {i + 1}: expected 'key: value' in plotstyle {name}")
                entries.append((i + 1, entry.group(1), entry.group(2)))
            i += 1
        styles.append((name, header_no, entries))
    return "\n".join(lines), styles
