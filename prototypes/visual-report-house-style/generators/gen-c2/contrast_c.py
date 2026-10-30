"""WCAG check for every colour pair variant-navy-coral-v2 uses. Exit 1 on any failure."""
import sys
def lum(h):
    h = h.lstrip("#"); o = []
    for i in (0, 2, 4):
        c = int(h[i:i+2], 16) / 255
        o.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126*o[0] + 0.7152*o[1] + 0.0722*o[2]
def ratio(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True); return (x + .05) / (y + .05)
T = dict(paper="#ffffff", ink="#102542", muted="#5f5348", surface="#f4f7f7", line="#e1e7e7", rule="#7b8786",
         coral_text="#c2493a", coral_fill="#f87060", coral_line="#d95646", coral_soft="#fff1ed",
         th_bg="#edf1f1", bar="#dce4e3", zebra="#f7f9f9",
         code_fg="#24514e", code_pill="#cdd7d6", code_bg="#eef3f3", gutter_bg="#e2eaea", gutter="#4a5755", mark_bg="#e3e9f2",
         red="#a3123a", red_soft="#fbe7ec", red_text="#8c0f32", amber="#b7791f", amber_soft="#fcf2dd", amber_text="#714800",
         p2_label="#1a759f", p2_ink="#102a3f", p2_border="#184e77", sage="#4f7f7c", taupe="#8a7766",
         dag_cat_root="#edf1f1", dag_ci="#e3e8f0", dag_test="#f3efeb", dag_group="#edf1f1", white="#ffffff", hover="#e6ecec", mark_gutter="#d5deeb",
         # v2: GitHub light diff colours (inside diffs only); the del word tint is #ff818266 composited on #ffebe9
         gh_fg="#1f2328", gh_num="#57606a", gh_add="#e6ffec", gh_add_num="#ccffd8", gh_add_word="#abf2bc", gh_add_sign="#1a7f37",
         gh_del="#ffebe9", gh_del_num="#ffd7d5", gh_del_word="#ffc1c0", gh_del_sign="#d1242f", gh_hunk="#ddf4ff", gh_hunk_fg="#57606a",
         # v2: DAG tag badges
         tag_ci="#1a759f", tag_scr="#4f7f7c", tag_tst="#5f5348", tag_sks="#24514e", tag_ref="#4a5755")
