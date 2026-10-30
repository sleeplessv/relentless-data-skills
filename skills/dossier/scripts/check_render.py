#!/usr/bin/env python3
"""Render a dossier HTML file in headless Chromium and check what a reader sees.

Mermaid reports most mistakes by drawing an error diagram, with nothing on the
console, so this check reads the rendered page. It waits until Mermaid has
finished drawing, including diagrams a script adds after load, opens hidden
containers (tabs, toggles, <details>) the way a reader would, and fails when a
diagram:

  - is Mermaid's error diagram, or never rendered
  - collapsed to a speck or shows no labels, which is what a diagram drawn
    inside a display:none container looks like once it is shown
  - is shrunk until its labels are unreadable, or cut off by an overflow:hidden box

It also fails on broken images, resources that answer 404 or name a host that
does not exist, page and console errors, and a page that freezes its tab.

For a dossier it adds, from the source: a structure pass (answer box with a
claim, Limits as the last section, every figure and table numbered in order
with a caption, Mermaid used for sequence diagrams only, DAG node count), the
allowed hosts (cdn.jsdelivr.net) with exact x.y.z pins, and the locked
stylesheet block, compared with the skill's assets/scaffold.html. From the
rendered page: Vega charts drawn (it waits on window.__vegaDone), static-SVG
DAGs legible and unclipped, and no figure frame, table or page wider than its
box at 768, 1200, 1280 and 1440 px. Warnings cover the softer house rules:
long paragraphs, sections with no figure, tables over 20 visible rows,
headings not in sentence case, slop words, red or amber category fills, side
strips, small diagram text, and libraries outside the scaffold's block.

Prints JSON, then a final PASS, FAIL, or BLOCKED line. Exit codes:
  0  PASS     every check ran and passed
  1  FAIL     the page has a defect; fix it and rerun
  2  BLOCKED  the environment kept the check from running (no Playwright or
              browser, a CDN unreachable); the page is unverified, not passing

A diagram the page draws only when its hidden container is shown is listed
under "unverified": its source is rendered offscreen to catch errors, but the
page's own reveal is not exercised.

Writes to --shots (default: <report-stem>-check/ beside the report), replacing
earlier shots: page-<k>.png, the page in viewport-height slices with hidden
diagrams opened, diagram-<n>.png per Mermaid diagram, chart-<n>.png per Vega
chart and dag-<n>.png per DAG drawing. Read them all: the script cannot tell
whether a chart or a DAG shows what its caption says (the JSON's "review").

Usage:
  uv run --no-project --with playwright python check_render.py REPORT.html [--shots DIR]
      [--scaffold assets/scaffold.html]
"""

import argparse
import asyncio
import html as htmllib
import json
import os
import re
import sys
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dag_svg import MAX_NODES, WARN_ABOVE  # ships beside this script in scripts/

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
EXIT = {PASS: 0, FAIL: 1, BLOCKED: 2}
VIEWPORT = {"width": 1280, "height": 900}
LOAD_TIMEOUT_S = 30   # for the page's load event; the scaffold runs Mermaid itself (startOnLoad: false)
QUIET_MS = 2000       # Mermaid's output must sit unchanged this long before it is read
CALL_TIMEOUT_S = 10   # a page that cannot answer a query this fast has a frozen tab
PROBE_TIMEOUT_S = 15  # one offscreen re-render of a diagram's source
MIN_LABEL_PX = 6      # labels shrunk below this are unreadable: FAIL
SMALL_LABEL_PX = 9    # below this, warn that the diagram is shrunk to fit
SMALL_TEXT_PX = 10    # extra viewports: diagram text below this is hard to read on a tablet
TINY_PX = 24          # a diagram rendered narrower or shorter than this is a speck
CLIP_SLACK_PX = 2
MAX_SLICES = 40
MAX_PROBES = 20
# The only hosts a dossier may load from: the scaffold's library block is on
# jsdelivr (fastly. is its mirror). Any other host fails the structure pass, and
# a network failure on it is a bad URL in the page, not the environment.
CDN_HOSTS = {"cdn.jsdelivr.net", "fastly.jsdelivr.net"}
# The scaffold's pinned library block. Another package, or another version,
# is a warning: the gallery and its footguns were proven at these versions.
LIBRARIES = {"mermaid": "11.17.2", "vega": "6.4.0", "vega-lite": "6.5.0", "vega-embed": "7.3.0"}
NETWORK_PROBE_URL = f"https://cdn.jsdelivr.net/npm/mermaid@{LIBRARIES['mermaid']}/package.json"
INSTALL_HINT = "uv run --no-project --with playwright playwright install chromium"
REVIEW = ("This check proves structure and that things drew, not that they are right. Open every "
          "screenshot: chart-<n>.png for each Vega chart (axes, values, colours against its "
          "caption), dag-<n>.png for each DAG (arrows meet their nodes, names readable), "
          "diagram-<n>.png for each sequence diagram, and page-<k>.png for every hand-built visual.")
# Statuses for which Mermaid ran and drew something wrong: proof of a defect.
DRAWN_BAD = {"error", "empty", "illegible", "clipped", "spill"}
# Statuses for which nothing was drawn: a defect, unless the network is to blame.
NOT_DRAWN = {"unrendered", "rendering"}
# Elements whose content never becomes live page elements.
INERT = {"template", "noscript", "textarea", "title", "xmp", "iframe",
         "noembed", "noframes"}
FETCH_FAILED = re.compile(
    r"Failed to fetch dynamically imported module|error loading dynamically "
    r"imported module|Importing a module script failed", re.I)


# ---------------------------------------------------------------------------
# Pure logic: no Playwright needed (tests/test_dossier.py covers it).

def read_source(path):
    """Decode the report as a browser would: BOM, then <meta charset>, then UTF-8."""
    data = Path(path).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    m = re.search(rb"""<meta[^>]*charset\s*=\s*["']?\s*([\w.:-]+)""", data[:4096], re.I)
    for enc in ([m.group(1).decode("ascii")] if m else []) + ["utf-8"]:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("cp1252", "replace")


class MermaidBlocks(HTMLParser):
    """Collect each live `class="mermaid"` element's source text and start line.

    Skips markup the browser never turns into page elements: <template> and
    <noscript> content, <textarea> and <title> text, and comments.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._tag = None    # tag of the open Mermaid block
        self._depth = 0
        self._inert = None  # [tag, depth] of the inert element being skipped

    def handle_starttag(self, tag, attrs):
        if self._inert:
            if tag == self._inert[0]:
                self._inert[1] += 1
            return
        if tag in INERT:
            self._inert = [tag, 1]
            return
        if self._tag is not None:
            if tag == self._tag:
                self._depth += 1
            return
        classes = (dict(attrs).get("class") or "").split()
        if "mermaid" in classes:
            self._tag, self._depth = tag, 1
            self.blocks.append({"line": self.getpos()[0], "source": ""})

    def handle_endtag(self, tag):
        if self._inert:
            if tag == self._inert[0]:
                self._inert[1] -= 1
                if not self._inert[1]:
                    self._inert = None
            return
        if self._tag is not None and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self._tag = None

    def handle_data(self, data):
        if self._tag is not None and not self._inert:
            self.blocks[-1]["source"] += data


def mermaid_blocks(html):
    parser = MermaidBlocks()
    parser.feed(html)
    parser.close()
    return parser.blocks


def locate(text, lines):
    """First line where a diagram's source lines appear consecutively in the file."""
    want = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not want:
        return None
    have = [htmllib.unescape(ln).strip() for ln in lines]
    for i in range(len(have) - len(want) + 1):
        got = have[i:i + len(want)]
        if len(want) == 1:
            if want[0] in got[0]:
                return i + 1
        elif (got[0].endswith(want[0]) and got[-1].startswith(want[-1])
              and got[1:-1] == want[1:-1]):
            return i + 1
    return None


def assign_lines(diagrams, html):
    """Give each diagram the source line it was drawn from.

    Pairs with the file's class="mermaid" blocks by source text, not position,
    so a diagram a script added, or a block inside <template>, cannot shift the
    others. A diagram matching no block (another selector, or built by a
    script) is looked up as text; failing that it gets line None.
    """
    unused = [(norm(b["source"]), b["line"]) for b in mermaid_blocks(html)]
    lines = html.splitlines()
    for d in diagrams:
        d["line"] = None
        if d.get("text") is None:
            continue
        key = norm(d["text"])
        for i, (k, line) in enumerate(unused):
            if k == key:
                d["line"] = line
                del unused[i]
                break
        else:
            d["line"] = locate(d["text"], lines)


IMPORT = re.compile(r"""import\s+mermaid\s+from\s+["']([^"']+)["']""")
MERMAID_ENTRY = re.compile(r"/mermaid(?:\.esm)?(?:\.min)?\.m?js$")


def strip_js_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def import_urls(script_texts):
    """Mermaid import URLs in the page's module scripts, ignoring commented-out ones."""
    urls = []
    for text in script_texts:
        urls += IMPORT.findall(strip_js_comments(text))
    return urls


def mermaid_module(imports, loaded):
    """The Mermaid build the page itself loaded, to re-parse failing diagrams with."""
    for url in imports:
        if url in loaded:
            return url
    for url in loaded:
        if MERMAID_ENTRY.search(urlsplit(url).path):
            return url
    return None


