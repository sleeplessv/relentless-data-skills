#!/usr/bin/env python3
"""Render a visual-report HTML file in headless Chromium and check what a reader sees.

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
diagrams opened, and diagram-<n>.png per diagram. Read them to judge
legibility and the hand-built CSS/SVG visuals; the script cannot.

Usage:
  uv run --no-project --with playwright python check_render.py REPORT.html [--shots DIR]
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

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
EXIT = {PASS: 0, FAIL: 1, BLOCKED: 2}
VIEWPORT = {"width": 1280, "height": 900}
LOAD_TIMEOUT_S = 30   # for the page's load event; Mermaid's startOnLoad waits for it
QUIET_MS = 2000       # Mermaid's output must sit unchanged this long before it is read
CALL_TIMEOUT_S = 10   # a page that cannot answer a query this fast has a frozen tab
PROBE_TIMEOUT_S = 15  # one offscreen re-render of a diagram's source
MIN_LABEL_PX = 6      # labels shrunk below this are unreadable: FAIL
SMALL_LABEL_PX = 9    # below this, warn that the diagram is shrunk to fit
TINY_PX = 24          # a diagram rendered narrower or shorter than this is a speck
CLIP_SLACK_PX = 2
MAX_SLICES = 40
MAX_PROBES = 20
# Hosts the skill's scaffold loads from. A network failure on one of these is
# the environment's fault; on any other host it is a bad URL in the page.
CDN_HOSTS = {"cdn.tailwindcss.com", "cdn.jsdelivr.net", "fastly.jsdelivr.net",
             "unpkg.com", "esm.sh", "cdnjs.cloudflare.com"}
NETWORK_PROBE_URL = "https://cdn.jsdelivr.net/npm/mermaid@11/package.json"
INSTALL_HINT = "uv run --no-project --with playwright playwright install chromium"
# Statuses for which Mermaid ran and drew something wrong: proof of a defect.
DRAWN_BAD = {"error", "empty", "illegible", "clipped"}
# Statuses for which nothing was drawn: a defect, unless the network is to blame.
NOT_DRAWN = {"unrendered", "rendering"}
# Elements whose content never becomes live page elements.
INERT = {"template", "noscript", "textarea", "title", "xmp", "iframe",
         "noembed", "noframes"}
FETCH_FAILED = re.compile(
    r"Failed to fetch dynamically imported module|error loading dynamically "
    r"imported module|Importing a module script failed", re.I)


# ---------------------------------------------------------------------------
# Pure logic: no Playwright needed (tests/test_visual_report.py covers it).

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


def source_key(text):
    return " ".join((text or "").split())


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
    unused = [(source_key(b["source"]), b["line"]) for b in mermaid_blocks(html)]
    lines = html.splitlines()
    for d in diagrams:
        d["line"] = None
        if d.get("text") is None:
            continue
        key = source_key(d["text"])
        for i, (k, line) in enumerate(unused):
            if k == key:
                d["line"] = line
                del unused[i]
                break
        else:
            d["line"] = locate(d["text"], lines)


IMPORT = re.compile(r"""import\s+mermaid\s+from\s+["']([^"']+)["']""")
MERMAID_ENTRY = re.compile(r"/mermaid(?:\.esm)?(?:\.min)?\.m?js$")


def import_urls(script_texts):
    """Mermaid import URLs in the page's module scripts, ignoring commented-out ones."""
    urls = []
    for text in script_texts:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(?m)^\s*//.*$", "", text)
        urls += IMPORT.findall(text)
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
    so those count only when the network was fine.
    """
    if result.get("blocked"):
        return BLOCKED
    diagrams = result.get("diagrams", [])
    requests = result.get("requests", [])
    if (any(d["status"] in DRAWN_BAD and not d.get("env") for d in diagrams)
            or any(r["kind"] == "defect" for r in requests)
            or result.get("broken_images") or result.get("hung")):
        return FAIL
    if (any(r["kind"] == "blocked" for r in requests)
            or any(d.get("env") for d in diagrams) or result.get("incomplete")):
        return BLOCKED
    if (any(d["status"] in NOT_DRAWN for d in diagrams)
            or result.get("page_errors") or result.get("console_errors")):
        return FAIL
    return PASS


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


async def screenshots(page, q, shots, diagrams, result):
    """Page slices and one shot per diagram; earlier shots are removed first."""
    shots.mkdir(parents=True, exist_ok=True)
    for old in [*shots.glob("page*.png"), *shots.glob("diagram-*.png")]:
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
    result["unverified"] = unverified
    result["verdict"] = verdict(result)
    result["problems"] = problems(result) if result["verdict"] != PASS else []
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
                    help="seconds to wait for Mermaid after load (default 20)")
    args = ap.parse_args()

    report = Path(args.report).resolve()
    shots = Path(args.shots) if args.shots else report.with_name(report.stem + "-check")
    result = {"report": str(report), "diagrams": [], "requests": [], "broken_images": [],
              "page_errors": [], "console_errors": [], "hung": None, "blocked": None,
              "incomplete": None, "warnings": [], "screenshots": []}
    try:
        html = read_source(report)
    except OSError as exc:
        result["page_errors"].append(f"cannot read the report: {exc}")
        emit(result, "")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["blocked"] = (
            "playwright is not importable; run this script with "
            "`uv run --no-project --with playwright python` or install it "
            "with `pip install playwright`"
        )
        emit(result, html)

    limit = LOAD_TIMEOUT_S + args.timeout + 90

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
