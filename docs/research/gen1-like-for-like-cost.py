#!/usr/bin/env python3
"""Like-for-like cost of sessions with and without the implement/orchestrator stack.

Usage: python3 like_for_like.py RUN_DIR [--no-fetch | --no-graphql]

Reads RUN_DIR/usage-sessions.csv written by usage_scan.py (the version that
adds a pr_urls column), fetches each PR's size and post-open history with
read-only gh GraphQL calls (cached in RUN_DIR/pr-cache/), and writes
  RUN_DIR/l4l-prs.csv        one row per PR attributed to a session
  RUN_DIR/l4l-sessions.csv   one row per session in the size comparison
  RUN_DIR/l4l-tables.md      every table the note quotes
Groups: "stack" = run_session 1 (orchestrator-mode or an implement-* skill in
the main thread); "direct" = no such skill and a commit or PR seen.
"""
import collections, concurrent.futures as cf, csv, datetime as dt, json, os, re, subprocess, sys

RUN = sys.argv[1]
FETCH = '--no-fetch' not in sys.argv
GRAPHQL = FETCH and '--no-graphql' not in sys.argv   # skip uncached PR detail fetches (GraphQL rate limit)
CACHE = os.path.join(RUN, 'pr-cache'); os.makedirs(CACHE, exist_ok=True)
URL_RE = re.compile(r'https://github\.com/([^/]+)/([^/]+)/pull/(\d+)$')
OPEN_GRACE = dt.timedelta(minutes=2)      # PR must be created inside the session (start - grace, end + 5 min)
HANDOFF_GRACE = dt.timedelta(minutes=5)   # commits later than session end + this are post-hand-off
FAIL = {'FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE', 'ACTION_REQUIRED', 'ERROR'}

Q = '''query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){
 number createdAt mergedAt closedAt state isDraft additions deletions changedFiles author{login}
 commits(first:100){totalCount nodes{commit{oid committedDate
   status{contexts{state context}}
   checkSuites(first:6){nodes{app{slug} checkRuns(first:25){nodes{name conclusion status}}}}}}}
 reviews(first:50){nodes{state submittedAt}}
 timelineItems(first:50,itemTypes:[READY_FOR_REVIEW_EVENT,HEAD_REF_FORCE_PUSHED_EVENT]){nodes{__typename
   ... on ReadyForReviewEvent{createdAt} ... on HeadRefForcePushedEvent{createdAt}}}}}}'''

def gh(argv):
    """Run gh read-only; back off on GitHub's secondary rate limit (the token is shared with other sessions)."""
    import time
    for wait in (0, 30, 60, 120):
        time.sleep(wait)
        p = subprocess.run(['gh'] + argv, capture_output=True, text=True)
        if 'rate limit' not in (p.stdout + p.stderr).lower(): return p
    return p

