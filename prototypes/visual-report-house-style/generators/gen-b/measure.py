import asyncio, json, re, sys
from playwright.async_api import async_playwright

src = open("variant_dag_src.json").read()
variants = json.loads(src)

PAGE = """<!doctype html><html><body>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs";
import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs";
mermaid.registerLayoutLoaders(elkLayouts);
mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
window.__m = mermaid; window.__ready = true;
</script></body></html>"""

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        p = await b.new_page(viewport={"width":1280,"height":900})
        await p.set_content(PAGE)
        await p.wait_for_function("window.__ready === true", timeout=60000)
        for name, text in variants.items():
            try:
                r = await p.evaluate("""async ([name, text]) => {
                    const { svg } = await window.__m.render("m_" + name.replace(/[^a-z0-9]/gi,'_'), text);
                    const m = svg.match(/viewBox="([^"]+)"/);
                    const w = svg.match(/ width="([^"]+)"/), h = svg.match(/ height="([^"]+)"/);
                    return { viewBox: m && m[1], w: w && w[1], h: h && h[1], len: svg.length };
                }""", [name, text])
                print(name, r)
            except Exception as e:
                print(name, "ERROR", str(e)[:300])
        await b.close()
asyncio.run(main())
