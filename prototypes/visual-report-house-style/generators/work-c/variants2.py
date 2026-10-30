import asyncio, re, html
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
src = open(page_path).read()
dag, seq = [html.unescape(x) for x in re.findall(r'<pre class="mermaid">\n(.*?)\n</pre>', src, re.S)]
dag_body = dag[dag.index("---\nflowchart")+4:]
# short labels: replace label text with id for non-skill nodes
def shorten(body):
    out = []
    for line in body.splitlines():
        m = re.match(r'  (\w+)\["(.+)"\]$', line)
        if m:
            nid, label = m.groups()
            short = {"plugin_json": "plugin.json (18)", "fld_scripts": "fabric-lineage-dag/scripts (17)"}.get(nid)
            if short is None:
                if label.startswith("CI job "): short = "CI " + label[7:].split(" (")[0]
                elif label.startswith("tests/"): short = label[6:-3]
                elif label.startswith("scripts/"): short = label[8:]
                elif "/scripts/" in label: short = label.split("/scripts/")[1]
                elif "/references/" in label: short = label.split("/")[0].split("-")[0] + "/" + label.split("/references/")[1]
                else: short = label
            line = f'  {nid}["{short}"]'
        out.append(line)
    return "\n".join(out)
def dag_variant(direction, extra_cfg, node_sp, rank_sp, font, body):
    fm = ["---","config:","  layout: elk","  theme: base","  themeVariables:",
          "    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'",f"    fontSize: {font}px",
          "  flowchart:","    useMaxWidth: false",f"    nodeSpacing: {node_sp}",f"    rankSpacing: {rank_sp}","    padding: 6"] + extra_cfg + ["---"]
    return "\n".join(fm) + "\n" + body.replace("flowchart LR", f"flowchart {direction}", 1)
simple = ["  elk:","    mergeEdges: true","    nodePlacementStrategy: SIMPLE"]
sb = shorten(dag_body)
cands = {
 "LR simple tight 12": dag_variant("LR", simple, 6, 45, 12, dag_body),
 "LR simple short 12": dag_variant("LR", simple, 6, 45, 12, sb),
 "TB simple short 12": dag_variant("TB", simple, 8, 50, 12, sb),
 "TB simple short 13": dag_variant("TB", simple, 10, 55, 13, sb),
 "TB linear short 12": dag_variant("TB", ["  elk:","    mergeEdges: true","    nodePlacementStrategy: LINEAR_SEGMENTS"], 8, 50, 12, sb),
 "TB nomerge short 12": dag_variant("TB", ["  elk:","    nodePlacementStrategy: SIMPLE"], 8, 50, 12, sb),
}
seq_body = """sequenceDiagram
  autonumber
  participant A as Agent
  participant S as check_render.py
  participant C as Chromium
  participant N as CDNs
  participant R as Report file
  A->>+S: run check_render.py
  S->>R: read_source()
  R-->>S: HTML text
  alt OSError
    S-->>A: FAIL, exit 1
  end
  S->>S: import playwright
  alt ImportError or no browser
    S-->>A: BLOCKED, exit 2
  end
  S->>+C: launch(), new_page()
  S->>C: goto(report), 30 s
  C->>N: GET scripts
  N-->>C: responses
  S->>C: settle(), 20 s
  S->>C: facts(), reveal(), facts()
  Note over S,C: diagram_status(), images(), screenshots()
  S->>C: probe(), 15 s each
  alt a request failed
    S->>C: fetch(jsDelivr), 5 s
    C->>N: GET package.json
    N-->>C: network_ok
  end
  S->>C: close(), 10 s cap
  deactivate C
  S->>S: emit(), verdict()
  S-->>-A: PASS, FAIL or BLOCKED"""
def seq_variant(cfg):
    fm = ["---","config:","  theme: base","  themeVariables:","    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'","    fontSize: 13px","  sequence:"] + cfg + ["---"]
    return "\n".join(fm) + "\n" + seq_body
cands["SEQ v2 w130"] = seq_variant(["    useMaxWidth: true","    mirrorActors: false","    width: 130","    actorMargin: 40","    messageMargin: 25","    boxMargin: 6"])
cands["SEQ v2 w110 m30"] = seq_variant(["    useMaxWidth: true","    mirrorActors: false","    width: 110","    actorMargin: 30","    messageMargin: 22","    boxMargin: 6","    height: 40"])
JS = """
async ([sources]) => {
  const mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs")).default;
  const elk = (await import("https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs")).default;
  mermaid.registerLayoutLoaders(elk);
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
  const out = [];
  for (const [name, s] of sources) {
    try { const r = await mermaid.render("p" + out.length, s); const m = r.svg.match(/viewBox="([^"]+)"/); out.push([name, true, m && m[1]]); }
    catch (e) { out.push([name, false, String(e && (e.message || e)).slice(0, 300)]); }
  }
  return out;
}
"""
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); pg = await b.new_page()
        await pg.goto("file://" + page_path, wait_until="load")
        for r in await pg.evaluate(JS, [list(cands.items())]): print(r)
        await b.close()
asyncio.run(main())
open("short_dag_body.txt","w").write(sb)
