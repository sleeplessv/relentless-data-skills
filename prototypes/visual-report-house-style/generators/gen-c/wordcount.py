"""Count prose words: answer, stats, prose, captions, so-what, takeaways, markers, limits, legend, dag notes. Excludes tables, code, timeline."""
import sys, re
from bs4 import BeautifulSoup
s = BeautifulSoup(open(sys.argv[1]).read(), "html.parser")
sel = [".answer", ".stat .l", ".prose", ".caption", ".sowhat", ".takeaways", "ol.markers", "ol.limits", ".legend", ".dag-notes", ".byline"]
tot = 0
for q in sel:
    w = sum(len(re.findall(r"\S+", e.get_text(" "))) for e in s.select(q)); tot += w
    print(f"{q:14} {w}")
print("TOTAL", tot)
