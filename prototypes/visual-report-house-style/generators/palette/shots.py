import sys
from playwright.sync_api import sync_playwright
page_path, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (1440, 768):
        pg = b.new_page(viewport={"width": w, "height": 900}, device_scale_factor=1)
        pg.goto("file://" + page_path)
        pg.screenshot(path=f"{out}/shot-v2-{w}.png", full_page=True)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        print(w, "scrollWidth", sw, "height", pg.evaluate("document.documentElement.scrollHeight"))
        if w == 1440:
            pg.locator(".p4").screenshot(path=f"{out}/col-v2-p4.png")
    b.close()
