import asyncio
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); pg = await b.new_page(viewport={"width": 1280, "height": 900})
        await pg.goto("file://" + page_path, wait_until="load"); await pg.wait_for_timeout(1500)
        vis = "[...document.querySelectorAll('#table-2 tbody tr')].filter(r=>r.offsetParent!==null).length"
        print("before:", await pg.evaluate(vis))
        await pg.click("details.more summary"); await pg.wait_for_timeout(300)
        print("after open:", await pg.evaluate(vis), await pg.evaluate("document.querySelector('details.more').open"))
        await pg.click("details.more summary"); await pg.wait_for_timeout(300)
        print("after close:", await pg.evaluate(vis))
        await pg.click("#fig6-table thead th:nth-child(5)")
        print("matrix FAIL desc:", await pg.evaluate("[...document.querySelectorAll('#fig6-table tbody tr')].slice(0,3).map(r=>r.cells[0].textContent)"))
        await b.close()
asyncio.run(main())
