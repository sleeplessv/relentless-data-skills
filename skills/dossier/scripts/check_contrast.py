#!/usr/bin/env python3
"""Check a dossier page's declared colour pairs against WCAG AA.

Reads the colour tokens from the page's :root block (the locked block when
present) and the pairs from its /* dossier:pairs ... */ comment, then checks
each pair: text 4.5:1, large text and graphics 3:1, decor reported only.
A translucent colour is composited over the background it sits on first.

    python3 check_contrast.py [page.html]     # default: ../assets/scaffold.html

Exit 0: every pair passes and every colour token is in a pair.
Exit 1: a pair fails, names an unknown token, or a colour token is unpaired.
Exit 2: the page cannot be read, or has no :root tokens or no pairs block.
Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _luminance(hex6: str) -> float:
    h = hex6.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def ratio(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two opaque #rrggbb colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _norm(colour: str) -> str:
    h = colour.strip().lstrip("#").lower()
    if len(h) in (3, 4):
        h = "".join(ch * 2 for ch in h)
    if len(h) not in (6, 8) or any(ch not in "0123456789abcdef" for ch in h):
        raise ValueError(f"not a hex colour: {colour!r}")
    return h


def composite(fg: str, bg: str) -> str:
    """Flatten a #rrggbb or #rrggbbaa colour over an opaque background."""
    f, b = _norm(fg), _norm(bg)[:6]
    alpha = int(f[6:8], 16) / 255 if len(f) == 8 else 1.0
    out = ""
    for i in (0, 2, 4):
        c = int(f[i:i + 2], 16) * alpha + int(b[i:i + 2], 16) * (1 - alpha)
        out += f"{int(c + 0.5):02x}"
    return "#" + out


LOCKED_BEGIN = "/* dossier:locked:begin"
LOCKED_END = "/* dossier:locked:end */"
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_VAR = re.compile(r"^var\(\s*--([\w-]+)\s*\)$")
_NUM = r"\s*(\d*\.?\d+%?)\s*"
_RGB = re.compile(rf"^rgba?\({_NUM}[,\s]{_NUM}[,\s]{_NUM}(?:[,/]{_NUM})?\)$", re.I)
_COLOUR_FN = re.compile(r"^(?:hsla?|hwb|lab|lch|oklab|oklch|color)\(.*\)$", re.I)


def _rgb_hex(m) -> str:
    """#rrggbb(aa) for an rgb()/rgba() match; channels and alpha may be percentages."""
    def scale(v, top):
        return float(v[:-1]) / 100 * top if v.endswith("%") else float(v)
    out = "#" + "".join(f"{round(min(scale(v, 255), 255)):02x}" for v in m.groups()[:3])
    alpha = m.group(4)
    if alpha is not None:
        out += f"{round(min(scale(alpha, 1), 1) * 255):02x}"
    return out


def _locked(html: str) -> str:
    start = html.find(LOCKED_BEGIN)
    end = html.find(LOCKED_END, start + 1)
    return html[start:end] if start != -1 and end != -1 else html


def parse_tokens(html: str) -> dict:
    """Colour custom properties from the first :root block, locked block first.

    Values are lowercased #hex; rgb()/rgba() become #hex; var(--x) resolves to
    x's value; non-colour tokens (fonts, shadows, sizes) are skipped. Another
    colour function (hsl(), oklch(), ...) is an error rather than a silent skip.
    """
    css = re.sub(r"/\*.*?\*/", "", _locked(html), flags=re.S)
    m = re.search(r":root\s*\{(.*?)\}", css, flags=re.S)
    if not m:
        raise ValueError("no :root block with colour tokens found")
    raw = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", m.group(1)))
    tokens = {}
    for name, value in raw.items():
        value = value.strip()
        seen = {name}
        while _VAR.match(value):
            target = _VAR.match(value).group(1)
            if target in seen or target not in raw:
                break
            seen.add(target)
            value = raw[target].strip()
        if _HEX.match(value):
            tokens[name] = "#" + _norm(value)
        elif _RGB.match(value):
            tokens[name] = _rgb_hex(_RGB.match(value))
        elif _COLOUR_FN.match(value):
            raise ValueError(f"--{name}: {value} is not supported; write it as #hex or rgb()")
    return tokens