def scale_of(fact):
    """Rendered size over natural (viewBox) size; None when there is no viewBox."""
    ratios = []
    if fact.get("natural_width"):
        ratios.append(fact["width"] / fact["natural_width"])
    if fact.get("natural_height") and fact.get("holds") != "iframe":
        ratios.append(fact["height"] / fact["natural_height"])
    return round(min(ratios), 2) if ratios else None


def label_px(fact):
    """Rendered label size: font size times scale. None for a diagram with no
    real natural size (a speck), which the speck rule judges instead."""
    scale = scale_of(fact)
    if scale is None or min(fact.get("natural_width", 0), fact.get("natural_height", 0)) < TINY_PX:
        return None
    return (fact.get("font_px") or 16) * scale


def diagram_status(fact):
    """Classify one diagram from what the rendered page shows: (status, problem)."""
    w, h = fact.get("width", 0), fact.get("height", 0)
    if fact.get("error_marks") or fact.get("role") == "error":
        return "error", "Mermaid drew its error diagram"
    if fact.get("holds") in ("text", "nothing"):
        if fact.get("processed"):
            return "rendering", "Mermaid started on it but never finished drawing it"
        if fact.get("hidden_at_settle"):
            return "lazy", None   # in a hidden container; the page may draw it when shown
        return "unrendered", "Mermaid never rendered it; a reader sees its source text"
    if fact.get("wrapper"):
        return "rendering", "Mermaid had not finished drawing it"
    if not fact.get("visible"):
        return "hidden", None
    px = label_px(fact)
    if px is not None and px < MIN_LABEL_PX:
        return "illegible", (f"it is shrunk to {scale_of(fact):.0%} of its natural size to fit, "
                             f"so its labels are about {px:.0f}px tall; split it or lay it "
                             "out top-down")
    if w < TINY_PX or h < TINY_PX:
        return "empty", f"it renders as a {w}x{h} px speck"
    if fact.get("labels") and not fact.get("shown_labels"):
        return "empty", f"none of its {fact['labels']} labels has a visible size"
    vw, vh = fact.get("visible_width", w), fact.get("visible_height", h)
    if w - vw > CLIP_SLACK_PX or h - vh > CLIP_SLACK_PX:
        return "clipped", (f"an overflow:hidden ancestor cuts it off; only {vw}x{vh} "
                           f"of its {w}x{h} px is visible")
    return "ok", None


def explain(d, probe):
    """Fold an offscreen re-render of a diagram's source into its entry.

    `probe` is what the page's own Mermaid made of the source when drawn in a
    visible offscreen box: a parse_error, a draw_error, or a rendered size.
    A diagram that looks fine but was drawn while hidden gets a warning when
    its natural size differs from the visible render's.
    """
    if d["status"] == "ok":
        if probe and probe.get("natural_height") and d.get("_natural"):
            mine, theirs = d["_natural"], (probe["natural_width"], probe["natural_height"])
            if any(abs(a - b) > max(8, 0.05 * b) for a, b in zip(mine, theirs)):
                d["warning"] = (f"Mermaid drew it while its container was hidden, and it is "
                                f"{mine[0]}x{mine[1]} where a visible render is "
                                f"{theirs[0]}x{theirs[1]}; check its screenshot")
        return
    if not probe or probe.get("unavailable"):
        if d["status"] == "lazy":
            d["unverified"] = ("drawn only when its container is shown, and the page's "
                               "Mermaid could not be loaded to check its source")
        return
    err = probe.get("parse_error") or probe.get("draw_error")
    if err and FETCH_FAILED.search(err):
        d["env"] = True   # a Mermaid chunk failed to download: no evidence either way
        d["error"] = err
        return
    if err:
        d["error"] = err if probe.get("parse_error") else "while drawing: " + err
        if d["status"] == "lazy":
            d["status"] = "error"
            d["problem"] = "it is drawn only when its container is shown, and its source fails"
        return
    speck = probe.get("width", 0) < TINY_PX or probe.get("height", 0) < TINY_PX
    if d["status"] == "lazy":
        if speck:
            d["status"] = "empty"
            d["problem"] = "it is drawn only when its container is shown, and has no content"
        else:
            d["unverified"] = ("drawn only when its container is shown; its source renders "
                               "cleanly offscreen, but the page's own reveal was not exercised")
    elif not speck and d.get("hidden_when_drawn"):
        d["problem"] += ("; it was drawn while its container was hidden, which breaks "
                         "Mermaid's layout, and the source itself renders cleanly. Draw it "
                         "while visible (see HTML-REPORT.md, Interactivity)")
    elif not speck and d["status"] == "error":
        d["problem"] += ("; the same source renders cleanly on its own, so something else "
                         "on the page broke it (two Mermaid versions?)")
    elif speck and d["status"] == "empty":
        d["problem"] += "; the diagram has no content"


def request_problem(url, failure=None, status=None, network_ok=True):
    """Classify one request the page could not complete.

    Returns None (no problem), ("defect", why) for a fault in the page, or
    ("blocked", why) when the environment, not the page, is to blame.
    """
    parts = urlsplit(url)
    if parts.scheme == "file":
        if failure and failure != "net::ERR_ABORTED":
            return "defect", f"{unquote(parts.path)} could not be loaded ({failure})"
        return None
    if parts.scheme not in ("http", "https"):
        return None
    cdn = (parts.hostname or "") in CDN_HOSTS
    if status is not None:
        if status >= 500 and cdn:
            return "blocked", f"{url} answered HTTP {status}; the CDN is having trouble"
        if status >= 400:
            return "defect", f"{url} answered HTTP {status}"
        return None
    if not failure or failure == "net::ERR_ABORTED":
        return None   # cancelled by the page, or already reported by its HTTP status
    if failure == "net::ERR_BLOCKED_BY_ORB":
        return "defect", (f"{url} answered with something other than the resource "
                          "(usually a 404 page)")
    if cdn or not network_ok:
        return "blocked", f"{url} could not be reached ({failure})"
    return "defect", f"{url} could not be reached ({failure}) while other hosts loaded"


def verdict(result):
    """Proof of a defect beats an environment problem, which beats softer evidence.

    An error diagram, a 404, or a broken image is a defect whatever else went
    wrong. An unreachable CDN explains unrendered diagrams and script errors,
    so those count only when the network was fine. Structure faults, the
    locked-block check among them, come from the source alone, so they fail
    even when no browser ran.
    """
    if result.get("structure"):
        return FAIL
    if result.get("blocked"):
        return BLOCKED
    diagrams = (result.get("diagrams", []) + result.get("charts", [])
                + result.get("dags", []))
    requests = result.get("requests", [])
    if (any(d["status"] in DRAWN_BAD and not d.get("env") for d in diagrams)
            or any(r["kind"] == "defect" for r in requests)
            or result.get("layout")
            or result.get("broken_images") or result.get("hung")):
        return FAIL
    if (any(r["kind"] == "blocked" for r in requests)
            or any(d.get("env") for d in diagrams) or result.get("incomplete")):
        return BLOCKED
    if (any(d["status"] in NOT_DRAWN for d in diagrams)
            or result.get("page_errors") or result.get("console_errors")):
        return FAIL
    return PASS


LOCKED_RE = re.compile(r"/\*\s*dossier:locked:begin\s+(\S+)\s*\*/(.*?)/\*\s*dossier:locked:end\s*\*/",
                       re.S)


def locked_version_and_text(html):
    """(version, normalised text) of the locked stylesheet block, or None."""
    m = LOCKED_RE.search(html or "")
    if not m:
        return None
    text = "\n".join(ln.rstrip() for ln in m.group(2).replace("\r\n", "\n").split("\n"))
    return m.group(1), text.strip("\n")


def locked_problem(report_html, scaffold_html):
    """Why the report's locked block is not the scaffold's, or None when it is.

    Compared with the scaffold at check time, so a palette change needs only
    a scaffold edit.
    """
    report_locked = locked_version_and_text(report_html)
    scaffold_locked = locked_version_and_text(scaffold_html)
    if scaffold_locked is None:
        return "the scaffold has no locked block to compare against"
    scaffold_version, scaffold_text = scaffold_locked
    if report_locked is None:
        return ("the page has no locked block (/* dossier:locked:begin " + scaffold_version
                + " */ ... /* dossier:locked:end */); copy the stylesheet from assets/scaffold.html")
    report_version, report_text = report_locked
    if report_version != scaffold_version:
        return (f"the page's locked block is {report_version}, the scaffold's is {scaffold_version}; "
                "copy the locked block from assets/scaffold.html again")
    if report_text != scaffold_text:
        return ("the locked block differs from the scaffold's; put per-report CSS in the "
                "dossier:report block and restore the locked block from assets/scaffold.html")
    return None


RESOURCE_ATTRS = {"script": "src", "img": "src", "iframe": "src", "source": "src",
                  "video": "src", "audio": "src", "embed": "src", "link": "href"}
JS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)["']([^"']+)["']""")
NPM_PATH = re.compile(r"^/npm/((?:@[^/@]+/)?[^/@]+)(?:@([^/]*))?")
PINNED = re.compile(r"^\d+\.\d+\.\d+$")


class Resources(HTMLParser):
    """Collect resource URLs (src/href) and JS import specifiers in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls, self._script = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in RESOURCE_ATTRS and a.get(RESOURCE_ATTRS[tag]):
            self.urls.append(a[RESOURCE_ATTRS[tag]].strip())
        if tag == "script" and not a.get("src"):
            self._script = []

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.urls += JS_IMPORT.findall(strip_js_comments("".join(self._script)))
            self._script = None

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)


