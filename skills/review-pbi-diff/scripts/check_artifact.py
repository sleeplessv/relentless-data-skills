#!/usr/bin/env python3
"""Check a review artifact against the change model it was built from.

Reads the artifact's check markers (see references/artifact.md) the way a
browser builds the page, counting only static markup a reader sees, and
compares them with change_model.json:

  - every added/modified measure has exactly one verdict card, the card shows
    the measure's name, and its one data-badge shows its verdict's badge alone
  - every touched curated page has one wireframe under a heading naming the
    page, no other page has one, and each wireframe draws every non-group
    visual on its page with the change model's status
  - each of the seven stat chips appears once, names its stat, and shows the
    change model's number
  - every red-flag card is its own <article> inside data-flags, its one
    data-badge shows its severity's badge alone, and no unmarked card shows one
  - the exclusion line names every page the check treats as scratch

Prints JSON (the counts to report, every excluded page with its reason, and
every problem), then PASS or FAIL. Exit codes: 0 PASS, 1 FAIL.

Usage:
  python3 check_artifact.py CHANGE_MODEL.json ARTIFACT.html [--scratch PAGE ...]

--scratch takes a page display name or page id the user named as scratch at
invocation, or REPORT/PAGE to pick one report's page; case is ignored. Pages
the extractor marked `scratch` need no flag. Stdlib only.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from html import unescape
from html.parser import HTMLParser

VERDICT_BADGES = {"match": "✅", "deviates": "⚠", "none": "❓"}
SEVERITY_BADGES = {"red": "🔴", "yellow": "🟡", "blue": "🔵"}
STATS = ("pages_added", "visuals_added", "visuals_modified", "visuals_deleted",
         "measures_added", "measures_modified", "relationships_added")
ADDED, MODIFIED, DELETED = ("added", "new"), ("modified", "changed", "updated"), ("deleted", "removed")
STAT_WORDS = {  # a chip's label must hold the noun and one of the verbs
    "pages_added": ("page", ADDED), "visuals_added": ("visual", ADDED),
    "visuals_modified": ("visual", MODIFIED), "visuals_deleted": ("visual", DELETED),
    "measures_added": ("measure", ADDED), "measures_modified": ("measure", MODIFIED),
    "relationships_added": ("relationship", ADDED),
}
MARKERS = ("data-stat", "data-measure", "data-severity", "data-badge", "data-flags",
           "data-wireframe", "data-visual", "data-excluded")


def _words(s):
    return frozenset(s.split())


# Enough of the HTML tree-construction rules to put text where a browser does.
VOID = _words("area base br col embed hr img input keygen link meta param source track wbr")
RAW = _words("script style title textarea xmp iframe noembed noframes noscript plaintext")
INLINE = _words("a abbr b bdi bdo big cite code data del dfn em font i ins kbd label mark "
                "nobr q s samp small span strike strong time tt u var wbr")
FORMATTING = _words("a b big code em font i nobr s small strike strong tt u")
SPECIAL = _words(
    "address applet area article aside base basefont bgsound blockquote body br button "
    "caption center col colgroup dd details dialog dir div dl dt embed fieldset figcaption "
    "figure footer form frame frameset h1 h2 h3 h4 h5 h6 head header hgroup hr html iframe "
    "img input keygen li link listing main marquee menu meta nav noembed noframes noscript "
    "object ol p param plaintext pre script search section select source style summary "
    "table tbody td template textarea tfoot th thead title tr track ul wbr xmp "
    "foreignobject desc mi mo mn ms mtext annotation-xml")
CLOSES_P = _words(
    "address article aside blockquote center details dialog dir div dl fieldset figcaption "
    "figure footer form header hgroup hr h1 h2 h3 h4 h5 h6 li dd dt listing main menu nav "
    "ol p plaintext pre search section summary table ul xmp")
HEADINGS = _words("h1 h2 h3 h4 h5 h6")
SCOPE = _words("applet caption html table td th marquee object template "
               "foreignobject desc title mi mo mn ms mtext annotation-xml")
TABLE_SCOPE = _words("html table template")
BREAKOUT = _words("b big blockquote body br center code dd div dl dt em embed h1 h2 h3 h4 h5 "
                  "h6 head hr i img li listing menu meta nobr ol p pre ruby s small span "
                  "strong strike sub sup table tt u ul var")


def declarations(style):
    out = {}
    for part in (style or "").split(";"):
        prop, sep, value = part.partition(":")
        if sep:
            out[prop.strip().lower()] = value.replace("!important", "").strip().lower()
    return out


def is_zero(value):
    try:
        return value is not None and float(value.rstrip("%")) == 0
    except ValueError:
        return False


def hiding_reason(tag, attrs, ns, style):
    """Why this element and everything in it never reaches a reader, if so."""
    svg = ns != "html"
    if "hidden" in attrs:
        return "hidden attribute"
    if (attrs.get("aria-hidden") or "").strip().lower() == "true":
        return 'aria-hidden="true"'
    if style.get("display") == "none" or (svg and attrs.get("display") == "none"):
        return "display:none"
    if is_zero(style.get("opacity")) or (svg and is_zero(attrs.get("opacity"))):
        return "opacity:0"
    if style.get("content-visibility") == "hidden":
        return "content-visibility:hidden"
    if tag == "dialog" and "open" not in attrs:
        return "closed <dialog>"
    if tag in RAW or tag in ("template", "datalist"):
        return f"<{tag}>"
    return None


class Page(HTMLParser):
    """Build the element tree a browser would, keeping each marked element's
    visible text. Hidden and never-rendered markup adds no text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # open elements, outermost first
        self.raw = None      # tag whose content never renders, until its end tag
        self.records = []    # marked elements and every <article>, in order
        self.heading = None  # text of the last visible heading closed so far

    # Tokens

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag):
        if self.raw:
            if tag == self.raw != "plaintext":
                self.raw = None
            return
        if self.stack and self.stack[-1]["ns"] != "html":
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i]["ns"] == "html":
                    break
                if self.stack[i]["tag"] == tag:
                    self.pop_to(i)
                    return
        if tag in ("html", "body"):  # later content still renders in the body
            return
        if tag == "br":
            self.start("br", [], False)
            return
        if tag in FORMATTING:
            self.end_formatting(tag)
        elif tag in SPECIAL or tag in CLOSES_P:
            if tag in ("td", "th", "tr", "tbody", "thead", "tfoot", "table"):
                i = self.in_scope({tag}, TABLE_SCOPE)
            else:
                stops = SCOPE | {"p": {"button"}, "li": {"ol", "ul"}}.get(tag, set())
                i = self.in_scope(HEADINGS if tag in HEADINGS else {tag}, stops)
            if i is not None:
                self.pop_to(i)
        else:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i]["tag"] == tag:
                    self.pop_to(i)
                    break
                if self.stack[i]["tag"] in SPECIAL:
                    break
        if tag not in INLINE:
            self.separate()

    def handle_data(self, data):
        if self.raw or not self.stack:
            return
        top = self.stack[-1]
        if top["hidden"] or top["vis"]:
            return
        in_pre = any(n["tag"] == "pre" for n in self.stack)
        loose = None  # the data-flags list, when this text sits outside its cards
        for n in self.stack:
            if n["heading"] is not None:
                n["heading"].append(data)
            rec = n["rec"]
            if rec is None:
                continue
            rec["text"].append(data)
            if not in_pre:
                rec["plain"].append(data)
            if "data-flags" in rec["attrs"]:
                loose = rec
            elif is_card(rec):
                loose = None
        if loose is not None:
            loose["loose"].append(data)

    # Tree construction

    def start(self, tag, attrs, self_closing):
        if self.raw:
            return
        ns = self.namespace(tag)
        if ns == "html":
            self.imply_end_tags(tag)
        attrs = first_wins(attrs)
        style = declarations(attrs.get("style"))
        parent = self.stack[-1] if self.stack else None
        hidden = parent["hidden"] if parent else None
        if hidden is None:
            reason = hiding_reason(tag, attrs, ns, style)
            hidden = (reason, object()) if reason else None
        vis = parent["vis"] if parent else None
        visibility = style.get("visibility") or (attrs.get("visibility") if ns != "html" else None)
        if visibility in ("hidden", "collapse"):
            vis = ("visibility:" + visibility, object())
        elif visibility == "visible":
            vis = None
        if tag not in INLINE:
            self.separate()
        node = {"tag": tag, "ns": ns, "hidden": hidden, "vis": vis, "rec": None,
                "heading": [] if tag in HEADINGS and ns == "html" else None}
        if tag == "article" or any(k in attrs for k in MARKERS):
            node["rec"] = self.record(tag, attrs, hidden or vis)
        if tag in RAW:
            self.raw = tag
        elif not ((ns == "html" and tag in VOID) or (self_closing and ns != "html")):
            self.stack.append(node)  # browsers ignore "/>" on HTML elements

    def record(self, tag, attrs, hidden):
        def nearest(test, stop=lambda r: False):
            for n in reversed(self.stack):
                if n["rec"] and test(n["rec"]):
                    return n["rec"]
                if n["rec"] and stop(n["rec"]):
                    return None
            return None

        origin = hidden[1] if hidden else None
        rec = {
            "tag": tag, "attrs": attrs, "line": self.getpos()[0],
            "marked": any(k in attrs for k in MARKERS),
            "text": [], "plain": [], "loose": [],
            "hidden": hidden[0] if hidden else None, "origin": origin,
            "wireframe": nearest(lambda r: "data-wireframe" in r["attrs"]),
            "flags": nearest(lambda r: "data-flags" in r["attrs"]),
            "card": nearest(lambda r: "data-measure" in r["attrs"] or "data-severity" in r["attrs"]),
            # A card enclosing this one inside the same red-flags list.
            "outer": nearest(is_card, stop=lambda r: "data-flags" in r["attrs"]),
            "heading": self.heading,
        }
        # Report a hidden marker once, at the outermost marked element it hides.
        rec["quiet"] = origin is not None and nearest(
            lambda r: r["marked"] and r["origin"] is origin) is not None
        self.records.append(rec)
        return rec

    def namespace(self, tag):
        if tag in ("svg", "math"):
            return tag
        if not self.stack or self.stack[-1]["ns"] == "html":
            return "html"
        top = self.stack[-1]
        if top["tag"] in ("foreignobject", "desc") or (
                top["ns"] == "math" and top["tag"] in ("mi", "mo", "mn", "ms", "mtext")):
            return "html"
        if tag in BREAKOUT:
            while self.stack and self.stack[-1]["ns"] != "html":
                self.pop_to(len(self.stack) - 1)
            return "html"
        return top["ns"]

    def imply_end_tags(self, tag):
        """Close what a browser closes when this start tag arrives."""
        if tag == "li":
            self.close_item({"li"})
        elif tag in ("dd", "dt"):
            self.close_item({"dd", "dt"})
        elif tag in ("td", "th"):
            self.close_in_table({"td", "th"}, {"tr", "tbody", "thead", "tfoot"})
        elif tag == "tr":
            self.close_in_table({"tr"}, {"tbody", "thead", "tfoot"})
        elif tag in ("tbody", "thead", "tfoot"):
            self.close_in_table({"tbody", "thead", "tfoot"}, set())
        elif tag in ("option", "optgroup") and self.stack and self.stack[-1]["tag"] == "option":
            self.pop_to(len(self.stack) - 1)
        elif tag == "a":
            self.end_formatting("a")
        if tag in CLOSES_P:
            i = self.in_scope({"p"}, SCOPE | {"button"})
            if i is not None:
                self.pop_to(i)
        if tag in HEADINGS and self.stack and self.stack[-1]["tag"] in HEADINGS:
            self.pop_to(len(self.stack) - 1)

    def close_item(self, names):
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i]["tag"]
            if t in names:
                self.pop_to(i)
                return
            if t in SPECIAL and t not in ("address", "div", "p"):
                return

    def close_in_table(self, names, stops):
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i]["tag"]
            if t in names:
                self.pop_to(i)
                return
            if t in stops or t in TABLE_SCOPE:
                return

    def end_formatting(self, tag):
        """A misnested inline end tag closes the inline element, not the
        blocks opened inside it (the adoption agency algorithm, simplified)."""
        i = next((k for k in range(len(self.stack) - 1, -1, -1)
                  if self.stack[k]["tag"] == tag), None)
        if i is None or any(n["tag"] in SCOPE for n in self.stack[i + 1:]):
            return
        block = next((k for k in range(i + 1, len(self.stack))
                      if self.stack[k]["tag"] in SPECIAL), None)
        if block is None:
            self.pop_to(i)
        else:
            del self.stack[i:block]

    def in_scope(self, names, stops):
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i]["tag"]
            if t in names:
                return i
            if t in stops:
                return None
        return None

    def pop_to(self, i):
        while len(self.stack) > i:
            node = self.stack.pop()
            if node["heading"] is not None and not (node["hidden"] or node["vis"]):
                self.heading = " ".join("".join(node["heading"]).split())

    def separate(self):
        """Element boundaries split text, so <div>6</div><div>1</div> isn't 61."""
        for n in self.stack:
            if n["heading"] is not None:
                n["heading"].append(" ")
            if n["rec"] is not None:
                n["rec"]["text"].append(" ")
                n["rec"]["plain"].append(" ")


