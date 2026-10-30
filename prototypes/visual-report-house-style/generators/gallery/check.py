import asyncio, sys
from playwright.async_api import async_playwright
S = sys.argv[1]; P = f"file://{S}/proto/prototypes.html"; G = f"{S}/gallery"
async def main():
    log = open(f"{G}/check.log", "w")
    def L(m): log.write(m + "\n"); log.flush()
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for w, h in [(1440, 900), (768, 1024)]:
            pg = await b.new_page(viewport={"width": w, "height": h})
            errs = []
            pg.on("console", lambda m: m.type == "error" and errs.append(f"console: {m.text}"))
            pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
            pg.on("requestfailed", lambda r: errs.append(f"requestfailed: {r.url} {r.failure}"))
            pg.on("response", lambda r: r.status >= 400 and errs.append(f"HTTP {r.status}: {r.url}"))
            await pg.goto(P); await pg.wait_for_timeout(4000)
            await pg.screenshot(path=f"{G}/gallery-{w}-default.png")
            async def expand(want):
                c = await pg.evaluate("document.body.classList.contains('collapsed')")
                if c == want: await pg.click("#toggle"); await pg.wait_for_timeout(300)
            await expand(True)
            await pg.screenshot(path=f"{G}/gallery-{w}.png")
            ids = await pg.eval_on_selector_all("#list button", "bs => bs.map(b => b.dataset.id)")
            for i in ids:
                errs.clear()
                await expand(True)
                await pg.click(f'#list button[data-id="{i}"]')
                await pg.wait_for_timeout(4500)
                fr = pg.frame_locator("#frame")
                src = await pg.get_attribute("#frame", "src")
                title = await pg.frame(url=lambda u: u.endswith(src)).title() if pg.frame(url=lambda u: u.endswith(src)) else None
                status = "OK" if (title is not None and not errs) else "FAIL"
                L(f"{status} w={w} {i} src={src} title={title!r}")
                for e in errs: L(f"    {e}")
                if w == 1440 or i in ("c", "navy-coral", "navy-coral-v2"):
                    await pg.screenshot(path=f"{G}/entry-{w}-{i}.png")
                if w == 1440:
                    await expand(False)
                    fw = await pg.evaluate("document.getElementById('frame').clientWidth")
                    side = await pg.frame(url=lambda u: u.endswith(src)).evaluate("(() => { const e = document.querySelector('.side'); return e ? getComputedStyle(e).display + ' ' + e.getBoundingClientRect().width : 'no .side'; })()")
                    L(f"    collapsed: iframe width={fw} sidebar={side}")
                    await pg.screenshot(path=f"{G}/collapsed-1440-{i}.png")
            await pg.close()
        # Brief at 768, for comparison with the pre-overwrite screenshot variant-c-768-1.png
        pg = await b.new_page(viewport={"width": 768, "height": 1024})
        await pg.goto(f"file://{S}/proto/variant-c.html"); await pg.wait_for_timeout(4000)
        await pg.screenshot(path=f"{G}/brief-regen-768.png")
        # Pill link check on one page
        await pg.click("text=All prototypes"); await pg.wait_for_timeout(1500)
        L(f"pill navigates to: {pg.url}")
        await b.close()
asyncio.run(main())
