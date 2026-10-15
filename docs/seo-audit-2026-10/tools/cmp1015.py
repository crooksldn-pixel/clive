import json, os, sys, csv
SP = sys.argv[1]
def load(d):
    out = {}
    idx = os.path.join(SP, 'audit', d, 'index.tsv')
    for line in open(idx):
        f, c, u = line.rstrip('\n').split('\t')
        j = os.path.join(SP, 'audit', d, 'json', os.path.basename(f).replace('.html', '.json'))
        if os.path.exists(j):
            out[u] = json.load(open(j))
    return out
B, A, N = load('before'), load('after'), load('live1015')
rows = []
for u in N:
    n, a, b = N[u], A.get(u, {}), B.get(u, {})
    rows.append((u.replace('https://crooksldn.com', ''), b.get('title_len'), a.get('title_len'), n['title_len'], n['title'], n['meta_description_len'], a.get('meta_description_len'), n['meta_robots'], len(n['h1']), n['jsonld_invalid'], n['visible_words'], a.get('title') == n['title'], a.get('meta_description') == n['meta_description']))
for r in sorted(rows):
    print('\t'.join(str(x) for x in r))