def resource_urls(html):
    """Remote URLs the page loads: src/href of resources and JS imports, in order."""
    parser = Resources()
    parser.feed(html)
    parser.close()
    return [u for u in parser.urls if urlsplit(u).scheme in ("http", "https")]


def npm_package(url):
    """(package, version or None) for a jsdelivr /npm/ URL, else None."""
    parts = urlsplit(url)
    m = NPM_PATH.match(parts.path) if parts.hostname in CDN_HOSTS else None
    return (m.group(1), m.group(2)) if m else None


def url_problem(url):
    """Why a resource URL breaks the house rules (host, pin), or None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if parts.hostname not in CDN_HOSTS:
        return (f"{url}: {parts.hostname} is not an allowed host; load libraries from "
                "cdn.jsdelivr.net as the scaffold's library block does, and inline everything else")
    pkg = npm_package(url)
    if not pkg or not PINNED.match(pkg[1] or ""):
        return f"{url}: the version is not pinned; name an exact x.y.z version"
    return None


def library_warnings(urls):
    """Packages outside the scaffold's library block, or at another version."""
    out = []
    for url in urls:
        pkg = npm_package(url)
        if not pkg or not PINNED.match(pkg[1] or ""):
            continue  # url_problem reports it
        name, version = pkg
        if name not in LIBRARIES:
            out.append(f"{name}@{version} is not in the scaffold's library block "
                       f"({', '.join(f'{k}@{v}' for k, v in LIBRARIES.items())})")
        elif version != LIBRARIES[name]:
            out.append(f"{name}@{version} differs from the scaffold's pin {name}@{LIBRARIES[name]}")
    return counted(out)


# ---------------------------------------------------------------------------
# Structure pass: the house rules a page's source can prove or disprove.

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}
FIGURE_ID = re.compile(r"^(?:fig-(\d+)|table-(\d+)-fig)$")
# Block starts that close an open <p>, as browsers do.
P_CLOSERS = {"p", "div", "ul", "ol", "table", "figure", "section", "h2", "h3", "pre", "details"}
MAX_PARAGRAPH_WORDS = 60
MAX_VISIBLE_ROWS = 20
TOC_FROM_SECTIONS = 4
NOT_PROSE = {"script", "style", "code", "pre", "kbd", "samp", "svg", "template", "noscript"}
# AI vocabulary that leaks in from source material: references/WRITING.md "Banned words"
# ("landscape" is banned only when abstract, which a regex cannot tell, so it is left out).
SLOP = re.compile(r"\b(additionally|crucial(?:ly)?|delv(?:e|es|ed|ing)|enduring|"
                  r"enhanc(?:e|es|ed|ing)|foster(?:s|ed|ing)?|garner(?:s|ed|ing)?|interplay|"
                  r"intricate(?:ly)?|leverag(?:e|es|ed|ing)|pivotal|robust(?:ly|ness)?|"
                  r"seamless(?:ly)?|showcas(?:e|es|ed|ing)|tapestry|testament|"
                  r"underscor(?:e|es|ed|ing)|utili[sz](?:e|es|ed|ing)|vibrant)\b", re.I)


