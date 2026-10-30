import asyncio, os
from playwright.async_api import async_playwright
S = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad"
URL = f"file://{S}/proto/variant-navy-coral.html"; OUT = f"{S}/proto/variant-navy-coral-check"
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w in (1440, 768):
            p = await b.new_page(viewport={"width": w, "height": 900})
            await p.goto(URL, wait_until="load")
            await p.wait_for_function("document.querySelectorAll('pre.mermaid svg').length === 2 && document.querySelectorAll('.vega-embed svg.marks').length === 2", timeout=90000)
            await p.wait_for_timeout(600)
            info = await p.evaluate("""() => {
              const over = [...document.querySelectorAll('.figframe, table, .fig .visual, pre.code')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth);
              const dag = document.querySelector('#dag-frame svg').getBoundingClientRect();
              const seq = document.querySelectorAll('pre.mermaid svg')[1].getBoundingClientRect();
              const f = document.querySelector('#dag-frame svg text, #dag-frame svg .nodeLabel'); 
              return {over, dag: [Math.round(dag.width), Math.round(dag.height)], vb: document.querySelector('#dag-frame svg').getAttribute('viewBox'), seq: [Math.round(seq.width), Math.round(seq.height)], docW: document.documentElement.scrollWidth, label: f && getComputedStyle(f).fontSize};
            }""")
            print(w, info)
            for sel, name in (("#s4", "s4"), ("#fig-5", "fig5"), ("#s1", "s1")):
                await p.evaluate(f"document.querySelector('{sel}').scrollIntoView()")
                await p.wait_for_timeout(300)
                await p.screenshot(path=f"{OUT}/own-{w}-{name}.png")
            await p.evaluate("window.scrollTo(0, 0)"); await p.wait_for_timeout(200)
            await p.screenshot(path=f"{OUT}/own-{w}-top.png")
            await p.locator("#fig-3").screenshot(path=f"{OUT}/own-{w}-dag.png")
            await p.close()
        await b.close()
asyncio.run(main())
