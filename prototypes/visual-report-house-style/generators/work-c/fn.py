import asyncio
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); pg = await b.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto("file://" + page_path, wait_until="load"); await pg.wait_for_timeout(1500)
        # sort Table 1 by commits (numeric, first click descending), then by skill
        await pg.click("#table-1 thead th:nth-child(7)")
        print("commits desc:", await pg.evaluate("[...document.querySelectorAll('#table-1 tbody tr')].slice(0,3).map(r=>r.cells[0].textContent+':'+r.cells[6].textContent)"), await pg.evaluate("document.querySelector('#table-1 thead th:nth-child(7)').getAttribute('aria-sort')"))
        await pg.click("#table-1 thead th:nth-child(7)")
        print("commits asc:", await pg.evaluate("[...document.querySelectorAll('#table-1 tbody tr')].slice(0,3).map(r=>r.cells[0].textContent+':'+r.cells[6].textContent)"))
        await pg.click("#table-1 thead th:nth-child(9)")
        print("tracked lines desc:", await pg.evaluate("[...document.querySelectorAll('#table-1 tbody tr')].slice(0,3).map(r=>r.cells[0].textContent+':'+r.cells[8].textContent)"))
        print("tfoot intact:", await pg.evaluate("document.querySelector('#table-1 tfoot td').textContent"))
        # Table 2: visible count, toggle, sort by id asc then check first visible
        print("t2 visible rows:", await pg.evaluate("[...document.querySelectorAll('#table-2 tbody tr')].filter(r=>r.offsetParent!==null).length"))
        await pg.click("details.more summary")
        print("t2 after open:", await pg.evaluate("[...document.querySelectorAll('#table-2 tbody tr')].filter(r=>r.offsetParent!==null).length"))
        await pg.click("details.more summary")
        await pg.click("#table-2 thead th:nth-child(1)")
        print("t2 id asc first 3:", await pg.evaluate("[...document.querySelectorAll('#table-2 tbody:not(.extra) tr')].slice(0,3).map(r=>r.cells[0].textContent)"), await pg.evaluate("document.querySelectorAll('#table-2 tbody:not(.extra) tr').length"), await pg.evaluate("document.querySelectorAll('#table-2 tbody.extra tr').length"))
        # keyboard: focus a th and press ArrowLeft should navigate; test that input focus blocks (none exist); just check handler presence
        print("matrix sort by FAIL:", end=" "); await pg.click("#fig6-table thead th:nth-child(5)"); print(await pg.evaluate("[...document.querySelectorAll('#fig6-table tbody tr')].slice(0,2).map(r=>r.cells[0].textContent)"))
        # vega drawn?
        print("vega:", await pg.evaluate("['#fig1','#fig2'].map(s=>{const e=document.querySelector(s+' svg.marks');return e? e.getAttribute('width')+'x'+e.getAttribute('height')+' paths='+e.querySelectorAll('path').length : 'MISSING'})"))
        await pg.set_viewport_size({"width": 768, "height": 900})
        await pg.wait_for_timeout(800)
        y = await pg.evaluate("document.querySelector('#s6').offsetTop")
        await pg.evaluate(f"window.scrollTo(0,{y})"); await pg.wait_for_timeout(300)
        await pg.screenshot(path="w768-seq.png")
        y = await pg.evaluate("document.querySelector('#s8').offsetTop")
        await pg.evaluate(f"window.scrollTo(0,{y})"); await pg.wait_for_timeout(300)
        await pg.screenshot(path="w768-matrix.png")
        print("pageerrors:", errs)
        await b.close()
asyncio.run(main())
