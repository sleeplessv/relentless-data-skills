"""Render the statusline README screenshots into skills/statusline/assets/.

Runs skills/statusline/scripts/statusline.sh against a throwaway repo and a
fake PR cache, as tests/test_statusline.py does, converts its ANSI output to
HTML, and screenshots the HTML with headless Google Chrome. Each image comes
in a dark and a light version. Rerun after changing the script's colours:

    python3 scripts/statusline_screenshots.py
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "statusline" / "scripts" / "statusline.sh"
OUT = REPO_ROOT / "skills" / "statusline" / "assets"
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
REPO_URL = "https://github.com/acme/widgets"

THEMES = {
    "dark": {"bg": (30, 30, 30), "fg": (212, 212, 212), "label": "#9a9ea8", "rule": "#55585f", "frame": "#3a3a3a"},
    "light": {"bg": (250, 250, 248), "fg": (36, 36, 36), "label": "#5f6470", "rule": "#b8b8b2", "frame": "#dcdcd6"},
}

RUNNING = [{"__typename": "CheckRun", "status": "IN_PROGRESS"}]
FAILED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]


def pr(number, closes=(), checks=(), branch=None, draft=False):
    return {
        "number": number,
        "url": f"{REPO_URL}/pull/{number}",
        "isDraft": draft,
        "isCrossRepository": False,
        "headRefName": branch or f"branch-{number}",
        "statusCheckRollup": list(checks),
        "closingIssuesReferences": [{"number": n, "url": f"{REPO_URL}/issues/{n}"} for n in closes],
    }


PRS = [
    pr(48),
    pr(47, closes=[46], checks=RUNNING, branch="ticket-46-preflight"),
    pr(45, closes=[39, 41], checks=FAILED),
    pr(44, draft=True),
    pr(42, closes=[37]),
    pr(41),
    pr(40, draft=True),
]


def run(branch, used, prs, tmp: Path) -> list[str]:
    """Run the script in a fresh repo named my-project on `branch`. Return its lines."""
    tmp.mkdir()
    repo = tmp / "my-project"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q", "-b", branch], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    key = subprocess.run(["cksum"], input=str(repo), capture_output=True, text=True, check=True).stdout.split()[0]
    cache = tmp / "cache" / "claude-statusline"
    cache.mkdir(parents=True)
    (cache / f"prs-v2-{key}.json").write_text(json.dumps(prs))
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "XDG_CACHE_HOME": str(tmp / "cache")}
    stdin = json.dumps({
        "model": {"display_name": "Opus 5.5"},
        "effort": {"level": "high"},
        "context_window": {"total_input_tokens": used, "context_window_size": 200000,
                           "used_percentage": used / 2000},
        "workspace": {"current_dir": str(repo)},
    })
    out = subprocess.run(["sh", str(SCRIPT)], input=stdin, capture_output=True, text=True, env=env, check=True)
    return out.stdout.split("\n")


SGR = re.compile(r"\x1b\[([0-9;]*)m|\x1b\]8;;[^\x1b]*\x1b\\")


def plain(line: str) -> str:
    return SGR.sub("", line)


def to_html(line: str, theme: dict) -> str:
    """One span per visible character, so annotations can measure any range."""
    st: dict = {}
    out = []
    pos = 0

    def emit(text):
        for ch in text:
            fg = st.get("fg", theme["fg"])
            bg = st.get("bg")
            if st.get("dim"):
                base = bg or theme["bg"]
                fg = tuple(int(a * 0.55 + b * 0.45) for a, b in zip(fg, base))
            css = [f"color:rgb{fg}"]
            if bg:
                css.append(f"background:rgb{bg}")
            if st.get("bold"):
                css.append("font-weight:700")
            out.append(f'<span class="c" style="{";".join(css)}">{html.escape(ch)}</span>')

    for m in SGR.finditer(line):
        emit(line[pos:m.start()])
        pos = m.end()
        if m.group(1) is None:
            continue
        p = [int(x) for x in m.group(1).split(";") if x] or [0]
        i = 0
        while i < len(p):
            c = p[i]
            if c == 0:
                st.clear()
            elif c == 1:
                st["bold"] = True
            elif c == 2:
                st["dim"] = True
            elif c == 22:
                st.pop("bold", None)
                st.pop("dim", None)
            elif c in (38, 48) and p[i + 1] == 2:
                st["fg" if c == 38 else "bg"] = tuple(p[i + 2:i + 5])
                i += 4
            i += 1
    emit(line[pos:])
    return "".join(out)


def span(line: str, needle: str, nth: int = 0) -> tuple[int, int]:
    """Character range of the nth `needle` in the plain text of `line`."""
    text = plain(line)
    start = -1
    for _ in range(nth + 1):
        start = text.index(needle, start + 1)
    return start, start + len(needle)


PAGE = """<!doctype html><meta charset="utf-8">
<style>
html,body {{ margin:0; background:transparent; }}
#shot {{ display:inline-block; padding:8px; }}
.term {{ background:rgb{bg}; border:1px solid {frame}; border-radius:10px; overflow:hidden; }}
.bar {{ height:26px; display:flex; gap:7px; align-items:center; padding-left:12px; border-bottom:1px solid {frame}; }}
.bar i {{ width:11px; height:11px; border-radius:50%; background:{frame}; }}
.body {{ padding:14px 20px 16px; display:grid; gap:4px; }}
.row {{ display:flex; align-items:baseline; gap:14px; }}
.line {{ font:15px/1.6 "SF Mono", Menlo, monospace; white-space:pre; position:relative; }}
.notes {{ position:relative; font:12px/1.3 -apple-system, system-ui, sans-serif; color:{label}; }}
.notes .rule {{ position:absolute; top:0; height:6px; border:1px solid {rule}; border-top:0; border-radius:0 0 3px 3px; }}
.notes .lbl {{ position:absolute; white-space:nowrap; }}
.gap {{ height:6px; }}
</style>
<div id="shot"><div class="term"><div class="bar"><i></i><i></i><i></i></div><div class="body">{rows}</div></div></div>
<script>
// Place each label under its character range, in the first row where it fits.
document.querySelectorAll(".notes").forEach(notes => {{
  const chars = notes.parentElement.previousElementSibling.querySelectorAll(".line .c");
  const origin = notes.getBoundingClientRect().left;
  const rows = [];
  JSON.parse(notes.dataset.spans).forEach(([a, b, text]) => {{
    const left = chars[a].getBoundingClientRect().left - origin;
    const right = chars[b - 1].getBoundingClientRect().right - origin;
    const rule = document.createElement("div");
    rule.className = "rule"; rule.style.left = (left + 1) + "px"; rule.style.width = (right - left - 4) + "px";
    const lbl = document.createElement("div");
    lbl.className = "lbl"; lbl.textContent = text;
    notes.append(rule, lbl);
    const w = lbl.getBoundingClientRect().width;
    // Centre the label, or nudge it right while it still starts under its rule.
    const centred = Math.max(0, (left + right) / 2 - w / 2);
    let r = rows.findIndex(end => Math.max(centred, end + 10) < right - 12);
    if (r < 0) {{ r = rows.length; rows.push(-Infinity); }}
    const x = Math.max(centred, rows[r] + 10);
    rows[r] = x + w;
    lbl.style.left = x + "px"; lbl.style.top = (10 + r * 17) + "px";
  }});
  notes.style.height = (10 + rows.length * 17) + "px";
}});
const r = document.getElementById("shot").getBoundingClientRect();
document.title = Math.ceil(r.width) + "x" + Math.ceil(r.height);
</script>"""


def render(name: str, rows: list[tuple[str, list]]):
    """rows: (ANSI line, [(start, end, note)]) per status line."""
    for theme_name, theme in THEMES.items():
        parts = []
        for line, notes in rows:
            parts.append(f'<div class="row"><div class="line">{to_html(line, theme)}</div></div>')
            if notes:
                parts.append(f'<div class="row"><div class="notes" style="flex:1" '
                             f"data-spans='{html.escape(json.dumps(notes))}'></div></div>")
                parts.append('<div class="gap"></div>')
        page = PAGE.format(rows="".join(parts), bg=theme["bg"], frame=theme["frame"],
                           label=theme["label"], rule=theme["rule"])
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "shot.html"
            src.write_text(page)
            # First pass measures the shot; the second screenshots it at that size.
            dom = subprocess.run([CHROME, "--headless", "--disable-gpu", "--window-size=1400,900",
                                  "--dump-dom", src.as_uri()], capture_output=True, text=True, check=True).stdout
            w, h = re.search(r"<title>(\d+)x(\d+)</title>", dom).groups()
            out = OUT / f"{name}-{theme_name}.png"
            subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=2", "--default-background-color=00000000",
                            f"--window-size={w},{h}", f"--screenshot={out}", src.as_uri()],
                           capture_output=True, check=True)
            print(f"wrote {out.relative_to(REPO_ROOT)} ({w}x{h} @2x)")


def main():
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d).resolve()
        l1, l2 = run("ticket-46-preflight", 42000, PRS, tmp / "overview")[:2]
        render("overview", [(l1, []), (l2, [])])

        render("anatomy", [
            (l1, [
                (*span(l1, "Opus 5.5"), "model"),
                (*span(l1, "· high"), "effort"),
                (*span(l1, "▰▰▱▱▱▱▱▱▱▱"), "context bar"),
                (*span(l1, "42k/200k (21%)"), "tokens used / window"),
                (*span(l1, "my-project"), "directory"),
                (*span(l1, "(ticket-46-preflight)"), "git branch"),
            ]),
            (l2, [
                (*span(l2, "#48 ∅"), "PR, no issue"),
                (*span(l2, "[#47  46 ]"), "your branch's PR"),
                (*span(l2, " 39 "), "issue it closes"),
                (*span(l2, "#44"), "draft"),
                (*span(l2, "+2"), "more"),
                (*span(l2, "PRs ✓3 ⧗1 ✗1 ✎2"), "open PRs by state"),
            ]),
        ])


if __name__ == "__main__":
    main()