# Minimum ratios, WCAG 2.x AA: body text 4.5, large text (24px, or 18.66px bold) 3,
# graphics and UI parts 3. "decor" pairs are listed so every token is accounted
# for, and are reported but never fail.
MINIMUM = {"text": 4.5, "large": 3.0, "graphic": 3.0, "decor": 1.0}


def parse_pairs(html: str) -> list:
    """Declared pairs from the scaffold's dossier:pairs comment.

    One pair per line: kind, foreground token, background token, label.
    A background written a/b means token a laid over token b.
    """
    m = re.search(r"/\*\s*dossier:pairs\b(.*?)\*/", html, flags=re.S)
    if not m:
        raise ValueError("no /* dossier:pairs */ block found")
    pairs = []
    for line in m.group(1).splitlines():
        parts = line.split(None, 3)
        if not parts:
            continue
        if len(parts) < 4 or parts[0] not in MINIMUM:
            raise ValueError(f"bad pair line: {line.strip()!r}")
        pairs.append(tuple(parts[:3]) + (parts[3].strip(),))
    return pairs


def _resolve(tokens: dict, spec: str) -> str:
    """An opaque #rrggbb for a background spec: token, or token/token/... layered top first."""
    names = spec.split("/")
    for name in names:
        if name not in tokens:
            raise KeyError(f"unknown token --{name}")
    colour = tokens[names[-1]]
    if len(_norm(colour)) == 8:
        raise KeyError(f"--{names[-1]} is translucent; name the colour it sits on (a/b)")
    for name in reversed(names[:-1]):
        colour = composite(tokens[name], colour)
    return colour


def check(tokens: dict, pairs: list) -> list:
    """One result row per pair: label, kind, fg, bg, ratio, minimum, ok, error."""
    rows = []
    for kind, fg_name, bg_spec, label in pairs:
        row = {"label": label, "kind": kind, "fg": None, "bg": None, "ratio": None,
               "minimum": MINIMUM[kind], "ok": False, "error": None}
        try:
            row["bg"] = _resolve(tokens, bg_spec)
            if fg_name not in tokens:
                raise KeyError(f"unknown token --{fg_name}")
            row["fg"] = composite(tokens[fg_name], row["bg"])
        except KeyError as exc:
            row["error"] = exc.args[0]
        else:
            row["ratio"] = ratio(row["fg"], row["bg"])
            row["ok"] = kind == "decor" or row["ratio"] >= row["minimum"]
        rows.append(row)
    return rows


def unpaired(tokens: dict, pairs: list) -> list:
    """Colour tokens that no declared pair mentions, sorted."""
    used = set()
    for _, fg, bg, _ in pairs:
        used.add(fg)
        used.update(bg.split("/"))
    return sorted(set(tokens) - used)


DEFAULT_PAGE = Path(__file__).resolve().parent.parent / "assets" / "scaffold.html"


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("page", nargs="?", default=str(DEFAULT_PAGE),
                        help="HTML file holding the tokens and the dossier:pairs block "
                             "(default: the skill's assets/scaffold.html)")
    args = parser.parse_args(argv)
    try:
        html = Path(args.page).read_text(encoding="utf-8")
        tokens = parse_tokens(html)
        pairs = parse_pairs(html)
    except (OSError, ValueError) as exc:
        print(f"check_contrast: {exc}", file=sys.stderr)
        return 2
    rows = check(tokens, pairs)
    for r in rows:
        status = "PASS" if r["ok"] else "FAIL"
        if r["error"]:
            print(f"{status}  {r['label']}: {r['error']}")
        else:
            print(f"{status}  {r['ratio']:5.2f} >= {r['minimum']:<3}  {r['fg']} on {r['bg']}  "
                  f"{r['kind']:7}  {r['label']}")
    loose = unpaired(tokens, pairs)
    for name in loose:
        print(f"FAIL  --{name} is a colour token that no dossier:pairs line checks")
    failed = sum(not r["ok"] for r in rows) + len(loose)
    print(f"{len(rows)} pairs, {failed} failed" + ("" if failed else ": ALL PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