def first_wins(attrs):
    out = {}
    for k, v in attrs:
        out.setdefault(k, v)  # browsers keep the first of a repeated attribute
    return out


def is_card(rec):
    return rec["tag"] == "article" or "data-severity" in rec["attrs"]


def parse_markers(html):
    page = Page()
    page.feed(html)
    if page.cdata_elem is None and page.rawdata.startswith("<!--"):
        page.rawdata = ""  # browsers run an unterminated comment to the end
    page.close()
    return page.records


def text(rec, key="text"):
    return " ".join("".join(rec[key]).split())


def canon(s):
    """Compare names by decoded value; Python versions decode attributes differently."""
    return None if s is None else unescape(s)


def fold(s):
    return " ".join(unescape(s or "").split()).casefold()


def first_int(s):
    m = re.search(r"\d[\d,]*", s)
    return int(m.group().replace(",", "")) if m else None


def marker_label(rec):
    name = next(k for k in MARKERS if k in rec["attrs"])
    value = rec["attrs"][name]
    return f"<{rec['tag']} {name}>" if value is None else f'<{rec["tag"]} {name}="{value}">'


def expected(model, scratch_names=()):
    """What the artifact must show, computed from the change model."""
    flags = [(s, fold(s)) for s in scratch_names]
    matched = set()
    pages, excluded = {}, []
    stats = Counter({k: 0 for k in STATS})
    for report, r in (model.get("reports") or {}).items():
        for page_id, p in (r.get("pages") or {}).items():
            name = p.get("display_name") or page_id
            forms = {fold(page_id), fold(name), fold(f"{report}/{page_id}"), fold(f"{report}/{name}")}
            hits = [s for s, f in flags if f in forms]
            matched.update(hits)
            reasons = (["marked scratch by the extractor"] if p.get("scratch") else []) + [
                f"--scratch {h!r}" for h in hits]
            visuals = {canon(vid): v for vid, v in (p.get("visuals") or {}).items()}
            pages[(canon(report), canon(page_id))] = {
                "report": report, "id": page_id, "name": name, "scratch": bool(reasons),
                "visuals": visuals,
                "drawn": {vid for vid, v in visuals.items() if v.get("visual_type") != "visualGroup"},
            }
            if reasons:
                excluded.append({"report": report, "page": page_id, "display_name": name,
                                 "reason": "; ".join(reasons)})
                continue
            stats["pages_added"] += p.get("status") == "added"
            # Unlike the extractor's visual_counts, chips skip group containers.
            for vid in pages[(canon(report), canon(page_id))]["drawn"]:
                status = visuals[vid].get("status")
                if f"visuals_{status}" in stats:
                    stats[f"visuals_{status}"] += 1
    measures, deleted = {}, set()
    for model_name, m in (model.get("models") or {}).items():
        for table, t in (m.get("tables") or {}).items():
            for kind in ("added", "modified"):
                for member in t.get(f"measures_{kind}") or []:
                    measures[(canon(model_name), canon(table), canon(member["name"]))] = (
                        model_name, table, member["name"])
                stats[f"measures_{kind}"] += len(t.get(f"measures_{kind}") or [])
            for member in t.get("measures_deleted") or []:
                deleted.add((canon(model_name), canon(table), canon(member["name"])))
        stats["relationships_added"] += len((m.get("relationships") or {}).get("added") or [])
    problems = [f"--scratch {s!r} matches no page in the change model"
                for s, _ in flags if s not in matched]
    return {"pages": pages, "measures": measures, "deleted": deleted, "stats": dict(stats),
            "excluded": excluded, "problems": problems}


