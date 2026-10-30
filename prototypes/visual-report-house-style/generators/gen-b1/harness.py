import asyncio, sys
from playwright.async_api import async_playwright
PROTO = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto"
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for v in ("b1", "b2"):
            p = await b.new_page(viewport={"width":1280,"height":900})
            await p.goto(f"file://{PROTO}/variant-{v}.html", wait_until="load")
            await p.wait_for_function("document.querySelectorAll('pre.mermaid svg').length === 2 && document.querySelectorAll('.vega-embed svg.marks').length === 2", timeout=90000)
            await p.wait_for_timeout(600)
            info = await p.evaluate("""() => {
              const svgs = [...document.querySelectorAll('pre.mermaid svg')].map(s => { const r = s.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), minFont: Math.min(...[...s.querySelectorAll('text')].map(t => t.getBoundingClientRect().height).filter(Boolean)).toFixed(1)}; });
              const vega = [...document.querySelectorAll('.vega-embed svg.marks')].map(s => ({w: s.getAttribute('width'), h: s.getAttribute('height'), paths: s.querySelectorAll('path').length}));
              const over = [...document.querySelectorAll('table, .fig .visual, .figframe')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth);
              const dag = document.querySelector('#dag-frame'); const dr = dag.getBoundingClientRect();
              const side = document.querySelector('.side').getBoundingClientRect(); const content = document.querySelector('.content').getBoundingClientRect();
              const last = document.querySelector('#s9').getBoundingClientRect();
              const pill = document.querySelector('.proto-switch').getBoundingClientRect();
              return {svgs, vega, over, dagFrame: Math.round(dr.width), sideRight: side.right, contentLeft: content.left, docW: document.documentElement.scrollWidth, docH: document.documentElement.scrollHeight, pillH: pill.height, lastBottom: last.bottom + window.scrollY};
            }""")
            print(v, info)
            # sticky stacking: scroll into Table 1
            await p.evaluate("window.scrollTo(0, document.getElementById('table-1-fig').getBoundingClientRect().top + window.scrollY + 260)")
            await p.wait_for_timeout(300)
            await p.screenshot(path=f"{PROTO}/variant-{v}-sticky.png")
            print(v, "current toc:", (await p.evaluate("(document.querySelector('#toc a.current')||{}).textContent") or "").strip())
            # bottom of page: pill vs last section
            await p.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await p.wait_for_timeout(300)
            await p.screenshot(path=f"{PROTO}/variant-{v}-bottom.png")
            gap = await p.evaluate("(() => { const l = document.querySelector('#s9 ol.limits').getBoundingClientRect(); const pl = document.querySelector('.proto-switch').getBoundingClientRect(); return Math.round(pl.top - l.bottom); })()")
            print(v, "gap between last list and pill top (px):", gap)
            # 768 first viewport
            await p.set_viewport_size({"width":768, "height":1024})
            await p.wait_for_timeout(600)
            await p.evaluate("window.scrollTo(0,0)")
            await p.screenshot(path=f"{PROTO}/variant-{v}-768-1.png")
            print(v, "768 docW", await p.evaluate("document.documentElement.scrollWidth"), "overflow:", await p.evaluate("[...document.querySelectorAll('table, .fig .visual, .figframe, .answer, .stats')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth)"))
            await p.close()
        await b.close()
asyncio.run(main())
