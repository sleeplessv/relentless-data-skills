import asyncio
from playwright.async_api import async_playwright
URL = "file:///private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-b.html"
OUT = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/gen-b/shots"
import os; os.makedirs(OUT, exist_ok=True)
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        p = await b.new_page(viewport={"width":1280,"height":900})
        await p.goto(URL, wait_until="load")
        await p.wait_for_function("document.querySelectorAll('pre.mermaid svg').length === 2 && document.querySelectorAll('.vega-embed svg.marks').length === 2", timeout=90000)
        await p.wait_for_timeout(500)
        info = await p.evaluate("""() => {
          const svgs = [...document.querySelectorAll('pre.mermaid svg')].map(s => { const r = s.getBoundingClientRect(); return {vb: s.getAttribute('viewBox'), w: r.width, h: r.height, font: getComputedStyle(s.querySelector('text')||s).fontSize}; });
          const vega = [...document.querySelectorAll('.vega-embed svg.marks')].map(s => ({w: s.getAttribute('width'), h: s.getAttribute('height'), paths: s.querySelectorAll('path').length}));
          const over = [...document.querySelectorAll('table, .fig .visual')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth);
          const seqText = [...document.querySelectorAll('pre.mermaid')[1].querySelectorAll('text')].map(t => t.getBoundingClientRect().height).filter(Boolean);
          return {svgs, vega, over, seqMinText: Math.min(...seqText), seqMaxText: Math.max(...seqText), docW: document.documentElement.scrollWidth};
        }""")
        print("1280:", info)
        # sidebar highlight after scrolling to section 4 and 6
        for sid in ("s4", "s6", "s7"):
            await p.evaluate(f"document.getElementById('{sid}').scrollIntoView()")
            await p.wait_for_timeout(300)
            cur = await p.evaluate("(document.querySelector('#toc a.current')||{}).textContent")
            print("scrolled to", sid, "-> current:", cur and cur.strip())
        # sort check: click SKILL.md column twice on table-1, read first cell
        await p.evaluate("document.getElementById('table-1').scrollIntoView()")
        th = p.locator("#table-1 thead th").nth(2)
        await th.click(); await p.wait_for_timeout(100)
        first = await p.evaluate("document.querySelector('#table-1 tbody tr td').textContent + ' / ' + document.querySelector('#table-1 thead th[aria-sort]').getAttribute('aria-sort')")
        await th.click(); await p.wait_for_timeout(100)
        second = await p.evaluate("document.querySelector('#table-1 tbody tr td').textContent + ' / ' + document.querySelector('#table-1 thead th[aria-sort]').getAttribute('aria-sort')")
        print("sort asc:", first, "| desc:", second)
        # table-2 sort by label then count main rows
        await p.locator("#table-2 thead th").nth(1).click(); await p.wait_for_timeout(100)
        print("table-2 after sort: main rows", await p.evaluate("document.querySelectorAll('#t2-main tr').length"), "rest rows", await p.evaluate("document.querySelectorAll('#t2-rest tr').length"), "rest hidden", await p.evaluate("document.getElementById('t2-rest').hidden"))
        # DAG natural size screenshot
        await p.evaluate("document.getElementById('dag-expand').click()")
        await p.set_viewport_size({"width": 2000, "height": 1800})
        await p.wait_for_timeout(300)
        svg = p.locator("#dag-frame svg")
        await svg.screenshot(path=f"{OUT}/dag-natural.png")
        await p.set_viewport_size({"width": 1280, "height": 900})
        await p.evaluate("document.getElementById('dag-expand').click()")
        # sequence region screenshot
        await p.locator("#fig-4 .figframe").screenshot(path=f"{OUT}/seq-fit.png")
        # narrower viewports
        for w in (1000, 768):
            await p.set_viewport_size({"width": w, "height": 900})
            await p.wait_for_timeout(600)
            await p.evaluate("window.scrollTo(0,0)")
            await p.screenshot(path=f"{OUT}/top-{w}.png")
            await p.evaluate("document.getElementById('table-1-fig').scrollIntoView()")
            await p.wait_for_timeout(200)
            await p.screenshot(path=f"{OUT}/table1-{w}.png")
            await p.evaluate("document.getElementById('fig-5').scrollIntoView()")
            await p.wait_for_timeout(200)
            await p.screenshot(path=f"{OUT}/fig5-{w}.png")
            print(w, "docW", await p.evaluate("document.documentElement.scrollWidth"), "overflow:", await p.evaluate("[...document.querySelectorAll('table, .fig .visual, .answer, .stats')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth)"))
        await b.close()
asyncio.run(main())
