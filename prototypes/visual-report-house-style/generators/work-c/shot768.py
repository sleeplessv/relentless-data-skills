import asyncio
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
out = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/work-c/"
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); pg = await b.new_page(viewport={"width": 768, "height": 900})
        await pg.goto("file://" + page_path, wait_until="load")
        await pg.wait_for_timeout(6000)
        h = await pg.evaluate("document.documentElement.scrollHeight")
        print("768 height", h)
        for i, y in enumerate([0, 900, 1800, 4200, 6300]):
            await pg.evaluate(f"window.scrollTo(0,{y})"); await pg.wait_for_timeout(200)
            await pg.screenshot(path=f"{out}w768-{i}.png")
        # also print document scrollWidth to detect horizontal page scroll
        print("scrollWidth", await pg.evaluate("document.documentElement.scrollWidth"))
        await b.close()
asyncio.run(main())
