#!/usr/bin/env python3
"""Turn unified diff text into a dossier diff figure (an HTML fragment).

Reads the output of `git diff` or `git show` and prints a
`<pre class="code diff">` block for the dossier's locked stylesheet: one row
per line with old and new line numbers, a sign column and the text, GitHub
light diff colours, and the changed words of each paired removed/added line
highlighted. Optional notes put navy numbered markers on chosen lines and
list the notes under the diff (`ol.markers`).

    git show <rev> -- <file> | python3 diff_html.py - [--lines FIRST-LAST]
        [--note old:LINE=TEXT] [--note new:LINE=TEXT] [--path FILE] [--out FILE]

Exit codes: 0 fragment written, 1 the input cannot be read or the diff or a
note does not fit (reason on stderr), 2 usage error. Standard library only.
"""
from __future__ import annotations

import argparse
import difflib
import html
import re
import sys
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
SIGNS = {"add": "+", "del": "-", "ctx": " ", "hunk": "", "nonl": ""}
# Row kind -> classes after "l". A "no newline" note is styled as context.
CLASSES = {"add": "add", "del": "del", "ctx": "ctx", "hunk": "hunk", "nonl": "ctx nonl"}
# Paired lines less alike than this are shown whole, as GitHub does.
WORD_PAIR_MIN_RATIO = 0.5


class DiffError(ValueError):
    """The diff text or an option cannot be turned into a figure."""


def esc(s):
    return html.escape(s, quote=True)


def _strip_prefix(path):
    path = path.split("\t")[0].strip()
    return path[2:] if path[:2] in ("a/", "b/") else path


def parse(text):
    """The files of a unified diff, as a list of (path, rows).

    Each row is a dict: kind ("hunk", "ctx", "del", "add", "nonl"), old and new
    line numbers (None where the side has no line) and the raw text. A hunk
    row's text is its header line. Hunk lengths from the headers decide where a
    hunk ends, so a removed line that starts with "--" is never read as a file
    header. Bare hunks with no file header give one file with path None.
    """
    files = []
    rows = None
    old = new = left_old = left_new = 0
    # Only "\n" ends a diff line: str.splitlines() also splits on form feeds
    # and other separators that can sit inside a source line.
    for line in text.removesuffix("\n").split("\n"):
        line = line.removesuffix("\r")
        if left_old > 0 or left_new > 0:
            if line.startswith("\\"):
                # "\ No newline at end of file" describes the line above it
                rows.append({"kind": "nonl", "old": None, "new": None, "text": line[1:].strip()})
            elif line.startswith("+"):
                rows.append({"kind": "add", "old": None, "new": new, "text": line[1:]})
                new, left_new = new + 1, left_new - 1
            elif line.startswith("-"):
                rows.append({"kind": "del", "old": old, "new": None, "text": line[1:]})
                old, left_old = old + 1, left_old - 1
            else:  # context; some tools drop the space on an empty line
                rows.append({"kind": "ctx", "old": old, "new": new, "text": line[1:]})
                old, new = old + 1, new + 1
                left_old, left_new = left_old - 1, left_new - 1
            continue
        if line.startswith("\\") and rows:
            rows.append({"kind": "nonl", "old": None, "new": None, "text": line[1:].strip()})
            continue
        if line.startswith("diff --git "):
            files.append([None, []])
            rows = files[-1][1]
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            if not files or files[-1][1]:  # plain `diff -u` output has no "diff --git" line
                files.append([None, []])
            rows = files[-1][1]
            name = _strip_prefix(line[4:])
            if name != "/dev/null" and (line.startswith("+++ ") or files[-1][0] is None):
                files[-1][0] = name
            continue
        m = HUNK_RE.match(line)
        if m:
            if rows is None:
                files.append([None, []])
                rows = files[-1][1]
            old, new = int(m.group(1)), int(m.group(3))
            left_old = 1 if m.group(2) is None else int(m.group(2))
            left_new = 1 if m.group(4) is None else int(m.group(4))
            rows.append({"kind": "hunk", "old": None, "new": None, "text": line,
                         "start": (old, new), "heading": m.group(5)})
        # anything else is a commit message or a header line such as "index ..."
    return [(path, rows) for path, rows in files if rows]


