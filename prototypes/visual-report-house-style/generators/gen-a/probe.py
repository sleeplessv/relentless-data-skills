import asyncio, pathlib
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); p = await b.new_page(viewport={"width":1280,"height":900})
        await p.goto("file://" + str(pathlib.Path("variant-a.html").resolve()))
        await p.wait_for_function("document.querySelectorAll('#figure-3 svg').length > 0", timeout=90000)
        await p.wait_for_timeout(1500)
        print(await p.evaluate('''() => {
          const f = document.querySelector("#figure-3 .frame");
          const svg = f.querySelector("svg");
          const ids = Array.from(svg.querySelectorAll("g.node, g[id*='lint']")).slice(0,5).map(g => g.id + "|" + g.className.baseVal);
          const lab = Array.from(svg.querySelectorAll("*")).filter(e => (e.textContent||"").trim() === "scripts/lint_skill.py").map(e => e.tagName + "#" + e.id + "." + (e.getAttribute("class")||"")).slice(0,6);
          return {scrollLeft: f.scrollLeft, scrollTop: f.scrollTop, clientW: f.clientWidth, clientH: f.clientHeight, scrollW: f.scrollWidth, scrollH: f.scrollHeight, ids, lab};
        }'''))
        await b.close()
asyncio.run(main())