def badge_problem(card, badges, family, key, where):
    """The card's one data-badge must show its own badge and none of the others."""
    mine = badges.get(id(card), [])
    want = family[key]
    if not mine:
        return f"{where} has no data-badge element showing its {want} badge"
    if len(mine) > 1:
        return f"{where} has {len(mine)} data-badge elements; give it exactly one"
    shown = text(mine[0])
    found = [b for b in family.values() if b in shown]
    if found != [want]:
        return (f"{where} is {key}, so its data-badge must show {want} alone; it shows "
                + (" ".join(found) if found else "none of " + "".join(family.values())))
    return None


def check(model, html, scratch_names=()):
    want = expected(model, scratch_names)
    problems = list(want["problems"])
    shown = []
    for rec in parse_markers(html):
        if rec["hidden"] is None:
            shown.append(rec)
        elif rec["marked"] and not rec["quiet"]:
            problems.append(f"line {rec['line']}: {marker_label(rec)} is hidden from readers "
                            f"({rec['hidden']}), so the check skips it")
    verdicts, findings = Counter(), Counter()

    badges = defaultdict(list)
    for rec in (r for r in shown if "data-badge" in r["attrs"]):
        owner = rec if ("data-measure" in rec["attrs"] or "data-severity" in rec["attrs"]) else rec["card"]
        if owner is None:
            problems.append(f"line {rec['line']}: data-badge sits outside any measure or red-flag card")
        else:
            badges[id(owner)].append(rec)

    # Measures: one verdict card each, naming the measure, badge agreeing with data-verdict.
    seen = Counter()
    for rec in (r for r in shown if "data-measure" in r["attrs"]):
        a = rec["attrs"]
        names = (a.get("data-model"), a.get("data-table"), a.get("data-measure"))
        where = f"line {rec['line']}: measure {names[1]}[{names[2]}]"
        if None in names:
            problems.append(f"{where} needs values for data-model, data-table and data-measure")
            continue
        key = tuple(canon(n) for n in names)
        if key not in want["measures"]:
            problems.append(f"{where} (model {names[0]}) is " + (
                "deleted; list deleted measures without data-measure" if key in want["deleted"]
                else "not an added/modified measure in the change model"))
            continue
        seen[key] += 1
        if fold(names[2]) not in fold(text(rec, "plain")):
            problems.append(f"{where} card doesn't show the measure's name outside <pre>")
        verdict = a.get("data-verdict")
        if verdict not in VERDICT_BADGES:
            problems.append(f"{where} has data-verdict {verdict!r}; "
                            f"use one of {sorted(VERDICT_BADGES)}")
            continue
        verdicts[verdict] += 1
        problem = badge_problem(rec, badges, VERDICT_BADGES, verdict, where)
        if problem:
            problems.append(problem)
    for key, (m, t, n) in sorted(want["measures"].items(), key=lambda kv: kv[1]):
        if not seen[key]:
            problems.append(f"measure {t}[{n}] (model {m}) has no verdict card")
        elif seen[key] > 1:
            problems.append(f"measure {t}[{n}] has {seen[key]} verdict cards")

    # Wireframes: one per curated page, under its heading, drawing every
    # non-group visual with the change model's status.
    frames = defaultdict(list)
    drawn = defaultdict(Counter)
    for rec in shown:
        a = rec["attrs"]
        if "data-wireframe" in a:
            if a.get("data-report") is None or a["data-wireframe"] is None:
                problems.append(f"line {rec['line']}: wireframe needs values for data-report "
                                "and data-wireframe")
            else:
                frames[(canon(a["data-report"]), canon(a["data-wireframe"]))].append(rec)
        if "data-visual" not in a:
            continue
        vid = a["data-visual"]
        frame = rec["wireframe"]
        if vid is None:
            problems.append(f"line {rec['line']}: data-visual has no value")
            continue
        if frame is None:
            problems.append(f"line {rec['line']}: visual {vid} sits outside any data-wireframe; "
                            "only wireframe boxes carry data-visual")
            continue
        fa = frame["attrs"]
        if fa.get("data-report") is None or fa["data-wireframe"] is None:
            continue
        fkey = (canon(fa["data-report"]), canon(fa["data-wireframe"]))
        drawn[fkey][canon(vid)] += 1
        visual = want["pages"].get(fkey, {}).get("visuals", {}).get(canon(vid))
        if visual is not None and a.get("data-status") != visual.get("status"):
            has = (f"has data-status {a['data-status']!r}" if a.get("data-status") is not None
                   else "has no data-status")
            problems.append(f"line {rec['line']}: visual {vid} {has}; "
                            f"the change model says {visual.get('status')!r}")
    for key, page in sorted(want["pages"].items(), key=lambda kv: tuple(map(str, kv[0]))):
        label = f"page {page['id']} (report {page['report']})"
        if page["scratch"]:
            if key in frames:
                problems.append(f"{label} is scratch work but has a wireframe")
            continue
        if key not in frames:
            problems.append(f"{label} has no wireframe")
            continue
        if len(frames[key]) > 1:
            problems.append(f"{label} has {len(frames[key])} wireframes")
        for rec in frames[key]:
            if fold(page["name"]) not in fold(rec["heading"]):
                problems.append(
                    f"line {rec['line']}: wireframe for {label} "
                    + (f"follows the heading {rec['heading']!r}" if rec["heading"] else "has no heading before it")
                    + f"; the last heading before it must name the page {page['name']!r}")
        missing = page["drawn"] - set(drawn[key])
        unknown = set(drawn[key]) - set(page["visuals"])
        repeated = sorted(v for v, n in drawn[key].items() if n > 1)
        if missing:
            problems.append(f"{label} wireframe is missing visuals {sorted(missing)}")
        if unknown:
            problems.append(f"{label} wireframe draws visuals not on the page {sorted(unknown)}")
        if repeated:
            problems.append(f"{label} wireframe draws visuals more than once {repeated}")
    for key in sorted(set(frames) - set(want["pages"]), key=lambda k: tuple(map(str, k))):
        problems.append(f"wireframe for page {key[1]} (report {key[0]}) matches no touched "
                        "page; untouched pages get no wireframe")

    # Stat chips: each once, labelled, showing the change model's number.
    chips = defaultdict(list)
    for rec in (r for r in shown if "data-stat" in r["attrs"]):
        stat = rec["attrs"]["data-stat"]
        if stat in STATS:
            chips[stat].append(rec)
        else:
            problems.append(f"line {rec['line']}: data-stat {stat!r} is not one of {list(STATS)}")
    for stat in STATS:
        n = want["stats"][stat]
        if not chips[stat]:
            problems.append(f"no stat chip for {stat} (expected {n})")
            continue
        if len(chips[stat]) > 1:
            shows = ", ".join(f"line {r['line']} shows {first_int(text(r))}" for r in chips[stat])
            problems.append(f"{len(chips[stat])} stat chips for {stat} ({shows}); keep exactly one")
            continue
        rec = chips[stat][0]
        shown_text = text(rec)
        if first_int(shown_text) != n:
            problems.append(f"stat chip {stat} shows {first_int(shown_text)}, change model gives {n}")
        noun, verbs = STAT_WORDS[stat]
        if noun not in shown_text.casefold() or not any(v in shown_text.casefold() for v in verbs):
            example = f"{n} {noun}{'' if n == 1 else 's'} {verbs[0]}"
            problems.append(f"line {rec['line']}: stat chip {stat} reads {shown_text!r}; label it "
                            f"with '{noun}' and '{verbs[0]}', like '{example}'")

    # Red flags: each finding its own marked <article> in data-flags, badge agreeing.
    lists = [r for r in shown if "data-flags" in r["attrs"]]
    if not lists:
        problems.append("no data-flags element; mark the element that holds the red-flag "
                        "cards, even when there are none")
    for rec in lists:
        loose = [b for b in SEVERITY_BADGES.values() if b in "".join(rec["loose"])]
        if loose:
            problems.append(f"line {rec['line']}: the data-flags list shows {' '.join(loose)} "
                            "outside any red-flag card; mark each finding's own <article>, and "
                            "keep data-flags on the element holding only the cards")
    for rec in shown:
        if "data-severity" not in rec["attrs"]:
            if rec["tag"] == "article" and rec["flags"] is not None:
                problems.append(f"line {rec['line']}: <article> in the data-flags list has no "
                                "data-severity")
            continue
        severity = rec["attrs"]["data-severity"]
        where = f"line {rec['line']}: red-flag card"
        if rec["tag"] != "article":
            problems.append(f"{where} is marked on <{rec['tag']}>; put data-severity on each "
                            "finding's own <article>")
        if rec["flags"] is None:
            problems.append(f"{where} sits outside the data-flags list")
        if rec["outer"] is not None:
            problems.append(f"{where} sits inside the card at line {rec['outer']['line']}; "
                            "give each finding its own <article>")
        if severity not in SEVERITY_BADGES:
            problems.append(f"line {rec['line']}: data-severity {severity!r}; "
                            f"use one of {sorted(SEVERITY_BADGES)}")
            continue
        findings[severity] += 1
        problem = badge_problem(rec, badges, SEVERITY_BADGES, severity, where)
        if problem:
            problems.append(problem)

    # Exclusion line: a reader sees every page the check left out.
    if want["excluded"]:
        lines = [r for r in shown if "data-excluded" in r["attrs"]]
        said = fold(" ".join(text(r) for r in lines))
        for page in want["excluded"]:
            if not lines or fold(page["display_name"]) not in said:
                problems.append(f"no data-excluded line names excluded page "
                                f"{page['display_name']!r} (report {page['report']})")

    return {
        "findings": {s: findings[s] for s in SEVERITY_BADGES},
        "verdicts": {v: verdicts[v] for v in VERDICT_BADGES},
        "stats": want["stats"],
        "curated_pages": sum(not p["scratch"] for p in want["pages"].values()),
        "excluded_pages": want["excluded"],
        "problems": problems,
        "verdict": "FAIL" if problems else "PASS",
    }