def _pick(files, path):
    if not files:
        raise DiffError("no hunk found: expected unified diff text, as from `git diff` or `git show`")
    names = [p or "(unnamed)" for p, _ in files]
    if path is None:
        if len(files) > 1:
            raise DiffError("the diff covers several files; pass a path: " + ", ".join(names))
        return files[0][1]
    for p, rows in files:
        if p == path:
            return rows
    raise DiffError(f"{path} is not in the diff; it covers: " + ", ".join(names))


def words(a, b):
    """HTML for a removed line `a` and its added line `b`, changed words wrapped in `span.w`.

    Returns None for both when the lines share too little to pair.
    """
    ta, tb = re.split(r"(\s+)", a), re.split(r"(\s+)", b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    if sm.ratio() < WORD_PAIR_MIN_RATIO:
        return None, None
    sa, sb = [], []  # (changed, text) segments per side
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        sa.append((op != "equal", "".join(ta[i1:i2])))
        sb.append((op != "equal", "".join(tb[j1:j2])))
    return _segments_html(sa), _segments_html(sb)


def _segments_html(segs):
    """Join segments, merging changed runs split only by whitespace, as GitHub does."""
    segs = [s for s in segs if s[1]]
    for i in range(1, len(segs) - 1):
        if not segs[i][0] and not segs[i][1].strip() and segs[i - 1][0] and segs[i + 1][0]:
            segs[i] = (True, segs[i][1])
    out, run = [], []
    for changed, text in segs + [(False, "")]:
        if changed:
            run.append(text)
            continue
        if run:
            out.append(f'<span class="w">{esc("".join(run))}</span>')
            run = []
        out.append(esc(text))
    return "".join(out)


def _pair_words(rows):
    """Set row["html"] on each removed line paired with an added line.

    A run of removals followed by a run of additions pairs first with first,
    second with second, and so on. "No newline" notes do not break a run.
    """
    rows = [r for r in rows if r["kind"] != "nonl"]
    i = 0
    while i < len(rows):
        if rows[i]["kind"] != "del":
            i += 1
            continue
        j = i
        while j < len(rows) and rows[j]["kind"] == "del":
            j += 1
        k = j
        while k < len(rows) and rows[k]["kind"] == "add":
            k += 1
        for d, a in zip(rows[i:j], rows[j:k]):
            d_html, a_html = words(d["text"], a["text"])
            if d_html is not None:
                d["html"], a["html"] = d_html, a_html
        i = k


def _row_html(row):
    num = lambda v: "" if v is None else str(v)  # noqa: E731
    text = row.get("html", esc(row["text"])) or " "
    cls, attr = CLASSES[row["kind"]], ""
    if "mark" in row:
        cls, attr = cls + " mark", f' data-m="{row["mark"]}"'
    return (f'<span class="l {cls}"{attr}><span class="o">{num(row["old"])}</span>'
            f'<span class="n">{num(row["new"])}</span><span class="sg">{SIGNS[row["kind"]]}</span>'
            f'<span class="t">{text}</span></span>')


def _hunk_header(kept, heading):
    """A `@@ -a,b +c,d @@` header for the kept rows of one hunk, git's spelling."""
    def side(sign, start, count):
        if count == 0:
            return f"{sign}{start - 1},0"
        return f"{sign}{start}" if count == 1 else f"{sign}{start},{count}"
    o0, n0 = kept[0]["pos"]
    olds = sum(r["kind"] in ("ctx", "del") for r in kept)
    news = sum(r["kind"] in ("ctx", "add") for r in kept)
    tail = f" {heading}" if heading else ""
    return f"@@ {side('-', o0, olds)} {side('+', n0, news)} @@{tail}"


def _slice(rows, first, last):
    """Only the lines whose new-file number is in first..last, with fresh hunk headers.

    A removed line is kept when the new-file line it sits before is in range.
    """
    out, hunk, kept = [], None, []

    def flush():
        if any(r["kind"] != "nonl" for r in kept):
            header = _hunk_header([r for r in kept if r["kind"] != "nonl"], hunk["heading"])
            out.append(dict(hunk, text=header))
            out.extend(kept)

    o = n = 0
    last_kept = False  # whether the line a "no newline" note describes was kept
    for r in rows:
        if r["kind"] == "hunk":
            if hunk is not None:
                flush()
            hunk, kept = r, []
            o, n = r["start"]
            continue
        if r["kind"] == "nonl":
            if last_kept:
                kept.append(r)
            continue
        last_kept = first <= n <= last
        if last_kept:
            kept.append(dict(r, pos=(o, n)))
        o += r["kind"] in ("ctx", "del")
        n += r["kind"] in ("ctx", "add")
    if hunk is not None:
        flush()
    if not out:
        raise DiffError(f"no line of the diff falls in new-file lines {first} to {last}")
    return out


def render(text, path=None, line_range=None, notes=None):
    """The `<pre class="code diff">` fragment for unified diff text.

    `path` picks one file when the diff covers several. `line_range`, a
    (first, last) pair of new-file line numbers, trims the figure to those
    lines. `notes` is a list of (side, line, text), side "old" or "new":
    each puts a numbered marker on that line, and the fragment gains an
    `ol.markers` list after the `pre`. Raises DiffError.
    """
    rows = _pick(parse(text), path)
    if line_range is not None:
        rows = _slice(rows, *line_range)
    _pair_words(rows)
    items = _attach_notes(rows, notes or [])
    pre = '<pre class="code diff"><code>' + "".join(_row_html(r) for r in rows) + "</code></pre>"
    if not items:
        return pre
    return pre + '<ol class="markers">' + "".join(
        f'<li><span class="k">{k}</span><span class="ln">{label}</span> {_note_html(text)}</li>'
        for k, label, text in items) + "</ol>"


def _note_html(text):
    """Escape a note; `backticks` become <code>."""
    parts = text.split("`")
    if len(parts) % 2 == 0:  # an unmatched backtick stays literal
        return esc(text)
    return "".join(f"<code>{esc(p)}</code>" if i % 2 else esc(p) for i, p in enumerate(parts))


def _attach_notes(rows, notes):
    """Mark the noted rows, numbering 1.. from the top; return (number, label, text) per note."""
    by_row = {}
    for side, line, text in notes:
        if side not in ("old", "new"):
            raise DiffError(f"note side must be old or new, not {side!r}")
        hits = [i for i, r in enumerate(rows) if r["kind"] in ("ctx", "add", "del") and r[side] == line]
        if not hits:
            raise DiffError(f"no {side}-file line {line} in the figure to annotate")
        if hits[0] in by_row:
            raise DiffError(f"two notes on the {side}-file line {line}")
        by_row[hits[0]] = text
    items = []
    for k, i in enumerate(sorted(by_row), 1):
        r = rows[i]
        r["mark"] = k
        label = {"del": f"-{r['old']}", "add": f"+{r['new']}", "ctx": str(r["new"])}[r["kind"]]
        items.append((k, label, by_row[i]))
    return items


def _note_arg(value):
    side, sep, rest = value.partition(":")
    line, sep2, text = rest.partition("=")
    if not (sep and sep2) or side not in ("old", "new") or not line.isdigit() or not text.strip():
        raise argparse.ArgumentTypeError(f"expected old:LINE=TEXT or new:LINE=TEXT, got {value!r}")
    return side, int(line), text.strip()


def _lines_arg(value):
    m = re.fullmatch(r"(\d+)-(\d+)", value)
    if not m or int(m.group(1)) > int(m.group(2)):
        raise argparse.ArgumentTypeError(f"expected FIRST-LAST new-file line numbers, got {value!r}")
    return int(m.group(1)), int(m.group(2))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn unified diff text (git diff / git show) into a dossier diff figure.",
        epilog="Example: git show 088a29f -- SKILL.md | diff_html.py - --lines 35-49 "
               "--note 'old:36=Before.' --note 'new:39=After: run `check_render.py`.'")
    ap.add_argument("diff", help="unified diff file, or - for stdin")
    ap.add_argument("--path", help="the file to show when the diff covers several (as in +++ b/PATH)")
    ap.add_argument("--lines", type=_lines_arg, metavar="FIRST-LAST",
                    help="keep only new-file lines FIRST..LAST and the removals between them")
    ap.add_argument("--note", type=_note_arg, action="append", default=[], metavar="SIDE:LINE=TEXT",
                    help="numbered marker on old- or new-file line LINE, with TEXT in the notes "
                         "list (`backticks` become code); repeatable")
    ap.add_argument("--out", help="write the fragment here instead of stdout")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
        fragment = render(text, path=args.path, line_range=args.lines, notes=args.note)
    except (OSError, DiffError) as e:
        print(f"diff_html: {e}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(fragment + "\n", encoding="utf-8")
    else:
        print(fragment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
