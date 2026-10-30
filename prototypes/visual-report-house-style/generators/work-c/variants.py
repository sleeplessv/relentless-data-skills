import asyncio, re, html, json, sys
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
src = open(page_path).read()
dag, seq = [html.unescape(x) for x in re.findall(r'<pre class="mermaid">\n(.*?)\n</pre>', src, re.S)]
fm_end = dag.index("---\nflowchart")
dag_body = dag[fm_end+4:]  # "flowchart LR ..."
def dag_variant(direction, extra_cfg, node_sp=18, rank_sp=70):
    fm = ["---","config:","  layout: elk","  theme: base","  themeVariables:",
          "    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'","    fontSize: 13px",
          "  flowchart:","    useMaxWidth: false",f"    nodeSpacing: {node_sp}",f"    rankSpacing: {rank_sp}","    padding: 8"] + extra_cfg + ["---"]
    body = dag_body.replace("flowchart LR", f"flowchart {direction}", 1)
    return "\n".join(fm) + "\n" + body
cands = {
 "LR base": dag_variant("LR", []),
 "LR merge": dag_variant("LR", ["  elk:","    mergeEdges: true"]),
 "LR simple": dag_variant("LR", ["  elk:","    mergeEdges: true","    nodePlacementStrategy: SIMPLE"], 10, 60),
 "LR linear": dag_variant("LR", ["  elk:","    mergeEdges: true","    nodePlacementStrategy: LINEAR_SEGMENTS"], 10, 60),
 "LR bk": dag_variant("LR", ["  elk:","    mergeEdges: true","    nodePlacementStrategy: BRANDES_KOEPF"], 10, 60),
 "TB merge": dag_variant("TB", ["  elk:","    mergeEdges: true"], 12, 60),
 "TB simple": dag_variant("TB", ["  elk:","    mergeEdges: true","    nodePlacementStrategy: SIMPLE"], 12, 60),
}
# sequence variants
seq_body = seq[seq.index("sequenceDiagram"):]
def seq_variant(cfg_lines, body=seq_body):
    fm = ["---","config:","  theme: base","  themeVariables:","    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'","    fontSize: 13px","  sequence:"] + cfg_lines + ["---"]
    return "\n".join(fm) + "\n" + body
short_body = """sequenceDiagram
  autonumber
  participant A as Agent
  participant S as Script
  participant C as Chromium
  participant N as CDNs
  participant R as Report file
  A->>+S: run check_render.py REPORT.html
  S->>R: read_source(report)
  R-->>S: HTML text
  alt OSError
    S-->>A: cannot read the report, FAIL (exit 1)
  end
  S->>S: import playwright, start watchdog (160 s)
  alt ImportError or no browser
    S-->>A: BLOCKED (exit 2)
  end
  S->>+C: launch(), new_page(), add_init_script()
  S->>C: goto(report, 30 s)
  C->>N: GET Vega, Mermaid, ELK
  N-->>C: responses, Net records each
  S->>C: settle(), facts(), reveal(), facts()
  Note over S,C: diagram_status() per diagram, then images() and screenshots()
  S->>C: probe() up to 20 suspect diagrams, 15 s each
  alt a request failed and no remote host answered
    S->>C: fetch(known-good jsDelivr URL, 5 s)
    C->>N: GET package.json
    N-->>C: reached or not, sets network_ok
  end
  S->>C: browser.close(), 10 s cap
  deactivate C
  S->>S: emit(), verdict(), problems()
  S-->>-A: JSON, then PASS, FAIL or BLOCKED (exit 0, 1, 2)"""
cands["SEQ orig"] = seq
cands["SEQ wrap"] = seq_variant(["    useMaxWidth: true","    mirrorActors: false","    wrap: true","    width: 140","    actorMargin: 40","    messageMargin: 25","    boxMargin: 6"])
cands["SEQ short"] = seq_variant(["    useMaxWidth: true","    mirrorActors: false","    width: 120","    actorMargin: 40","    messageMargin: 25","    boxMargin: 6"], short_body)
cands["SEQ short wrap"] = seq_variant(["    useMaxWidth: true","    mirrorActors: false","    wrap: true","    width: 120","    actorMargin: 40","    messageMargin: 25","    boxMargin: 6"], short_body)
JS = """
async ([sources]) => {
  const mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs")).default;
  const elk = (await import("https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs")).default;
  mermaid.registerLayoutLoaders(elk);
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
  const out = [];
  for (const [name, s] of sources) {
    try {
      const r = await mermaid.render("p" + out.length, s);
      const m = r.svg.match(/viewBox="([^"]+)"/);
      out.push([name, true, m && m[1]]);
    } catch (e) { out.push([name, false, String(e && (e.message || e)).slice(0, 300)]); }
  }
  return out;
}
"""
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); pg = await b.new_page()
        await pg.goto("file://" + page_path, wait_until="load")
        res = await pg.evaluate(JS, [list(cands.items())])
        for r in res: print(r)
        await b.close()
asyncio.run(main())