class Node:
    def __init__(self, tag, attrs, line, parent=None):
        self.tag, self.attrs, self.line, self.parent = tag, attrs, line, parent
        self.classes = set((attrs.get("class") or "").split())
        self.children = []   # Node or str

    def walk(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()

    def find(self, pred):
        return [n for n in self.walk() if pred(n)]

    def ancestors(self):
        a = self.parent
        while a is not None:
            yield a
            a = a.parent

    def text(self, skip=lambda n: False):
        out = []
        for c in self.children:
            if isinstance(c, str):
                out.append(c)
            elif not skip(c):
                out.append(c.text(skip))
        return "".join(out)


class Tree(HTMLParser):
    """A forgiving DOM: end tags close the nearest open match; strays are ignored."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node("#root", {}, 1)

    def handle_starttag(self, tag, attrs):
        if self.cur.tag == "p" and tag in P_CLOSERS:
            self.cur = self.cur.parent   # a block start closes the paragraph
        node = Node(tag, {k: v or "" for k, v in attrs}, self.getpos()[0], self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: v or "" for k, v in attrs}, self.getpos()[0], self.cur))

    def handle_endtag(self, tag):
        for a in [self.cur, *self.cur.ancestors()]:
            if a.tag == tag:
                self.cur = a.parent
                return

    def handle_data(self, data):
        self.cur.children.append(data)


def parse_tree(html):
    t = Tree()
    t.feed(html)
    t.close()
    return t.root


def norm(text):
    return " ".join((text or "").split())


def figure_of(node):
    """('Figure'|'Table', n) for a figure container, else None."""
    m = FIGURE_ID.match(node.attrs.get("id", ""))
    if not m:
        return None
    return ("Figure", int(m.group(1))) if m.group(1) else ("Table", int(m.group(2)))


def in_figure(node):
    return any(figure_of(a) for a in node.ancestors())


def hidden(node):
    for a in [node, *node.ancestors()]:
        if "hidden" in a.attrs or re.search(r"display\s*:\s*none", a.attrs.get("style", "")):
            return True
        if a.tag == "details" and "open" not in a.attrs and a is not node:
            return True
    return False


def heading_title(h2):
    """An h2's own words, without the section number and the figure count spans."""
    return norm(h2.text(skip=lambda n: bool(n.classes & {"n", "count"})))


def case_problem(title):
    """'all caps' or 'Title Case' when a heading is not in sentence case."""
    ws = re.findall(r"[A-Za-z][A-Za-z'’-]*", title)
    if len(ws) >= 2 and all(w.isupper() for w in ws):
        return "all caps"
    long = [w for w in ws[1:] if len(w) >= 4 and not w.isupper()]
    caps = [w for w in long if w[0].isupper()]
    if len(caps) >= 2 and 2 * len(caps) > len(long):
        return "Title Case"
    return None


def mermaid_kind(source):
    """The diagram keyword of a Mermaid source (after front matter and %% comments)."""
    lines = [ln.strip() for ln in source.splitlines()]
    lines = [ln for ln in lines if ln]
    if lines and lines[0] == "---":
        end = next((i for i, ln in enumerate(lines[1:], 1) if ln == "---"), 0)
        lines = lines[end + 1:]
    for ln in lines:
        if not ln.startswith("%%"):
            return ln.split()[0]
    return None


def structure(html):
    """(problems, warnings) from the page source: answer box, Limits, figure
    numbering and captions, Mermaid use, DAG size, and the prose warnings."""
    root = parse_tree(html)
    problems, warnings = [], []

    answers = root.find(lambda n: n.tag == "section" and "answer" in n.classes)
    if not answers:
        problems.append('no answer box: add <section class="answer"> with the claim in a '
                        '.claim paragraph at the top')
    elif not answers[0].find(lambda n: "claim" in n.classes):
        problems.append("the answer box has no .claim: state the one claim the dossier defends")

    secs = root.find(lambda n: n.tag == "section" and "sec" in n.classes)
    titled = []
    for s in secs:
        h2 = next(iter(s.find(lambda n: n.tag == "h2")), None)
        titled.append((s, h2, heading_title(h2) if h2 else ""))
    limits = [i for i, (_, _, t) in enumerate(titled) if t.lower() == "limits"]
    if not limits:
        problems.append('no Limits section: end with <section class="sec"> headed "Limits", '
                        'even when it says "None"')
    elif limits[-1] != len(titled) - 1:
        problems.append("the Limits section is not the last section")

    figures = root.find(figure_of)
    counters = {"Figure": [], "Table": []}
    for f in figures:
        kind, n = figure_of(f)
        counters[kind].append(n)
        want = f"{kind} {n}."
        nos = [x for c in f.find(lambda x: "caption" in x.classes)
               for x in c.find(lambda x: "figno" in x.classes)]
        got = norm(nos[0].text()) if nos else ""
        if got != want:
            problems.append(f'{kind} {n} (id="{f.attrs["id"]}", line {f.line}) needs a caption '
                            f'whose .figno reads "{want}"' + (f'; it reads "{got}"' if got else ""))
        # A DAG figure carries its so-what in .dag-notes under an h3 "So what".
        dag_so = any(norm(h.text()).lower() == "so what"
                     for d in f.find(lambda x: "dag-notes" in x.classes)
                     for h in d.find(lambda x: x.tag == "h3"))
        if not dag_so and not f.find(lambda x: "sowhat" in x.classes):
            warnings.append(f'{kind} {n} has no "So what" box (.sowhat .lbl)')
    for kind, nums in counters.items():
        for i, n in enumerate(nums, 1):
            if n != i:
                problems.append(f"{kind} {n} comes where {kind} {i} should: number "
                                f"{kind.lower()}s in the order they appear")
                break

    kinds = ("chart", "mermaid", "dag-frame", "figframe")
    visuals = root.find(lambda n: n.tag == "table" or n.classes & set(kinds)
                        or (n.tag == "svg" and "dag" in n.classes))
    loose = {}
    for v in visuals:
        if in_figure(v) or any(a in visuals for a in v.ancestors()):
            continue
        what = "a table" if v.tag == "table" else "a ." + next((k for k in kinds if k in v.classes), "dag")
        loose.setdefault(what, []).append(str(v.line))
    for what, lines in loose.items():
        problems.append(f"{what} at line {', '.join(lines)} has no numbered caption: put it in a "
                        'figure (id="fig-N" or id="table-N-fig") with .caption .figno')

    for b in mermaid_blocks(html):
        kind = mermaid_kind(b["source"])
        if kind and kind != "sequenceDiagram":
            problems.append(f"the Mermaid diagram at line {b['line']} is a {kind}; Mermaid is for "
                            "sequence diagrams only, so draw graphs and flows with scripts/dag_svg.py")

    frames = root.find(lambda n: "dag-frame" in n.classes)
    frames += [s for s in root.find(lambda n: n.tag == "svg" and "dag" in n.classes)
               if not any(a in frames for a in s.ancestors())]
    for fr in frames:
        svgs = [fr] if fr.tag == "svg" else fr.find(lambda n: n.tag == "svg" and "dag" in n.classes)
        count = max([len(s.find(lambda n: n.tag == "g" and "dn" in n.classes)) for s in svgs] or [0])
        where_ = next(("%s %d" % figure_of(a) for a in fr.ancestors() if figure_of(a)),
                      f"the DAG at line {fr.line}")
        if count > MAX_NODES:
            problems.append(f"{where_} draws {count} nodes; the cap is {MAX_NODES}. Merge "
                            "sibling sets into group nodes or draw a neighbourhood")
        elif count > WARN_ABOVE:
            warnings.append(f"{where_} draws {count} nodes; aim for {WARN_ABOVE} or fewer by "
                            "merging sibling sets into group nodes")

    if len(secs) >= TOC_FROM_SECTIONS:
        if not root.find(lambda n: n.attrs.get("id") == "toc"):
            warnings.append(f"{len(secs)} sections and no table of contents (#toc in .side)")
        elif not root.find(lambda n: "toc-inline" in n.classes):
            warnings.append("no .toc-inline: below 1100px the sidebar contents are hidden")

    for s, h2, title in titled:
        if title and title.lower() != "limits" and not s.find(figure_of):
            warnings.append(f'section "{title}" has no figure or table')
        case = case_problem(title)
        if case:
            warnings.append(f'heading "{title}" is in {case}; use sentence case')

    for p in root.find(lambda n: n.tag == "p"):
        n = len(p.text().split())
        if n > MAX_PARAGRAPH_WORDS:
            warnings.append(f"the paragraph at line {p.line} has {n} words; keep paragraphs to "
                            f"{MAX_PARAGRAPH_WORDS} or split them into bullets")

    for t in root.find(lambda n: n.tag == "table"):
        rows = [r for r in t.find(lambda n: n.tag == "tr")
                if r.find(lambda n: n.tag == "td") and not hidden(r)]
        if len(rows) > MAX_VISIBLE_ROWS:
            warnings.append(f"the table at line {t.line} shows {len(rows)} visible rows; show "
                            f"{MAX_VISIBLE_ROWS} and put the rest behind details.more")

    body = next(iter(root.find(lambda n: n.tag == "body")), root)
    slop = {}
    for m in SLOP.finditer(body.text(skip=lambda n: n.tag in NOT_PROSE)):
        slop[m.group(1).lower()] = slop.get(m.group(1).lower(), 0) + 1
    for w, n in slop.items():
        warnings.append(f'the word "{w}" appears {n} time(s); replace it with a plain word')
    return problems, warnings


SCAFFOLD = Path(__file__).resolve().parent.parent / "assets" / "scaffold.html"


def source_checks(html, scaffold_html, scaffold_path):
    """(problems, warnings, unverified) from the page source alone: the
    structure pass, allowed hosts and pins, the library block, the locked block."""
    problems, warnings = structure(html)
    urls = resource_urls(html)
    problems += counted([p for p in map(url_problem, urls) if p])
    warnings += library_warnings(urls)
    if scaffold_html is None:
        return problems, warnings, [f"locked block not compared: no scaffold at {scaffold_path}"]
    locked = locked_problem(html, scaffold_html)
    if locked:
        problems.append(locked)
    return problems, warnings, []


# ---------------------------------------------------------------------------
# Rendered facts beyond Mermaid: Vega charts, static-SVG DAGs, layout, colour.

VIEWPORTS = (768, 1200, 1440)   # extra widths, checked for overflow and small text only
ALARM_TOKENS = ("--red", "--amber")   # the soft tints sit too close to coral-soft to tell apart
COLOUR_SLACK = 20               # rgb distance under which two colours count as the same
STRIP_PX = 3                    # a left border this thick, with thin other sides, is a side strip


def chart_status(fact):
    """Classify one Vega chart (.chart filled by vegaEmbed): (status, problem)."""
    if not fact.get("visible"):
        return "hidden", None
    if fact.get("error"):
        return "error", f"vegaEmbed failed: {fact['error']}"
    if not fact.get("svg"):
        return "unrendered", ("Vega never drew it (no svg.marks); check the library block and "
                              "that the spec is passed to vegaEmbed")
    if fact.get("width", 0) < TINY_PX or fact.get("height", 0) < TINY_PX:
        return "empty", f"it renders as a {fact.get('width', 0)}x{fact.get('height', 0)} px speck"
    if not fact.get("marks"):
        return "empty", "Vega drew the frame but no marks; check the data and the encoding fields"
    return "ok", None


def dag_status(fact):
    """Classify one static-SVG DAG drawing: (status, problem, warning)."""
    if not fact.get("visible"):
        return "hidden", None, None   # the other orientation (LR/TB) is the one on show
    if fact.get("spills"):
        names = ", ".join(fact["spills"][:5])
        return "spill", f"node text runs out of its box: {names}; shorten the name or widen the node", None
    w, h = fact.get("width", 0), fact.get("height", 0)
    vw, vh = fact.get("visible_width", w), fact.get("visible_height", h)
    if w - vw > CLIP_SLACK_PX or h - vh > CLIP_SLACK_PX:
        return "clipped", f"an overflow:hidden ancestor cuts it off; only {vw}x{vh} of {w}x{h} px is visible", None
    if fact.get("natural_width") and fact.get("font_px"):
        px = fact["font_px"] * w / fact["natural_width"]
        if px < MIN_LABEL_PX:
            return "illegible", f"it is scaled until node names are about {px:.0f}px tall; split it or use TB", None
        if px < SMALL_LABEL_PX:
            return "ok", None, f"node names are scaled to about {px:.0f}px; merge nodes or lay it out top-down"
    return "ok", None, None


def viewport_findings(facts):
    """(problems, warnings) from the extra-viewport pass.

    kind "page": the page scrolls sideways; "frame": a figure frame, table or
    DAG is wider than its box; "code": a code block scrolls; "text": rendered
    diagram text size in px.
    """
    problems, warnings = [], []
    for f in facts:
        at = f"at {f['viewport']}px"
        if f["kind"] == "text":
            if f["px"] < SMALL_TEXT_PX:
                warnings.append(f"{f['label']} text renders at about {f['px']:.1f}px {at}; "
                                "split the diagram or shorten its labels")
        elif f.get("excess", 0) <= CLIP_SLACK_PX:
            continue
        elif f["kind"] == "page":
            problems.append(f"the page scrolls sideways by {f['excess']}px {at}")
        elif f["kind"] == "code":
            warnings.append(f"{f['label']} scrolls sideways by {f['excess']}px {at}")
        else:
            problems.append(f"{f['label']} is {f['excess']}px wider than its frame {at}; "
                            "narrow its columns in the dossier:report block")
    return counted(problems), counted(warnings)


def parse_colour(text):
    """(r, g, b) from #rgb, #rrggbb, rgb() or rgba(); None if transparent or unknown."""
    text = (text or "").strip().lower()
    m = re.match(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", text)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$", text)
    if not m:
        return None
    if m.group(4) is not None and float(m.group(4).rstrip("%")) == 0:
        return None
    return tuple(round(float(m.group(i))) for i in (1, 2, 3))


def colour_warnings(facts, alarms):
    """Red or amber used as a category fill (DAG node, bar, chart mark, tag).

    `alarms` maps token names (--red, --amber, ...) to the page's values; a
    page without them is not checked.
    """
    refs = [(name, parse_colour(v)) for name, v in alarms.items() if parse_colour(v)]
    out = []
    for f in facts:
        c = parse_colour(f.get("colour"))
        if not c:
            continue
        for name, ref in refs:
            if sum((a - b) ** 2 for a, b in zip(c, ref)) ** 0.5 <= COLOUR_SLACK:
                out.append(f"{f['label']} is filled with {name}; red is for problems and amber "
                           "for callouts only, so use a series colour")
                break
    return counted(out)


def strip_warnings(facts):
    """Decorative side strips: a thick left border on a box with thin other sides."""
    out = []
    for f in facts:
        others = max(f.get("right", 0), f.get("top", 0), f.get("bottom", 0))
        if f.get("left", 0) >= STRIP_PX and f["left"] > others + 1:
            out.append(f"{f['label']} has a {f['left']:.0f}px left border, a decorative side strip; remove it")
    return counted(out)


def page_slices(total, step, limit=MAX_SLICES):
    """Split a page `total` px tall into viewport-height (y, height) bands."""
    total = max(int(total), 1)
    return [(y, min(step, total - y)) for y in range(0, total, step)][:limit]


def counted(messages):
    """Collapse repeats: ["a", "a", "b"] -> ["a (x2)", "b"]."""
    seen = {}
    for m in messages:
        seen[m] = seen.get(m, 0) + 1
    return [m if n == 1 else f"{m} (x{n})" for m, n in seen.items()]


def where(d):
    if d.get("line"):
        return f"diagram {d['n']} (line {d['line']})"
    return f"diagram {d['n']} (not in the HTML source; added by a script)"


def problems(result):
    """One readable line per reason behind the verdict."""
    out = []
    if result.get("blocked"):
        out.append(result["blocked"])
    if result.get("hung"):
        out.append(result["hung"])
    for d in result.get("diagrams", []):
        if d["status"] in DRAWN_BAD | NOT_DRAWN or d.get("env"):
            text = f"{where(d)}: {d.get('problem') or d['status']}"
            out.append(text + (f": {d['error']}" if d.get("error") else ""))
    for kind in ("charts", "dags"):
        for d in result.get(kind, []):
            if d["status"] in DRAWN_BAD | NOT_DRAWN:
                out.append(f"{kind[:-1]} {d['n']} ({d['label']}): {d.get('problem') or d['status']}")
    out += result.get("structure", [])
    out += result.get("layout", [])
    out += [r["why"] for r in result.get("requests", [])]
    out += [f"broken image: {src}" for src in result.get("broken_images", [])]
    out += [f"page error: {e}" for e in result.get("page_errors", [])]
    out += [f"console error: {e}" for e in result.get("console_errors", [])]
    if result.get("incomplete"):
        out.append(result["incomplete"])
    return out


# ---------------------------------------------------------------------------
# Browser side. Injected before any page script runs.

INIT_JS = r"""
(() => {
  if (window.__vrCheck) return;
  const vr = window.__vrCheck = { seen: new Map(), changed: 0, ids: 0 };
  const MERMAID = '.mermaid, [data-processed], [id^="mermaid"], [id^="dmermaid"], svg[aria-roledescription]';
  const visible = el => el.checkVisibility
    ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0;

  // Mermaid marks a block data-processed just before it swaps the block's
  // source for a drawing: keep that source, and whether the block was visible.
  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (name === 'data-processed' && !vr.seen.has(this)) {
      vr.seen.set(this, { html: this.innerHTML, text: this.textContent, hidden: !visible(this) });
    }
    return setAttribute.call(this, name, value);
  };

  // Time the last change to anything Mermaid draws, so the checker can wait
  // for drawing to stop rather than trust data-processed, which comes first.
  const touches = n => n.nodeType === 1 && (n.matches(MERMAID) || !!n.querySelector(MERMAID));
  new MutationObserver(records => {
    for (const r of records) {
      const t = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (r.type === 'attributes' || (t && t.closest(MERMAID))
          || [...r.addedNodes].some(touches) || [...r.removedNodes].some(touches)) {
        vr.changed = performance.now();
        return;
      }
    }
  }).observe(document, { subtree: true, childList: true, characterData: true,
                         attributes: true, attributeFilter: ['data-processed'] });

  // Every diagram on the page, in document order: Mermaid blocks, blocks
  // Mermaid processed under another selector, and stray Mermaid output.
  vr.containers = () => {
    const found = new Set([...vr.seen.keys()].filter(el => el.isConnected));
    document.querySelectorAll('.mermaid, [data-processed]').forEach(el => found.add(el));
    const known = el => [...found].some(c => c.contains(el));
    document.querySelectorAll('svg[aria-roledescription], div[id^="dmermaid"]').forEach(el => {
      if (!known(el)) found.add(el);
    });
    return [...found].sort((a, b) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  };
  const parts = el => {
    const svg = el.tagName.toLowerCase() === 'svg' ? el : el.querySelector('svg');
    const frame = svg ? null : el.querySelector('iframe');
    // Mermaid draws into a temporary div#d<id>; it is replaced on success but
    // left behind when drawing throws.
    const wrapper = !!(svg && svg.parentElement !== el && svg.parentElement
                       && svg.parentElement.id === 'd' + svg.id);
    return { svg, frame, wrapper };
  };
  const processed = el => vr.seen.has(el) || el.hasAttribute('data-processed');
  const marked = svg => svg.getAttribute('aria-roledescription') === 'error'
    || !!svg.querySelector('.error-icon, .error-text');
  vr.drawing = el => {
    if (!processed(el)) return false;
    const { svg, frame, wrapper } = parts(el);
    if (svg) return wrapper && !svg.getAttribute('aria-roledescription') && !marked(svg);
    if (frame) return !/^data:/.test(frame.getAttribute('src') || '');
    return true;
  };
  vr.settle = () => ({ drawing: vr.containers().filter(vr.drawing).length,
                       quiet: performance.now() - vr.changed });

  // The part of a box not cut off by overflow:hidden ancestors, and whether
  // some ancestor (scrolling or clipping) keeps it from widening the page.
  const visibleBox = node => {
    let { left, top, right, bottom } = node.getBoundingClientRect();
    let contained = false;
    for (let a = node.parentElement; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      const page = a === document.documentElement || a === document.body;
      if (!page && cs.overflowX !== 'visible') contained = true;
      const cx = /hidden|clip/.test(cs.overflowX), cy = /hidden|clip/.test(cs.overflowY);
      if (!cx && !cy) continue;
      if (page) {
        if (cx) right = Math.min(right, document.documentElement.clientWidth);
        continue;
      }
      const b = a.getBoundingClientRect();
      const x0 = b.left + a.clientLeft, y0 = b.top + a.clientTop;
      if (cx) { left = Math.max(left, x0); right = Math.min(right, x0 + a.clientWidth); }
      if (cy) { top = Math.max(top, y0); bottom = Math.min(bottom, y0 + a.clientHeight); }
    }
    return [Math.max(0, Math.round(right - left)), Math.max(0, Math.round(bottom - top)), contained];
  };
  // securityLevel "sandbox" puts the drawing in a data: URL iframe.
  const frameSvg = frame => {
    const m = /^data:text\/html[^,]*;base64,(.*)$/.exec(frame.getAttribute('src') || '');
    if (!m) return null;
    const bytes = Uint8Array.from(atob(m[1]), c => c.charCodeAt(0));
    return new DOMParser().parseFromString(new TextDecoder().decode(bytes), 'text/html')
      .querySelector('svg');
  };

  vr.facts = () => vr.containers().map(el => {
    if (!el.dataset.vrCheck) el.dataset.vrCheck = String(++vr.ids);
    const rec = vr.seen.get(el);
    const { svg, frame, wrapper } = parts(el);
    const raw = !svg && !frame;
    const f = {
      id: el.dataset.vrCheck, processed: processed(el), wrapper,
      holds: svg ? 'svg' : frame ? 'iframe' : (el.textContent.trim() ? 'text' : 'nothing'),
      source: rec ? rec.html : (raw ? el.innerHTML : null),
      text: rec ? rec.text : (raw ? el.textContent : null),
      hidden_when_drawn: rec ? rec.hidden : null, visible: visible(el),
      role: null, error_marks: false, width: 0, height: 0, natural_width: 0,
      natural_height: 0, labels: 0, shown_labels: 0, font_px: null, visible_width: 0,
      visible_height: 0, overflows_page: false,
    };
    const drawn = svg || (frame && frameSvg(frame));
    if (!drawn) return f;
    f.role = drawn.getAttribute('aria-roledescription');
    f.error_marks = marked(drawn);
    const vb = (drawn.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
    if (vb.length === 4) { f.natural_width = Math.round(vb[2]); f.natural_height = Math.round(vb[3]); }
    const box = svg || frame, r = box.getBoundingClientRect();
    f.width = Math.round(r.width);
    f.height = Math.round(r.height);
    let contained;
    [f.visible_width, f.visible_height, contained] = visibleBox(box);
    f.overflows_page = !contained && r.right > document.documentElement.clientWidth + 1;
    const labels = [...drawn.querySelectorAll('text, foreignObject')]
      .filter(l => l.textContent.trim());
    f.labels = labels.length;
    const shown = svg ? labels.filter(l => {
      const b = l.getBoundingClientRect();
      return b.width >= 1 && b.height >= 1;
    }) : labels;
    f.shown_labels = shown.length;
    const sizes = svg ? shown.map(l => parseFloat(getComputedStyle(l).fontSize))
      .filter(x => x > 0).sort((a, b) => a - b) : [];
    f.font_px = sizes.length ? sizes[sizes.length >> 1] : null;
    return f;
  });

  // Show every hidden container around a diagram, as a reader clicking
  // through tabs and toggles would; return how many were opened.
  vr.reveal = () => {
    let opened = 0;
    document.querySelectorAll('details:not([open])').forEach(d => { d.open = true; opened++; });
    const force = (a, prop, value) => { a.style.setProperty(prop, value, 'important'); opened++; };
    for (const el of vr.containers()) {
      for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
        if (a.hasAttribute('hidden')) { a.removeAttribute('hidden'); opened++; }
        let cs = getComputedStyle(a);
        if (cs.display === 'none') {
          force(a, 'display', 'revert');
          if (getComputedStyle(a).display === 'none') force(a, 'display', 'block');
        }
        cs = getComputedStyle(a);
        if (cs.contentVisibility === 'hidden') force(a, 'content-visibility', 'visible');
        if (cs.visibility !== 'visible') force(a, 'visibility', 'visible');
      }
      // A collapsed max-height:0 / overflow:hidden section.
      const h = el.getBoundingClientRect().height;
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (h > 2 && a.clientHeight < 2 && /hidden|clip/.test(cs.overflowY)
            && !/^(inline|contents)$/.test(cs.display)) {
          force(a, 'max-height', 'none');
          force(a, 'height', 'auto');
        }
      }
    }
    return opened;
  };

  vr.images = async () => {
    const broken = [], loading = [];
    for (const img of document.images) {
      if (!img.getAttribute('src') && !img.getAttribute('srcset')) continue;
      const src = img.currentSrc || img.src;
      if (!img.complete) { if (img.loading !== 'lazy') loading.push(src); continue; }
      if (img.naturalWidth) continue;
      try { await img.decode(); } catch (e) { broken.push(src); }
    }
    return { broken, loading };
  };

  // What mermaid.run() hands the parser: the block's innerHTML with entities
  // decoded (tags kept), dedented, trimmed, <br> normalised.
  const mermaidText = html => {
    const d = document.createElement('div');
    d.innerHTML = escape(html).replace(/%26/g, '&').replace(/%23/g, '#').replace(/%3B/g, ';');
    const lines = unescape(d.textContent).split('\n');
    const pad = l => l.match(/^[ \t]*/)[0].length;
    const indent = Math.min(...lines.filter(l => l.trim()).map(pad), 1e9);
    return lines.map(l => l.slice(Math.min(indent, pad(l)))).join('\n')
      .trim().replace(/<br\s*\/?>/gi, '<br/>');
  };
  // Parse, then draw in a visible offscreen box, with the page's own Mermaid.
  vr.probe = async (url, html, n) => {
    const msg = e => String((e && (e.message || e.str)) || e).slice(0, 500);
    let mermaid;
    try { mermaid = url ? (await import(url)).default : window.mermaid; }
    catch (e) { return { unavailable: msg(e) }; }
    if (!mermaid || !mermaid.parse) return { unavailable: 'no Mermaid module' };
    const text = mermaidText(html);
    try { await mermaid.parse(text); } catch (e) { return { parse_error: msg(e) }; }
    if (!mermaid.render) return { unavailable: 'no mermaid.render' };
    const box = document.createElement('div');
    box.style.cssText = 'position:absolute;left:-20000px;top:0;width:1000px;display:block;visibility:visible';
    document.body.appendChild(box);
    try {
      const out = await mermaid.render('vrcheck-' + n, text, box);
      box.innerHTML = typeof out === 'string' ? out : (out && out.svg) || '';
      const svg = box.querySelector('svg');
      if (!svg) return { unavailable: 'render returned no svg' };
      if (marked(svg)) return { draw_error: 'an error diagram, with no message' };
      const r = svg.getBoundingClientRect();
      const vb = (svg.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
      return { width: Math.round(r.width), height: Math.round(r.height),
               natural_width: Math.round(vb[2] || 0), natural_height: Math.round(vb[3] || 0) };
    } catch (e) {
      return { draw_error: msg(e) };
    } finally {
      box.remove();
      const temp = document.getElementById('dvrcheck-' + n);
      if (temp) temp.remove();
    }
  };

  // ---- Dossier facts: Vega charts, static-SVG DAGs, layout, colour. ----
  const figLabel = el => {
    for (let a = el; a; a = a.parentElement) {
      const m = /^(?:fig-(\d+)|table-(\d+)-fig)$/.exec(a.id || '');
      if (m) return m[1] ? 'Figure ' + m[1] : 'Table ' + m[2];
    }
    return null;
  };
  const describe = el => figLabel(el) || (el.id ? '#' + el.id
    : el.tagName.toLowerCase() + (el.classList.length ? '.' + [...el.classList].join('.') : ''));
  const median = xs => { xs = xs.filter(x => x > 0).sort((a, b) => a - b); return xs.length ? xs[xs.length >> 1] : null; };

  vr.vegaWait = async ms => {
    if (!window.__vegaDone) return { present: false };
    let timer;
    try {
      await Promise.race([window.__vegaDone, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`window.__vegaDone did not settle within ${ms} ms`)), ms); })]);
      return { present: true };
    } catch (e) {
      return { present: true, error: String((e && e.message) || e).slice(0, 300) };
    } finally { clearTimeout(timer); }
  };

  vr.charts = () => [...document.querySelectorAll('.chart')].map((el, i) => {
    el.dataset.vrChart = String(i + 1);
    const svg = el.querySelector('svg.marks') || el.querySelector('svg');
    const r = (svg || el).getBoundingClientRect();
    return { label: describe(el), visible: visible(el), svg: !!svg,
             marks: svg ? svg.querySelectorAll('g.role-mark path, g.role-mark line, g.role-mark rect, g.role-mark text, g.role-mark circle').length : 0,
             width: Math.round(r.width), height: Math.round(r.height) };
  });

  vr.dags = () => [...document.querySelectorAll('svg.dag')].map((svg, i) => {
    svg.dataset.vrDag = String(i + 1);
    const r = svg.getBoundingClientRect();
    const vb = (svg.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
    const f = { label: describe(svg) + (svg.classList.contains('dag-tb') ? ' (TB)' : svg.classList.contains('dag-lr') ? ' (LR)' : ''),
                visible: visible(svg) && r.width > 0, width: Math.round(r.width), height: Math.round(r.height),
                natural_width: vb.length === 4 ? Math.round(vb[2]) : 0, font_px: null, spills: [],
                visible_width: 0, visible_height: 0 };
    if (!f.visible) return f;
    [f.visible_width, f.visible_height] = visibleBox(svg);
    f.font_px = median([...svg.querySelectorAll('text.nm')].map(t => parseFloat(getComputedStyle(t).fontSize)));
    for (const g of svg.querySelectorAll('g.dn')) {
      const box = g.querySelector('rect.box');
      if (!box) continue;
      const b = box.getBBox();
      for (const t of g.querySelectorAll('text')) {
        const tb = t.getBBox();
        if (tb.width && (tb.x < b.x - 1 || tb.x + tb.width > b.x + b.width + 1)) {
          f.spills.push(t.textContent.trim().slice(0, 60));
        }
      }
    }
    return f;
  });

  // Overflow and rendered text size at the current viewport width.
  vr.layout = () => {
    const out = [], de = document.documentElement, worst = new Map();
    if (de.scrollWidth > de.clientWidth + 1) out.push({ kind: 'page', label: 'the page', excess: de.scrollWidth - de.clientWidth });
    for (const el of document.querySelectorAll('.figframe, .dag-frame, table, pre.code')) {
      if (!visible(el) || el.closest('details:not([open])')) continue;
      // A table past its parent's border: out of the frame, not just into its padding.
      const p = el.parentElement, pr = p.getBoundingClientRect(), r = el.getBoundingClientRect();
      const spill = r.right - (pr.right - parseFloat(getComputedStyle(p).borderRightWidth));
      const excess = Math.round(Math.max(el.scrollWidth - el.clientWidth, el.tagName === 'TABLE' ? spill : 0));
      if (excess <= 0) continue;
      const kind = el.matches('pre.code') ? 'code' : 'frame', key = kind + describe(el);
      if (!worst.has(key) || worst.get(key).excess < excess) worst.set(key, { kind, label: describe(el), excess });
    }
    out.push(...worst.values());
    for (const svg of document.querySelectorAll('svg.dag')) {
      const r = svg.getBoundingClientRect();
      const vb = (svg.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
      const font = median([...svg.querySelectorAll('text.nm')].map(t => parseFloat(getComputedStyle(t).fontSize)));
      if (visible(svg) && r.width > 0 && vb[2] && font) out.push({ kind: 'text', label: describe(svg) + ' DAG', px: Math.round(font * r.width / vb[2] * 10) / 10 });
    }
    return out;
  };

  // Fills of category marks: DAG nodes and tags, bars, legend keys, chart marks.
  vr.colours = tokens => {
    const root = getComputedStyle(document.documentElement);
    const alarms = {};
    for (const t of tokens) { const v = root.getPropertyValue(t).trim(); if (v) alarms[t] = v; }
    const facts = [];
    const sel = 'svg.dag rect, svg.dag path.box, .bar-fill, td.bar, .cbar, .tgk, .legend .k > span, .chart svg g.role-mark > *';
    const clear = c => !c || c === 'transparent' || /^rgba\(.*,\s*0\)$/.test(c);
    for (const el of document.querySelectorAll(sel)) {
      if (el.closest('.callout, .problem, .diff')) continue;
      const cs = getComputedStyle(el);
      let colour = el instanceof SVGElement ? cs.fill : cs.backgroundColor;
      // an in-cell bar (td.bar .cbar) paints its fill on ::before
      if (!(el instanceof SVGElement) && clear(colour)) colour = getComputedStyle(el, '::before').backgroundColor;
      facts.push({ label: describe(el) + ' ' + (el.classList[0] || el.tagName.toLowerCase()), colour });
    }
    return { alarms, facts };
  };

  // Boxes with a thick left border only: decorative side strips.
  vr.strips = () => {
    const out = [];
    for (const el of document.querySelectorAll('main *, .content *, body > section *')) {
      if (el.closest('pre, table, svg')) continue;
      const cs = getComputedStyle(el);
      if (cs.borderLeftStyle === 'none' || /rgba\(0, 0, 0, 0\)|transparent/.test(cs.borderLeftColor)) continue;
      const w = s => cs[`border${s}Style`] === 'none' ? 0 : parseFloat(cs[`border${s}Width`]) || 0;
      const f = { label: describe(el), left: w('Left'), right: w('Right'), top: w('Top'), bottom: w('Bottom') };
      if (f.left >= 3) out.push(f);
    }
    return out;
  };

  vr.forcedCaps = () => [...document.querySelectorAll('h2.sec-head, h2')]
    .filter(h => getComputedStyle(h).textTransform === 'uppercase').length;
})();
"""


class Hung(Exception):
    """The page stopped answering: a script is hogging its main thread."""


class Page:
    """Page queries that cannot hang the check on a frozen tab."""

    def __init__(self, page, cdp, result):
        self.page, self.cdp, self.result = page, cdp, result

    async def call(self, js, arg=None, timeout=CALL_TIMEOUT_S):
        for attempt in (1, 2):
            try:
                return await asyncio.wait_for(self.page.evaluate(js, arg), timeout)
            except asyncio.TimeoutError:
                self.result["hung"] = (
                    f"the page stopped responding: a script kept its main thread busy "
                    f"for over {CALL_TIMEOUT_S} s, which freezes a reader's tab")
                if attempt == 2:
                    raise Hung() from None
                try:  # stop the runaway script so the rest of the page can be checked
                    await asyncio.wait_for(self.cdp.send("Runtime.terminateExecution"), 3)
                except Exception:
                    pass


class Net:
    """The page's own network traffic, until the checker starts making its own."""

    def __init__(self):
        self.frozen = False
        self.inflight = {}
        self.failed = []     # (url, failure, status)
        self.reached = False  # some remote server answered
        self.scripts = []    # script URLs that loaded

    def attach(self, page):
        page.on("request", self._request)
        page.on("response", self._response)
        page.on("requestfinished", self._done)
        page.on("requestfailed", self._failed)
        return self

    def _request(self, req):
        if not self.frozen:
            self.inflight[req] = req.url

    def _response(self, resp):
        if self.frozen:
            return
        if resp.url.startswith("http"):
            self.reached = True
        if resp.status >= 400:
            self.failed.append((resp.request.url, None, resp.status))
        elif resp.request.resource_type == "script":
            self.scripts.append(resp.request.url)

    def _done(self, req):
        self.inflight.pop(req, None)

    def _failed(self, req):
        self.inflight.pop(req, None)
        if self.frozen:
            return
        if req.failure == "net::ERR_BLOCKED_BY_ORB":
            self.reached = True
        self.failed.append((req.url, req.failure, None))


async def launch(pw):
    """Prefer Playwright's Chromium; fall back to an installed Chrome."""
    errors = []
    for kwargs in ({}, {"channel": "chrome"}):
        try:
            return await pw.chromium.launch(**kwargs), None
        except Exception as exc:  # executable missing, sandbox refusal, ...
            errors.append(str(exc).splitlines()[0])
    return None, "; ".join(errors)


async def settle(q, budget, quiet_ms, since):
    """Wait until no diagram is mid-draw and Mermaid's output has stopped changing."""
    end = time.monotonic() + budget
    while True:
        s = await q.call("() => window.__vrCheck.settle()")
        calm = s["quiet"] >= quiet_ms and (time.monotonic() - since) * 1000 >= quiet_ms
        if s["drawing"] == 0 and calm:
            return True
        if time.monotonic() >= end:
            return False
        await asyncio.sleep(0.25)


SHOT_NAME = re.compile(r"(?:page|diagram|chart|dag)-\d+\.png")


def stale_shots(shots):
    """Earlier shots in the folder, matched by the exact names this script writes."""
    return [p for p in shots.iterdir() if p.is_file() and SHOT_NAME.fullmatch(p.name)]


async def screenshots(page, q, shots, diagrams, result):
    """Page slices and one shot per diagram; earlier shots are removed first."""
    shots.mkdir(parents=True, exist_ok=True)
    for old in stale_shots(shots):
        old.unlink()
    height = await q.call("() => document.documentElement.scrollHeight")
    bands = page_slices(height, VIEWPORT["height"])
    if len(bands) * VIEWPORT["height"] < height:
        result["warnings"].append(f"page screenshots stop at {len(bands)} slices")
    for k, (y, h) in enumerate(bands, 1):
        path = shots / f"page-{k}.png"
        clip = {"x": 0, "y": y, "width": VIEWPORT["width"], "height": h}
        try:
            await asyncio.wait_for(page.screenshot(path=str(path), full_page=True, clip=clip,
                                                   timeout=10000), 15)
            result["screenshots"].append(str(path))
        except Exception as exc:
            result["warnings"].append(f"page slice {k}: no screenshot ({first_line(exc)})")
            break
    for d in diagrams:
        if d["status"] in ("hidden", "lazy") or not d.get("_shootable"):
            continue
        path = shots / f"diagram-{d['n']}.png"
        try:
            loc = page.locator(f"[data-vr-check='{d['_id']}']")
            await asyncio.wait_for(loc.screenshot(path=str(path), timeout=3000), 6)
            result["screenshots"].append(str(path))
        except Exception as exc:
            result["warnings"].append(f"{where(d)}: no screenshot ({first_line(exc)})")
    for kind, attr in (("chart", "data-vr-chart"), ("dag", "data-vr-dag")):
        for d in result.get(kind + "s", []):
            if d["status"] == "hidden":
                continue
            path = shots / f"{kind}-{d['n']}.png"
            try:
                loc = page.locator(f"[{attr}='{d['n']}']")
                await asyncio.wait_for(loc.screenshot(path=str(path), timeout=3000), 6)
                result["screenshots"].append(str(path))
            except Exception as exc:
                result["warnings"].append(f"{kind} {d['n']} ({d['label']}): no screenshot ({first_line(exc)})")


async def dossier_facts(page, q, timeout, result):
    """Vega charts, static-SVG DAGs, colour and side-strip facts at the main viewport."""
    vega = await q.call("(ms) => window.__vrCheck.vegaWait(ms)", timeout * 1000, timeout=timeout + 5)
    charts = await q.call("() => window.__vrCheck.charts()")
    if charts and not vega["present"]:
        result["warnings"].append("the page has .chart elements but sets no window.__vegaDone; "
                                  "charts were read without waiting for vegaEmbed")
    for n, f in enumerate(charts, 1):
        if vega.get("error") and not f["svg"]:
            f["error"] = vega["error"]
        status, problem = chart_status(f)
        d = {"n": n, "label": f["label"], "status": status, "size": f"{f['width']}x{f['height']}"}
        if problem:
            d["problem"] = problem
        result["charts"].append(d)
    for n, f in enumerate(await q.call("() => window.__vrCheck.dags()"), 1):
        status, problem, warning = dag_status(f)
        d = {"n": n, "label": f["label"], "status": status, "size": f"{f['width']}x{f['height']}"}
        if problem:
            d["problem"] = problem
        if warning:
            result["warnings"].append(f"dag {n} ({f['label']}): {warning}")
        result["dags"].append(d)
    found = await q.call("(t) => window.__vrCheck.colours(t)", list(ALARM_TOKENS))
    result["warnings"] += colour_warnings(found["facts"], found["alarms"])
    result["warnings"] += strip_warnings(await q.call("() => window.__vrCheck.strips()"))
    if await q.call("() => window.__vrCheck.forcedCaps()"):
        result["warnings"].append("h2 headings are forced to capitals with text-transform: "
                                  "uppercase; headings are sentence case")


async def viewport_pass(browser, report, q, timeout, result):
    """Overflow and small text at the main width (already-loaded page) and at
    each of VIEWPORTS. Each extra width gets a fresh page loaded at that width,
    not a resize: pages size things at load time (Mermaid's wrap setting reads
    window.innerWidth), so a resized page measures what no reader sees."""
    facts = [dict(f, viewport=VIEWPORT["width"])
             for f in await q.call("() => window.__vrCheck.layout()")
             if f["kind"] != "text"]   # main-width DAG text is judged by dag_status
    for width in VIEWPORTS:
        page = await browser.new_page(viewport={"width": width, "height": VIEWPORT["height"]})
        try:
            await page.add_init_script(INIT_JS)
            await page.goto(report.as_uri(), wait_until="load", timeout=LOAD_TIMEOUT_S * 1000)
            vq = Page(page, await page.context.new_cdp_session(page), {})
            await settle(vq, min(timeout, 10), QUIET_MS, time.monotonic())
            await vq.call("(ms) => window.__vrCheck.vegaWait(ms)", 5000, timeout=8)
            if await vq.call("() => window.__vrCheck.reveal()"):
                await asyncio.sleep(0.3)
                await settle(vq, 5, 500, time.monotonic())
            facts += [dict(f, viewport=width) for f in await vq.call("() => window.__vrCheck.layout()")]
            for n, f in enumerate(await vq.call("() => window.__vrCheck.facts()"), 1):
                px = label_px(f) if f["visible"] and f["holds"] == "svg" else None
                if px is not None:
                    facts.append({"viewport": width, "kind": "text", "label": f"diagram {n}",
                                  "px": round(px, 1)})
        except Exception as exc:
            result["warnings"].append(f"the {width}px pass did not finish ({first_line(exc)})")
        finally:
            await page.close()
    problems, warnings = viewport_findings(facts)
    result["layout"] += problems
    result["warnings"] += warnings


def ignored(msg):
    """Console messages that are not page defects."""
    return (msg.type != "error"  # warnings are noise: the Tailwind CDN always warns
            # A failed resource is judged from the request itself.
            or msg.text.startswith("Failed to load resource")
            # The checker's own instrumentation, refused by a sandboxed iframe
            # (Mermaid's securityLevel "sandbox"); a plain browser logs nothing.
            or msg.text.startswith("Blocked script execution in"))


def first_line(exc):
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0][:200]