def ts(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None

ACCESS_PATH = os.path.join(CACHE, 'repo-access.json')
ACCESS = json.load(open(ACCESS_PATH)) if os.path.exists(ACCESS_PATH) else {}
def can_read(repo):
    if repo not in ACCESS and FETCH:
        p = subprocess.run(['gh', 'api', 'repos/' + repo, '--jq', '.full_name'], capture_output=True, text=True)
        if p.returncode == 0: ACCESS[repo] = True
        elif 'Not Found' in p.stdout + p.stderr: ACCESS[repo] = False
        else: return False                     # transient (rate limit, network): not cached, rerun to retry
        json.dump(ACCESS, open(ACCESS_PATH, 'w'))
    return ACCESS.get(repo, False)

def fetch(url):
    o, r, n = URL_RE.match(url).groups()
    path = os.path.join(CACHE, '%s__%s__%s.json' % (o, r, n))
    if os.path.exists(path): return url, json.load(open(path))
    if not can_read(o + '/' + r): return url, {'error': 'repository not readable with this gh account'}
    if not GRAPHQL: return url, {'error': 'not cached'}
    p = gh(['api', 'graphql', '-f', 'query=' + Q, '-f', 'o=' + o, '-f', 'r=' + r, '-F', 'n=' + n],
                       )
    try: d = json.loads(p.stdout)
    except ValueError: d = {'error': (p.stderr or p.stdout)[:300]}
    pr = (((d.get('data') or {}).get('repository') or {}).get('pullRequest'))
    res = pr if pr else {'error': json.dumps(d.get('errors', d.get('error', '')))[:300]}
    if 'RATE_LIMIT' not in res.get('error', ''): json.dump(res, open(path, 'w'))
    return url, res

rows = list(csv.DictReader(open(os.path.join(RUN, 'usage-sessions.csv'))))
def group(r):
    if r['run_session'] == '1': return 'stack'
    if int(r['commits']) or int(r['prs_created']): return 'direct'
    return None
sess = [dict(r, group=group(r)) for r in rows if group(r)]
urls = sorted({u for r in sess for u in r['pr_urls'].split('|') if URL_RE.match(u or '')})
for repo in sorted({'%s/%s' % URL_RE.match(u).groups()[:2] for u in urls}): can_read(repo)
with cf.ThreadPoolExecutor(1) as ex: PR = dict(ex.map(fetch, urls))

def checks(commit):
    runs = [cr for s in commit['checkSuites']['nodes'] for cr in s['checkRuns']['nodes']]
    ctx = (commit.get('status') or {}).get('contexts') or []
    failed = [c['name'] for c in runs if c['conclusion'] in FAIL] + [c['context'] for c in ctx if c['state'] in FAIL]
    return len(runs) + len(ctx), failed

pr_rows = []; claimed = {}
sess.sort(key=lambda r: r['start'])
for r in sess:
    st, en = ts(r['start']), ts(r['end'])
    r['n_urls'] = 0; r['prs'] = []; r['pr_unreadable'] = 0; r['pr_outside'] = 0
    for u in [u for u in r['pr_urls'].split('|') if URL_RE.match(u or '')]:
        r['n_urls'] += 1
        pr = PR.get(u, {})
        if 'error' in pr: r['pr_unreadable'] += 1; continue
        c = ts(pr['createdAt'])
        if not (st - OPEN_GRACE <= c <= en + HANDOFF_GRACE) or u in claimed:
            r['pr_outside'] += 1; continue   # listed, not opened, by this session (or already attributed)
        claimed[u] = r['session_id']
        commits = [x['commit'] for x in pr['commits']['nodes']]
        after_open = [x for x in commits if ts(x['committedDate']) > c]
        after_end = [x for x in commits if ts(x['committedDate']) > en + HANDOFF_GRACE]
        handoff = [x for x in commits if ts(x['committedDate']) <= en + HANDOFF_GRACE]
        n_checks = 0; failed_any = 0; failed_commits = 0
        for x in commits:
            n, f = checks(x); n_checks += n; failed_any += len(f); failed_commits += bool(f)
        hand_fail = len(checks(handoff[-1])[1]) if handoff else 0
        ready = [ts(t['createdAt']) for t in pr['timelineItems']['nodes'] if t['__typename'] == 'ReadyForReviewEvent']
        ready_at = min(ready) if ready else c   # drafts: when marked ready; others: when opened
        after_ready = [x for x in commits if ts(x['committedDate']) > ready_at + HANDOFF_GRACE]
        failed_after_ready = sum(len(checks(x)[1]) for x in commits if ts(x['committedDate']) >= ready_at - HANDOFF_GRACE)
        cr = sum(1 for v in pr['reviews']['nodes'] if v['state'] == 'CHANGES_REQUESTED')
        merged = bool(pr['mergedAt'])
        d = dict(session_id=r['session_id'], group=r['group'], url=u, created=pr['createdAt'], merged=int(merged),
                 state=pr['state'], additions=pr['additions'], deletions=pr['deletions'], files=pr['changedFiles'],
                 commits=pr['commits']['totalCount'], commits_after_first=max(0, pr['commits']['totalCount'] - 1),
                 commits_after_open=len(after_open), commits_after_session=len(after_end),
                 check_runs=n_checks, failed_check_runs=failed_any, commits_with_failed_check=failed_commits,
                 failed_checks_at_handoff=hand_fail, opened_as_draft=int(bool(ready)), commits_after_ready=len(after_ready), change_requests=cr,
                 force_pushes=sum(1 for t in pr['timelineItems']['nodes'] if t['__typename'] == 'HeadRefForcePushedEvent'))
        # strict: merged, nothing pushed after opening, no failed check anywhere, no change request
        d['first_pass_strict'] = int(merged and not after_open and not failed_any and not cr)
        # hand-off: merged, no commit after the opening session ended, the commit it handed off passed its checks, no change request
        d['first_pass_handoff'] = int(merged and not after_end and not hand_fail and not cr)
        # ready: merged, no commit after it was opened for review (drafts: marked ready), no change request
        d['first_pass_ready'] = int(merged and not after_ready and not cr)
        d['repo'] = '%s/%s' % URL_RE.match(u).groups()[:2]; d['number'] = pr['number']; 
        d['session_end'] = r['end']; d['project'] = r['project']
        pr_rows.append(d); r['prs'].append(d)

# follow-up fix PRs: a later PR in the same repo, opened within 7 days, titled fix/revert/hotfix, that touches a file this PR
# touched (loose) and also names this PR as #N in its title or body (tight)
def repo_prs(repo):
    """Titles and creation times of the repo's PRs since 2026-10-14 (REST, core quota)."""
    path = os.path.join(CACHE, 'pulls2__' + repo.replace('/', '__') + '.json')
    if os.path.exists(path): return repo, json.load(open(path))
    if not FETCH: return repo, []
    p = gh(['api', '--paginate', 'repos/%s/pulls?state=all&per_page=100&sort=created&direction=desc' % repo,
            '--jq', '.[] | select(.created_at >= "2026-10-14") | {number, title, createdAt: .created_at, refs: [((.title // "") + " " + (.body // "")) | scan("#[0-9]+")]}'])
    if p.returncode: return repo, []          # not cached: rerun to retry
    d = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    json.dump(d, open(path, 'w')); return repo, d
def pr_files(repo, n):
    path = os.path.join(CACHE, 'files__%s__%s.json' % (repo.replace('/', '__'), n))
    if os.path.exists(path): return set(json.load(open(path)))
    if not FETCH: return None
    p = gh(['api', '--paginate', 'repos/%s/pulls/%s/files?per_page=100' % (repo, n), '--jq', '.[].filename'])
    if p.returncode: return None
    fs = [l for l in p.stdout.splitlines() if l.strip()]
    json.dump(fs, open(path, 'w')); return set(fs)
with cf.ThreadPoolExecutor(1) as ex: LIST = dict(ex.map(repo_prs, sorted({p['repo'] for p in pr_rows})))
FIX_RE = re.compile(r'^\s*(fix|revert|hotfix)\b', re.I)
for d in pr_rows:
    lst = LIST.get(d['repo'], [])
    c = ts(d['created'])
    cand = [x for x in lst if x['number'] != d['number'] and c < ts(x['createdAt']) <= c + dt.timedelta(days=7) and FIX_RE.match(x['title'])]
    mine = pr_files(d['repo'], d['number']) if cand else set()
    fu = [x for x in cand if mine and mine & (pr_files(d['repo'], x['number']) or set())]
    tight = [x for x in fu if '#%s' % d['number'] in x.get('refs', [])]
    d['files_known'] = int(bool(lst)); d['followup_fix_prs_loose'] = len(fu); d['followup_fix_prs'] = len(tight)
    d['first_pass_ready_nofix'] = int(d['first_pass_ready'] and not tight)

with open(os.path.join(RUN, 'l4l-prs.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(pr_rows[0])); w.writeheader(); w.writerows(pr_rows)

TOKEN_HARNESS = {'claude-code', 'claude-code-work', 'codex'}
def bucket(lines):
    return 'S <=50' if lines <= 50 else 'M 51-300' if lines <= 300 else 'L 301-1500' if lines <= 1500 else 'XL >1500'
BUCKETS = ['S <=50', 'M 51-300', 'L 301-1500', 'XL >1500']
cmp_rows = []
for r in sess:
    if not r['prs']: continue
    lines = sum(p['additions'] + p['deletions'] for p in r['prs'])
    tok = r['harness'] in TOKEN_HARNESS
    cmp_rows.append(dict(session_id=r['session_id'], group=r['group'], harness=r['harness'], project=r['project'],
        n_prs=len(r['prs']), multi_pr=int(len(r['prs']) > 1), lines=lines,
        additions=sum(p['additions'] for p in r['prs']), deletions=sum(p['deletions'] for p in r['prs']),
        files=sum(p['files'] for p in r['prs']), bucket=bucket(lines), tokens_recorded=int(tok),
        total_tokens=int(r['total_tokens']) if tok else '',
        tokens_no_cache_read=(int(r['input_tokens']) + int(r['output_tokens']) + int(r['cache_creation_tokens'])) if tok else '',
        output_tokens=int(r['output_tokens']) if tok else '',
        active_min=float(r['active_min']), subagent_calls=int(r['subagent_calls']), interventions=int(r['interventions']),
        fp_strict=int(all(p['first_pass_strict'] for p in r['prs'])), fp_handoff=int(all(p['first_pass_handoff'] for p in r['prs'])),
        fp_ready=int(all(p['first_pass_ready'] for p in r['prs'])), fp_ready_nofix=int(all(p['first_pass_ready_nofix'] for p in r['prs'])),
        merged_all=int(all(p['merged'] for p in r['prs']))))
with open(os.path.join(RUN, 'l4l-sessions.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(cmp_rows[0])); w.writeheader(); w.writerows(cmp_rows)

# ---------------- tables ----------------
def q(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)
def f(x):
    if abs(x) >= 1e6: return '%.1fM' % (x / 1e6)
    if abs(x) >= 1e4: return '%.0fk' % (x / 1e3)
    return ('%.1f' % x).rstrip('0').rstrip('.')
def cell(xs):
    xs = [x for x in xs if x != '']
    if not xs: return 'n=0'
    return 'n=%d: %s [%s-%s]' % (len(xs), f(q(xs, .5)), f(q(xs, .25)), f(q(xs, .75)))
md = ['# like_for_like.py tables\n']
def table(title, header, data):
    md.append('\n### ' + title + '\n'); md.append('| ' + ' | '.join(header) + ' |'); md.append('|' + '---|' * len(header))
    for row in data: md.append('| ' + ' | '.join(str(x) for x in row) + ' |')

ss = collections.Counter(); 
for r in sess:
    g = r['group']
    ss[(g, 'sessions')] += 1
    ss[(g, 'with a PR URL in gh pr create output')] += bool(r['n_urls'])
    ss[(g, 'no PR URL (out of size comparison)')] += not r['n_urls']
    ss[(g, 'PR URL(s) but none readable with gh')] += bool(r['n_urls']) and r['pr_unreadable'] == r['n_urls']
    ss[(g, 'readable URL(s) but none created inside the session')] += bool(r['n_urls']) and not r['prs'] and r['pr_unreadable'] < r['n_urls']
    ss[(g, 'in size comparison (>=1 PR opened in session)')] += bool(r['prs'])
    ss[(g, '  of which opened >1 PR (sizes summed)')] += len(r['prs']) > 1
labels = ['sessions', 'with a PR URL in gh pr create output', 'no PR URL (out of size comparison)', 'PR URL(s) but none readable with gh',
          'readable URL(s) but none created inside the session', 'in size comparison (>=1 PR opened in session)', '  of which opened >1 PR (sizes summed)']
table('L1 Session funnel', ['step', 'stack', 'direct'], [(l, ss[('stack', l)], ss[('direct', l)]) for l in labels])
uu = collections.Counter('unreadable' if 'error' in PR[u] else 'read' for u in urls)
table('L1b PR URLs seen', ['state', 'urls'], sorted(uu.items()) + [('attributed to an opening session', len(pr_rows))])

table('L2 Size distribution of compared sessions (changed lines = additions + deletions)', ['group', 'n', 'p10', 'p25', 'median', 'p75', 'p90', 'files median'],
      [(g, len(xs), *[f(q(xs, p)) for p in (.1, .25, .5, .75, .9)], f(q([c['files'] for c in cmp_rows if c['group'] == g], .5)))
       for g in ('stack', 'direct') for xs in [[c['lines'] for c in cmp_rows if c['group'] == g]]])

mets = [('total_tokens', 'total tokens incl. cache'), ('tokens_no_cache_read', 'tokens excl. cache reads'), ('output_tokens', 'output tokens'),
        ('active_min', 'active minutes'), ('subagent_calls', 'subagent calls'), ('interventions', 'user prompts after the start'), ('lines', 'changed lines'), ('files', 'files changed')]
def cost_table(title, rows_):
    data = []
    for b in BUCKETS:
        for m, lab in mets:
            data.append((b, lab, cell([c[m] for c in rows_ if c['bucket'] == b and c['group'] == 'stack']),
                         cell([c[m] for c in rows_ if c['bucket'] == b and c['group'] == 'direct'])))
    table(title, ['bucket', 'metric', 'stack: n: median [IQR]', 'direct: n: median [IQR]'], data)
cost_table('L3 Cost per session by size bucket, all harnesses (tokens only where the harness records them)', cmp_rows)
cost_table('L4 Same, single-PR sessions on Claude Code only', [c for c in cmp_rows if c['n_prs'] == 1 and c['harness'] == 'claude-code'])

def rate(xs): return '%d/%d (%.0f%%)' % (sum(xs), len(xs), 100 * sum(xs) / len(xs)) if xs else 'n=0'
fp = []
for b in BUCKETS + ['all']:
    for g in ('stack', 'direct'):
        ps = [p for p in pr_rows if p['group'] == g and (b == 'all' or bucket(p['additions'] + p['deletions']) == b)]
        med = lambda k: f(q([p[k] for p in ps], .5)) if ps else ''
        fp.append((b, g, len(ps), rate([p['merged'] for p in ps]), rate([p['first_pass_strict'] for p in ps]), rate([p['first_pass_handoff'] for p in ps]),
                   rate([p['first_pass_ready'] for p in ps]), rate([p['first_pass_ready_nofix'] for p in ps]), rate([p['opened_as_draft'] for p in ps]),
                   rate([int(p['followup_fix_prs'] > 0) for p in ps]), rate([int(p['followup_fix_prs_loose'] > 0) for p in ps]), rate([int(p['commits_after_open'] > 0) for p in ps]), rate([int(p['commits_after_session'] > 0) for p in ps]),
                   rate([int(p['failed_check_runs'] > 0) for p in ps]), rate([int(p['failed_checks_at_handoff'] > 0) for p in ps]),
                   rate([int(p['change_requests'] > 0) for p in ps]), rate([int(p['check_runs'] > 0) for p in ps])))
table('L5 Right first time per PR, by the PR\'s own size bucket', ['bucket', 'group', 'PRs', 'merged', 'first-pass strict', 'first-pass hand-off', 'first-pass ready', 'first-pass ready, no fix PR', 'opened as draft', 'fix PR naming it <=7d', 'fix PR sharing a file <=7d (loose)',
      '>=1 commit after open', '>=1 commit after session end', '>=1 failed check run', 'failed check at hand-off commit', 'change request', 'has any check'], fp)
pc = collections.Counter(c['project'] for c in cmp_rows)
LAB = {p: 'project ' + (chr(65 + i) if i < 26 else 'Z%d' % i) for i, (p, _) in enumerate(pc.most_common())}
with open(os.path.join(RUN, 'l4l-project-labels.csv'), 'w', newline='') as fh:   # private mapping, keep out of the repo
    w = csv.writer(fh); w.writerow(['label', 'project', 'sessions']); [w.writerow([LAB[p], p, n]) for p, n in pc.most_common()]
mix = []
for b in BUCKETS:
    for g in ('stack', 'direct'):
        cs = collections.Counter(LAB[c['project']] for c in cmp_rows if c['bucket'] == b and c['group'] == g)
        mix.append((b, g, sum(cs.values()), len(cs), ', '.join('%s %d' % kv for kv in cs.most_common(4))))
table('L6 Project mix per bucket (labels; mapping kept outside the repo)', ['bucket', 'group', 'sessions', 'projects', 'top projects'], mix)
wp = []
for b in BUCKETS:
    for p in sorted(pc, key=lambda p: LAB[p]):
        st = [c for c in cmp_rows if c['bucket'] == b and c['project'] == p and c['group'] == 'stack']
        di = [c for c in cmp_rows if c['bucket'] == b and c['project'] == p and c['group'] == 'direct']
        if len(st) >= 3 and len(di) >= 3:
            wp.append((b, LAB[p], cell([c['total_tokens'] for c in st]), cell([c['total_tokens'] for c in di]),
                       cell([c['active_min'] for c in st]), cell([c['active_min'] for c in di]),
                       cell([c['lines'] for c in st]), cell([c['lines'] for c in di])))
table('L7 Within one project and one bucket (both groups n>=3)', ['bucket', 'project', 'stack tokens', 'direct tokens', 'stack active min', 'direct active min', 'stack lines', 'direct lines'], wp)
hm = collections.Counter((c['group'], c['harness']) for c in cmp_rows)
table('L8 Harness of compared sessions', ['harness', 'stack', 'direct'], [(h, hm[('stack', h)], hm[('direct', h)]) for h in sorted({c['harness'] for c in cmp_rows})])
open(os.path.join(RUN, 'l4l-tables.md'), 'w').write('\n'.join(md) + '\n')
print('urls', len(urls), 'readable', uu['read'], 'prs attributed', len(pr_rows), 'sessions compared', len(cmp_rows))