def failed(problem):
    return {"findings": {s: 0 for s in SEVERITY_BADGES}, "verdicts": {v: 0 for v in VERDICT_BADGES},
            "stats": {}, "curated_pages": 0, "excluded_pages": [], "problems": [problem],
            "verdict": "FAIL"}


def run(change_model, artifact, scratch_names=()):
    try:
        with open(change_model, encoding="utf-8") as f:
            model = json.load(f)
    except (OSError, ValueError) as e:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return failed(f"cannot read change model {change_model}: {e}")
    if not isinstance(model, dict):
        return failed(f"change model {change_model} is not a JSON object")
    try:
        with open(artifact, "rb") as f:
            data = f.read()
    except OSError as e:
        return failed(f"cannot read artifact {artifact}: {e}")
    try:
        html = data.decode("utf-8")
    except UnicodeDecodeError as e:
        return failed(f"artifact is not UTF-8 (byte {data[e.start]:#04x} at offset {e.start}); "
                      "save it as UTF-8")
    return check(model, html, scratch_names)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("change_model", help="path to change_model.json")
    ap.add_argument("artifact", help="path to the artifact HTML")
    ap.add_argument("--scratch", action="append", default=[],
                    help="page display name or id the user named as scratch, "
                         "or REPORT/PAGE (repeatable)")
    args = ap.parse_args()
    result = run(args.change_model, args.artifact, args.scratch)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    print(result["verdict"])
    sys.exit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
