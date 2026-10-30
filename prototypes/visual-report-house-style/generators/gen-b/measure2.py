import asyncio, json
from playwright.async_api import async_playwright
variants = json.load(open("variant_dag_src.json"))
CFG = {"w":150,"h":36,"mm":28}
PAGE = """<!doctype html><html><body>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs";
window.__m = mermaid; window.__ready = true;
</script></body></html>"""
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); p = await b.new_page(viewport={"width":1280,"height":900})
        await p.set_content(PAGE); await p.wait_for_function("window.__ready === true", timeout=60000)
        for w in (150, 130, 120):
            for mm in (28, 20):
                await p.evaluate("""([w,mm]) => window.__m.initialize({ startOnLoad:false, securityLevel:'strict', sequence:{ useMaxWidth:false, messageFontSize:12, actorFontSize:13, width:w, height:36, boxMargin:8, messageMargin:mm, mirrorActors:false, wrap:false, actorMargin: 40 } })""", [w, mm])
                for name, text in variants.items():
                    r = await p.evaluate("""async ([name,text]) => { const {svg} = await window.__m.render('x'+Math.random().toString(36).slice(2), text); const m = svg.match(/viewBox="([^"]+)"/); return m && m[1]; }""", [name, text])
                    print(f"actor w={w} mm={mm} {name}: viewBox {r}")
        await b.close()
asyncio.run(main())