PAIRS = [  # label, fg, bg, kind
 ("body text", "ink", "paper", "text"), ("muted text / captions how", "muted", "paper", "text"),
 ("coral labels (fig no, so what)", "coral_text", "paper", "text"),
 ("takeaways text", "ink", "surface", "text"), ("takeaways label", "ink", "surface", "text"), ("muted on surface", "muted", "surface", "text"),
 ("sidebar current text", "ink", "coral_soft", "text"), ("sidebar current number", "ink", "coral_soft", "text"),
 ("sidebar number", "muted", "paper", "text"),
 ("table header text", "ink", "th_bg", "text"), ("table cell over bar", "ink", "bar", "text"), ("table zebra text", "ink", "zebra", "text"),
 ("table zebra muted", "muted", "zebra", "text"),
 ("highlight cell numeral", "ink", "coral_fill", "text"), ("in-cell bar vs paper", "bar", "paper", "decor"),
 ("inline code", "code_fg", "code_pill", "text"), ("code panel text", "code_fg", "code_bg", "text"),
 ("code gutter numbers", "gutter", "gutter_bg", "text"), ("code text on marked line", "code_fg", "mark_bg", "text"),
 ("gutter on marked line", "ink", "mark_bg", "text"),
 ("problem text", "red", "paper", "text"), ("problem callout text", "red_text", "red_soft", "text"),
 ("note callout text", "amber_text", "amber_soft", "text"), ("note border", "amber", "paper", "graphic"),
 ("ANSWER (P2) claim", "p2_ink", "paper", "text"), ("ANSWER (P2) label", "p2_label", "paper", "text"),
 ("ANSWER (P2) border", "p2_border", "paper", "graphic"), ("answer inline code", "code_fg", "code_pill", "text"),
 ("timeline key text", "ink", "coral_soft", "text"), ("timeline key date", "ink", "coral_soft", "text"),
 ("timeline key code", "ink", "coral_fill", "text"), ("timeline note", "muted", "coral_soft", "text"),
 ("chart series navy", "ink", "paper", "graphic"), ("chart series coral", "coral_line", "paper", "graphic"),
 ("chart axis labels", "muted", "paper", "text"),
 ("DAG node text (white)", "ink", "white", "text"), ("DAG focus text", "ink", "coral_fill", "text"),
 ("DAG root-script text", "ink", "dag_cat_root", "text"), ("DAG CI text", "ink", "dag_ci", "text"),
 ("DAG test text", "ink", "dag_test", "text"), ("DAG script text", "code_fg", "code_bg", "text"),
 ("DAG navy border", "ink", "paper", "graphic"), ("DAG sage border", "sage", "paper", "graphic"),
 ("DAG taupe border", "taupe", "paper", "graphic"), ("DAG teal border", "code_fg", "paper", "graphic"),
 ("DAG coral border", "coral_line", "paper", "graphic"), ("DAG edge", "rule", "paper", "graphic"),
 ("matrix PASS mark", "ink", "paper", "graphic"), ("matrix FAIL mark", "red", "paper", "graphic"),
 ("matrix BLOCKED mark", "muted", "paper", "graphic"),
 ("sidebar current title", "white", "ink", "text"), ("sidebar current number (coral on navy)", "coral_fill", "ink", "text"),
 ("sidebar link on hover", "ink", "hover", "text"), ("sidebar muted link", "muted", "surface", "text"),
 ("marked gutter number", "ink", "mark_gutter", "text"), ("stat label on surface", "muted", "surface", "text"),
 ("table hover row text", "ink", "coral_soft", "text"), ("switcher text", "white", "ink", "text"),
 ("seq actor text", "ink", "th_bg", "text"), ("seq number on navy", "white", "ink", "text"),
 # v2 diff (Figure 8)
 ("diff added text", "gh_fg", "gh_add", "text"), ("diff added word", "gh_fg", "gh_add_word", "text"),
 ("diff added + sign", "gh_add_sign", "gh_add", "text"), ("diff added line no.", "gh_num", "gh_add_num", "text"),
 ("diff removed text", "gh_fg", "gh_del", "text"), ("diff removed word", "gh_fg", "gh_del_word", "text"),
 ("diff removed - sign", "gh_del_sign", "gh_del", "text"), ("diff removed line no.", "gh_num", "gh_del_num", "text"),
 ("diff hunk header", "gh_hunk_fg", "gh_hunk", "text"), ("diff context text", "code_fg", "code_bg", "text"),
 ("diff context line no.", "gutter", "gutter_bg", "text"), ("annotation marker numeral (Fig 5, Fig 8, notes)", "white", "ink", "text"),
 ("annotation marker on slate tint", "ink", "mark_bg", "graphic"), ("annotation marker on diff add", "ink", "gh_add", "graphic"),
 ("annotation marker on diff del", "ink", "gh_del", "graphic"), ("annotation marker on code panel", "ink", "code_bg", "graphic"),
 # v2 DAG nodes (Figure 3)
 ("DAG node name", "ink", "white", "text"), ("DAG node caption", "muted", "white", "text"),
 ("DAG focus name", "ink", "coral_soft", "text"), ("DAG focus caption", "muted", "coral_soft", "text"),
 ("DAG focus badge", "ink", "coral_fill", "text"), ("DAG focus border", "coral_line", "surface", "graphic"),
 ("DAG SKL badge", "white", "ink", "text"), ("DAG SCR badge", "white", "tag_scr", "text"), ("DAG CI badge", "white", "tag_ci", "text"),
 ("DAG TST badge", "white", "tag_tst", "text"), ("DAG SKS badge", "white", "tag_sks", "text"), ("DAG REF badge", "tag_ref", "white", "text"),
 ("DAG group count", "ink", "th_bg", "text"), ("DAG node border on canvas", "rule", "surface", "graphic"),
 ("DAG edge on canvas", "rule", "surface", "graphic"), ("legend group swatch", "rule", "paper", "graphic"),
 ("legend label", "muted", "paper", "text"),
]
MIN = {"text": 4.5, "large": 3.0, "graphic": 3.0, "decor": 1.0}
ok = True
for lab, f, b, k in PAIRS:
    r = ratio(T[f], T[b]); res = "PASS" if r >= MIN[k] else "FAIL"; ok &= res == "PASS"
    print(f"{lab:34} {T[f]} on {T[b]}  {r:5.2f}  min {MIN[k]}  {res}")
print("ALL PASS" if ok else "SOME FAIL"); sys.exit(0 if ok else 1)
