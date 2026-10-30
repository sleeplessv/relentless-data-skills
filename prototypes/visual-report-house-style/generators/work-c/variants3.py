import asyncio
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
sb = open("short_dag_body.txt").read()
def dag_variant(direction, node_sp, rank_sp, pad, body=sb):
    fm = ["---","config:","  layout: elk","  theme: base","  themeVariables:",
          "    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'",
          "  flowchart:","    useMaxWidth: false",f"    nodeSpacing: {node_sp}",f"    rankSpacing: {rank_sp}",f"    padding: {pad}",
          "  elk:","    mergeEdges: true","    nodePlacementStrategy: SIMPLE","---"]
    return "\n".join(fm) + "\n" + body.replace("flowchart LR", f"flowchart {direction}", 1)
cands = {
 "LR pad2 ns4 rs45": dag_variant("LR", 4, 45, 2),
 "LR pad4 ns6 rs45": dag_variant("LR", 6, 45, 4),
 "LR pad4 ns8 rs60": dag_variant("LR", 8, 60, 4),
 "TB pad4 ns6 rs50": dag_variant("TB", 6, 50, 4),
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
  alt no Playwright or browser
    S-->>A: BLOCKED, exit 2
  end
  S->>+C: launch(), new_page()
  S->>C: goto(report), 30 s
  C->>N: GET scripts
  N-->>C: responses
  S->>C: settle(), 20 s
  S->>C: facts(), reveal(),<br/>facts() again
  Note over S,C: diagram_status(),<br/>images(), screenshots()
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
def seq_variant(cfg, body=seq_body):
    fm = ["---","config:","  theme: base","  themeVariables:","    fontFamily: '\"Helvetica Neue\", Arial, system-ui, sans-serif'","    fontSize: 13px","  sequence:"] + cfg + ["---"]
    return "\n".join(fm) + "\n" + body
base = ["    useMaxWidth: true","    mirrorActors: false","    width: 110","    actorMargin: 30","    messageMargin: 22","    boxMargin: 6","    height: 40"]
cands["SEQ v3 br"] = seq_variant(base)
cands["SEQ v3 br wrap"] = seq_variant(base + ["    wrap: true"])
cands["SEQ v3 nobr"] = seq_variant(base, seq_body.replace("<br/>", " "))
JS = """
async ([sources]) => {
  const mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs")).default;
  const elk = (await import("https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs")).default;
  mermaid.registerLayoutLoaders(elk);
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
  const out = [];
  for (const [name, s] of sources) {
    try { const r = await mermaid.render("p" + out.length, s); const m = r.svg.match(/viewBox="([^"]+)"/); out.push([name, true, m && m[1], (r.svg.match(/<br\\s*\\/?>/g)||[]).length]); }
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
