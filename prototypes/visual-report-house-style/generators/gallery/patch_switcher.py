import re, sys
for path in sys.argv[1:]:
    s = open(path).read()
    nav = re.search(r'<nav class="(switcher|proto-switch)" aria-label="Prototype switcher">.*?</nav>', s, re.S)
    assert nav, path
    cls = nav.group(1)
    style = ' style="width:auto;padding:0 0.8rem;border-radius:999px"' if 'circle' or True else ''
    new = (f'<nav class="{cls}" aria-label="Prototype navigation">\n'
           f'  <a href="prototypes.html" target="_top"{style if cls=="switcher" else ""}>&larr; All prototypes</a>\n</nav>')
    s = s[:nav.start()] + new + s[nav.end():]
    s, n = re.subn(r'  // (Prototype switcher: arrow keys[^\n]*|---- prototype switcher keys ----)\n  document\.addEventListener\("keydown".*?\n  \}\);\n', '', s, flags=re.S)
    assert n == 1, (path, n)
    open(path, "w").write(s); print("patched", path, cls)
