import asyncio, os
from playwright.async_api import async_playwright
S = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad"
URL = f"file://{S}/proto/variant-navy-coral-v2.html"; OUT = f"{S}/proto/variant-navy-coral-v2-check"
os.makedirs(OUT, exist_ok=True)
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w in (1440, 768):
            p = await b.new_page(viewport={"width": w, "height": 900})
            await p.goto(URL, wait_until="load")
            await p.wait_for_function("document.querySelectorAll('pre.mermaid svg').length === 1 && document.querySelectorAll('.vega-embed svg.marks').length === 2", timeout=90000)
            await p.wait_for_timeout(600)
            info = await p.evaluate("""() => {
              const over = [...document.querySelectorAll('.figframe, table, .fig .visual, pre.code')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth);
              const svg = [...document.querySelectorAll('#dag-frame svg.dag')].find(s => getComputedStyle(s).display !== 'none');
              const r = svg.getBoundingClientRect(), fr = document.querySelector('#dag-frame').getBoundingClientRect();
              const vb = svg.viewBox.baseVal, scale = r.width / vb.width;
              // text that spills past its node box (in SVG units)
              const spill = [...svg.querySelectorAll('g.dn')].flatMap(g => {
                const bw = g.querySelector('rect.box').width.baseVal.value;
                return [...g.querySelectorAll('text')].filter(t => { const bb = t.getBBox(); return bb.x + bb.width > bw - 6 - (g.classList.contains('group') && t.classList.contains('nm') ? 30 : 0); }).map(t => t.textContent);
              });
              const nm = svg.querySelector('text.nm');
              return {over, dag: svg.classList[1], dagBox: [Math.round(r.width), Math.round(r.height)], frame: Math.round(fr.width), scale: +scale.toFixed(3),
                      nameFontPx: +(parseFloat(getComputedStyle(nm).fontSize) * scale).toFixed(1), spill, docW: document.documentElement.scrollWidth};
            }""")
            print(w, info)
            await p.locator("#fig-3").screenshot(path=f"{OUT}/own-{w}-dag.png")
            await p.locator("#fig-8").screenshot(path=f"{OUT}/own-{w}-diff.png"); await p.locator("#fig-5").screenshot(path=f"{OUT}/own-{w}-fig5.png")
            await p.close()
        await b.close()
asyncio.run(main())