async def inspect(pw, report, shots, timeout, result):
    browser, err = await launch(pw)
    if browser is None:
        result["blocked"] = f"no browser could launch ({err}); install one with `{INSTALL_HINT}`"
        return
    try:
        await inspect_page(browser, report, shots, timeout, result)
    except Hung:
        pass  # result["hung"] says why; nothing more can be read from the page
    finally:
        try:
            await asyncio.wait_for(browser.close(), 10)
        except Exception:
            pass


async def inspect_page(browser, report, shots, timeout, result):
    page = await browser.new_page(viewport=VIEWPORT)
    cdp = await page.context.new_cdp_session(page)
    q = Page(page, cdp, result)
    net = Net().attach(page)
    page_errors, console_errors = [], []
    page.on("pageerror", lambda exc: None if net.frozen else page_errors.append(str(exc)[:400]))
    page.on("console", lambda msg: None if net.frozen or ignored(msg)
            else console_errors.append(msg.text[:400]))
    await page.add_init_script(INIT_JS)

    pending = []
    try:
        await page.goto(report.as_uri(), wait_until="load", timeout=LOAD_TIMEOUT_S * 1000)
    except Exception as exc:
        if "Timeout" not in type(exc).__name__:
            raise
        pending = list(net.inflight.values())
    loaded_at = time.monotonic()

    if not await settle(q, timeout, QUIET_MS, loaded_at):
        result["warnings"].append(f"diagrams were still changing after {timeout} s; checked as they were")
    before = {f["id"]: f for f in await q.call("() => window.__vrCheck.facts()")}
    if await q.call("() => window.__vrCheck.reveal()"):  # diagrams get "revealed": true
        await asyncio.sleep(0.3)
        await settle(q, 5, 500, time.monotonic())
    facts = await q.call("() => window.__vrCheck.facts()")

    for n, f in enumerate(facts, 1):
        f["hidden_at_settle"] = f["id"] in before and not before[f["id"]]["visible"]
        status, problem = diagram_status(f)
        d = {"n": n, "status": status, "type": f["role"], "size": f"{f['width']}x{f['height']}",
             "_id": f["id"], "_shootable": f["visible"] and f["width"] > 0 or f["holds"] == "text",
             "source": f["source"], "text": f["text"], "hidden_when_drawn": f["hidden_when_drawn"],
             "_natural": (f["natural_width"], f["natural_height"])}
        scale = scale_of(f)
        if scale is not None and status not in ("error", "empty"):
            d["scale"] = scale
        if f["hidden_at_settle"]:
            d["revealed"] = True
        if problem:
            d["problem"] = problem
        px = label_px(f)
        if status == "ok" and px is not None and px < SMALL_LABEL_PX:
            result["warnings"].append(f"diagram {n} is shrunk to {scale:.0%} of its natural "
                                      f"size; its labels are about {px:.0f}px tall")
        if status == "ok" and f["overflows_page"]:
            result["warnings"].append(f"diagram {n} runs past the window's right edge; the page scrolls sideways")
        if status == "hidden":
            d["unverified"] = "still hidden after the checker opened its containers"
        result["diagrams"].append(d)

    await dossier_facts(page, q, timeout, result)
    images = await q.call("() => window.__vrCheck.images()")
    scripts = await q.call("() => [...document.querySelectorAll('script[type=module]')].map(s => s.textContent)")
    await screenshots(page, q, shots, result["diagrams"], result)

    # From here on the checker makes its own requests; they do not count.
    net.frozen = True
    module = mermaid_module(import_urls(scripts), net.scripts)
    probes = [d for d in result["diagrams"] if d.get("source") and (
        d["status"] in ("error", "empty", "lazy")
        or d["status"] == "ok" and d["hidden_when_drawn"])][:MAX_PROBES]
    for d in probes:
        try:
            out = await asyncio.wait_for(page.evaluate(
                "([u, h, n]) => window.__vrCheck.probe(u, h, n)", [module, d["source"], d["n"]]),
                PROBE_TIMEOUT_S)
        except Exception:
            out = None
        explain(d, out)
        if d.get("warning"):
            result["warnings"].append(f"diagram {d['n']}: {d.pop('warning')}")
    await viewport_pass(browser, report, q, timeout, result)

    # Nothing remote answered, yet some host was unreachable: a typo in the
    # page, or no network at all? Ask a known-good host to tell them apart.
    network_ok = net.reached
    unreachable = any(f and f not in ("net::ERR_ABORTED", "net::ERR_BLOCKED_BY_ORB")
                      for _, f, _ in net.failed)
    if not network_ok and (unreachable or pending):
        try:
            network_ok = await asyncio.wait_for(page.evaluate(
                """async (url) => { const c = new AbortController(); setTimeout(() => c.abort(), 5000);
                   try { await fetch(url, { mode: 'no-cors', cache: 'no-store', signal: c.signal }); return true; }
                   catch (e) { return false; } }""", NETWORK_PROBE_URL), 8)
        except Exception:
            network_ok = False
    for url, failure, status in net.failed:
        found = request_problem(url, failure, status, network_ok)
        if found:
            result["requests"].append({"url": url, "kind": found[0], "why": found[1]})
    for url in pending:
        found = request_problem(url, f"still loading after {LOAD_TIMEOUT_S} s", None, network_ok)
        if found:
            why = found[1] + "; the page's load event waits on it, and Mermaid renders on load"
            result["requests"].append({"url": url, "kind": found[0], "why": why})
    blocked_urls = {r["url"] for r in result["requests"] if r["kind"] == "blocked"}
    result["broken_images"] = [src[:200] for src in images["broken"] if src not in blocked_urls]
    if images["loading"]:
        result["warnings"].append(f"{len(images['loading'])} image(s) still loading when checked")
    if net.inflight and not pending:
        result["warnings"].append(f"{len(net.inflight)} request(s) still pending when checked")
    if module and not result["diagrams"]:
        result["warnings"].append("the page loads Mermaid, but no diagram appeared")
    result["page_errors"] = counted(page_errors)
    result["console_errors"] = counted(console_errors)


