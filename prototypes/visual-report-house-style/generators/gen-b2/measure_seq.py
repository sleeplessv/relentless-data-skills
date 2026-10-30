import asyncio, sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/gen-b1")
import gen
from playwright.async_api import async_playwright
PAGE = """<!doctype html><html><body>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs";
import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs";
mermaid.registerLayoutLoaders(elkLayouts);
window.__m = mermaid; window.__ready = true;
</script></body></html>"""
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); p = await b.new_page(viewport={"width":1280,"height":900})
        await p.set_content(PAGE); await p.wait_for_function("window.__ready === true", timeout=60000)
        for w,h,mm,bm in ((150,36,24,8),(140,32,16,6),(130,30,14,5),(120,30,12,4)):
            await p.evaluate("""([w,h,mm,bm]) => window.__m.initialize({ startOnLoad:false, securityLevel:'strict', fontFamily:'-apple-system, "Segoe UI", Helvetica, Arial, sans-serif', sequence:{ useMaxWidth:true, actorFontWeight:600, messageFontSize:13, actorFontSize:14, width:w, height:h, boxMargin:bm, messageMargin:mm, mirrorActors:false, wrap:false, actorMargin:40 } })""", [w,h,mm,bm])
            r = await p.evaluate("""async (text) => { const {svg} = await window.__m.render('x'+Math.random().toString(36).slice(2), text); const m = svg.match(/viewBox="([^"]+)"/); return m && m[1]; }""", gen.MERMAID_SEQ)
            print(f"seq w={w} h={h} mm={mm} bm={bm}: viewBox {r}")
        for name in ("TB collapsed","LR collapsed"):
            d, c = name.split()
            for strat in ("NETWORK_SIMPLEX","BRANDES_KOEPF","LINEAR_SEGMENTS"):
                text = gen.dag_source(d, collapse_skills=True).replace("NETWORK_SIMPLEX", strat)
                r = await p.evaluate("""async (text) => { const {svg} = await window.__m.render('x'+Math.random().toString(36).slice(2), text); const m = svg.match(/viewBox="([^"]+)"/); return m && m[1]; }""", text)
                print(f"{name} {strat}: viewBox {r}")
        await b.close()
asyncio.run(main())
