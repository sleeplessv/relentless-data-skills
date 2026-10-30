import asyncio, json, sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/gen-b1")
import gen
from playwright.async_api import async_playwright
PAGE = """<!doctype html><html><body><div id="out"></div>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs";
import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs";
mermaid.registerLayoutLoaders(elkLayouts);
mermaid.initialize({ startOnLoad:false, securityLevel:"strict", fontFamily:'-apple-system, "Segoe UI", Helvetica, Arial, sans-serif', sequence:{ useMaxWidth:true, actorFontWeight:600, messageFontSize:13, actorFontSize:14, width:150, height:36, boxMargin:8, messageMargin:24, mirrorActors:false, wrap:false } });
window.__m = mermaid; window.__ready = true;
</script></body></html>"""
CANDS = {
  "LR strict": gen.dag_source("LR"),
  "TB strict": gen.dag_source("TB"),
  "LR collapsed": gen.dag_source("LR", collapse_skills=True),
  "TB collapsed": gen.dag_source("TB", collapse_skills=True),
  "SEQ": gen.MERMAID_SEQ,
}
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); p = await b.new_page(viewport={"width":1280,"height":900})
        await p.set_content(PAGE); await p.wait_for_function("window.__ready === true", timeout=60000)
        for name, text in CANDS.items():
            r = await p.evaluate("""async ([name,text]) => { const {svg} = await window.__m.render('x'+Math.random().toString(36).slice(2), text); const m = svg.match(/viewBox="([^"]+)"/); return m && m[1]; }""", [name, text])
            print(f"{name}: viewBox {r}")
        await b.close()
asyncio.run(main())
