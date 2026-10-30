import asyncio, re, sys, html
from playwright.async_api import async_playwright
page_path = "/private/tmp/claude-501/-Users-tumul-projects-repo-relentless-data-skills/8c044738-6885-4c97-9673-1ff9b4ed85db/scratchpad/proto/variant-c.html"
src = open(page_path).read()
blocks = re.findall(r'<pre class="mermaid">\n(.*?)\n</pre>', src, re.S)
print("blocks:", len(blocks))
JS = """
async ([sources]) => {
  const mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs")).default;
  const elk = (await import("https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs")).default;
  mermaid.registerLayoutLoaders(elk);
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
  const out = [];
  for (let i = 0; i < sources.length; i++) {
    try {
      const t0 = performance.now();
      const r = await mermaid.render("probe" + i, sources[i]);
      const m = r.svg.match(/viewBox="([^"]+)"/);
      out.push({ i, ok: true, ms: Math.round(performance.now() - t0), viewBox: m && m[1], len: r.svg.length });
    } catch (e) {
      out.push({ i, ok: false, err: String(e && (e.message || e)).slice(0, 600) });
    }
  }
  return out;
}
"""
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page()
        pg.on("pageerror", lambda e: print("pageerror:", str(e)[:400]))
        await pg.goto("file://" + page_path, wait_until="load")
        res = await pg.evaluate(JS, [[html.unescape(x) for x in blocks]])
        for r in res: print(r)
        await b.close()
asyncio.run(main())
