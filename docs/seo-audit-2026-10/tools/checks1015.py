import json, os, re, sys, glob
L = sys.argv[1]
idx = {}
for line in open(L + '/index.tsv'):
    f, c, u = line.rstrip('\n').split('\t'); idx[u] = f
def J(u): return json.load(open(L + '/json/' + os.path.basename(idx[u]).replace('.html', '.json')))
def H(u): return open(L + '/' + idx[u], encoding='utf-8', errors='replace').read()
def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
prod = [u for u in idx if '/products/' in u and '?' not in u and os.path.exists(L + '/json/' + os.path.basename(idx[u]).replace('.html', '.json'))]
offers = ship = seller = 0; avail = {}; mat = 0; graph_err = 0; brand_ok = 0
for u in prod:
    j = J(u); nodes = list(walk(j['jsonld']))
    ids = {n['@id'] for n in nodes if '@id' in n and len(n) > 1}
    refs = [n['@id'] for n in nodes if '@id' in n and len(n) == 1]
    graph_err += sum(1 for r in refs if r not in ids)
    has_mat = any('material' in n for n in nodes); mat += has_mat
    brand_ok += any(n.get('@type') == 'Brand' and n.get('@id') == 'https://crooksldn.com#brand' for n in nodes)
    for n in nodes:
        if n.get('@type') == 'Offer':
            offers += 1; ship += 'shippingDetails' in n; seller += isinstance(n.get('seller'), dict) and n['seller'].get('@id') == 'https://crooksldn.com#organization'
            a = n.get('availability', '').rsplit('/', 1)[-1]; avail[a] = avail.get(a, 0) + 1
print(f'products {len(prod)}: offers {offers}, with shippingDetails {ship}, seller @id {seller}, brand @id on {brand_ok}, material on {mat}, unresolved refs {graph_err}, availability {avail}')
org = [n for u in idx if os.path.exists(L + '/json/' + os.path.basename(idx[u]).replace('.html', '.json')) for n in walk(J(u)['jsonld']) if n.get('@type') == 'Organization' and 'legalName' in n]
print('pages with Organization legalName:', len(org))
# gmail
gm = [u for u in idx if os.path.exists(L + '/' + idx[u]) and 'crooksldn@gmail.com' in H(u)]
print('pages with crooksldn@gmail.com:', [x.replace('https://crooksldn.com', '') for x in gm])
# LCP eager/high on the 4 templates
for u in ['https://crooksldn.com/', 'https://crooksldn.com/collections/denim', 'https://crooksldn.com/collections/all', 'https://crooksldn.com/products/blue-wash-yard-jeans']:
    imgs = J(u)['imgs']; hi = [i for i in imgs if i.get('fetchpriority') == 'high']
    print('LCP', u.replace('https://crooksldn.com', '') or '/', 'high-priority imgs:', [(i.get('src', '')[-60:], i.get('loading')) for i in hi][:2])
# collection intros and product counts
for c in ['denim', 'tees', 'sweats', 'tracksuits', 'accessories', 'new', 'all']:
    h = H('https://crooksldn.com/collections/' + c)
    intro = re.search(r'<div class="crk-log__intro">(.*?)</div>', h, re.S)
    cards = len(set(re.findall(r'href="/products/([a-z0-9-]+)', h)))
    print(f'collection {c}: intro words {len(re.sub("<[^>]+>", " ", intro.group(1)).split()) if intro else 0} | product links {cards} | {re.sub("<[^>]+>", " ", intro.group(1)).strip()[:80] if intro else "-"}')
# homepage images without alt
h = H('https://crooksldn.com/')
noalt = re.findall(r'<img[^>]*alt=""[^>]*src="([^"]+)"', h) + re.findall(r'<img[^>]*src="([^"]+)"[^>]*alt=""', h)
print('home imgs with empty alt:', sorted(set(re.sub(r'\?.*', '', x).rsplit('/', 1)[-1] for x in noalt))[:12])
# reviews / ratings
print('pages with AggregateRating/Review:', sum(1 for u in prod if any(n.get('@type') in ('AggregateRating', 'Review') for n in walk(J(u)['jsonld']))))
# blog articles
h = H('https://crooksldn.com/blogs/news'); print('blog article links:', len(set(re.findall(r'href="(/blogs/news/[a-z0-9-]+)"', h))))
# canonical for variant URL
print('variant canonical:', J('https://crooksldn.com/products/blue-wash-yard-jeans?variant=53639822377303')['canonical'])
# FAQ questions
faq = [n for n in walk(J('https://crooksldn.com/pages/faq')['jsonld']) if n.get('@type') == 'Question']; print('FAQ questions:', len(faq))