# ---------------------------------------------------------------------------

_emitted = threading.Lock()


def emit(result, html, hard=False):
    if not _emitted.acquire(blocking=False):
        return
    assign_lines(result["diagrams"], html)
    unverified = [f"{where(d)}: {d['unverified']}" for d in result["diagrams"] if d.get("unverified")]
    for d in result["diagrams"]:
        for k in [k for k in d if k.startswith("_") or k in ("source", "text", "hidden_when_drawn", "unverified")]:
            del d[k]
    result["unverified"] = result.get("unverified", []) + unverified
    result["verdict"] = verdict(result)
    result["problems"] = problems(result) if result["verdict"] != PASS else []
    result["review"] = REVIEW
    print(json.dumps(result, indent=1))
    print(result["verdict"], flush=True)
    if hard:
        os._exit(EXIT[result["verdict"]])
    sys.exit(EXIT[result["verdict"]])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", help="the report HTML file")
    ap.add_argument("--shots", help="screenshot directory")
    ap.add_argument("--timeout", type=int, default=20,
                    help="seconds to wait for Mermaid and Vega after load (default 20)")
    ap.add_argument("--scaffold", default=str(SCAFFOLD),
                    help="scaffold whose locked block the page must match (default: the skill's "
                         "assets/scaffold.html)")
    args = ap.parse_args()

    report = Path(args.report).resolve()
    shots = Path(args.shots) if args.shots else report.with_name(report.stem + "-check")
    result = {"report": str(report), "structure": [], "diagrams": [], "charts": [], "dags": [],
              "layout": [], "requests": [], "broken_images": [],
              "page_errors": [], "console_errors": [], "hung": None, "blocked": None,
              "incomplete": None, "warnings": [], "unverified": [], "screenshots": []}
    try:
        html = read_source(report)
    except OSError as exc:
        result["page_errors"].append(f"cannot read the report: {exc}")
        emit(result, "")
    try:
        scaffold = read_source(args.scaffold)
    except OSError:
        scaffold = None
    found, warned, unverified = source_checks(html, scaffold, args.scaffold)
    result["structure"] += found
    result["warnings"] += warned
    result["unverified"] += unverified

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["blocked"] = (
            "playwright is not importable; run this script with "
            "`uv run --no-project --with playwright python` or install it "
            "with `pip install playwright`"
        )
        emit(result, html)

    limit = LOAD_TIMEOUT_S + 2 * args.timeout + 110   # Mermaid settle, Vega wait, viewport pass

    def give_up():  # last resort if even cancelling the check hangs
        result["incomplete"] = f"the check was stopped after {limit + 20} s"
        emit(result, html, hard=True)
    watchdog = threading.Timer(limit + 20, give_up)
    watchdog.daemon = True
    watchdog.start()

    async def run():
        async with async_playwright() as pw:
            await asyncio.wait_for(inspect(pw, report, shots, args.timeout, result), limit)
    try:
        asyncio.run(run())
    except asyncio.TimeoutError:
        result["incomplete"] = f"the check did not finish within {limit} s"
    except Exception as exc:
        result["blocked"] = f"the check itself failed: {type(exc).__name__}: {first_line(exc)}"
    emit(result, html)


if __name__ == "__main__":
    main()
