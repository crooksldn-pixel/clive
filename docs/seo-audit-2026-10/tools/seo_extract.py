"""Extract the SEO/GEO-relevant facts from a rendered HTML page.

usage: python3 -I seo_extract.py <html file> <url>  -> JSON on stdout
"""
import json
import re
import sys
from html.parser import HTMLParser


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self.metas = []
        self.links = []
        self.headings = []
        self._h = None
        self.scripts = []
        self._script = None
        self.imgs = []
        self.anchors = []
        self._skip = 0  # inside <script>/<style>/<noscript>
        self._tpl = 0  # inside <template>: inert, never part of the rendered page
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'template':
            self._tpl += 1
        if self._tpl and tag in ('h1', 'h2', 'h3', 'img', 'a'):
            return
        if tag == 'title' and self.title is None:
            self._in_title = True
            self.title = ''
        elif tag == 'meta':
            self.metas.append(a)
        elif tag == 'link':
            self.links.append(a)
        elif tag in ('h1', 'h2', 'h3'):
            self._h = [tag, '']
        elif tag == 'script':
            self._script = [a.get('type', ''), '']
            self._skip += 1
        elif tag in ('style', 'noscript', 'template'):
            self._skip += 1
        elif tag == 'img':
            self.imgs.append(a)
        elif tag == 'a' and a.get('href'):
            self.anchors.append(a.get('href'))

    def handle_endtag(self, tag):
        if tag == 'template':
            self._tpl = max(0, self._tpl - 1)
        if tag == 'title':
            self._in_title = False
        elif tag in ('h1', 'h2', 'h3') and self._h and self._h[0] == tag:
            self.headings.append((tag, re.sub(r'\s+', ' ', self._h[1]).strip()))
            self._h = None
        elif tag == 'script':
            if self._script:
                self.scripts.append(tuple(self._script))
            self._script = None
            self._skip = max(0, self._skip - 1)
        elif tag in ('style', 'noscript', 'template'):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._h is not None:
            self._h[1] += data
        if self._script is not None:
            self._script[1] += data
        elif not self._skip:
            self.text.append(data)


def max_srcset_w(srcset):
    ws = [int(m) for m in re.findall(r'\s(\d+)w', srcset or '')]
    return max(ws) if ws else None


def main():
    html = open(sys.argv[1], encoding='utf-8', errors='replace').read()
    url = sys.argv[2]
    p = P()
    p.feed(html)

    def meta(**kw):
        for m in p.metas:
            if all(m.get(k) == v for k, v in kw.items()):
                return m.get('content')
        return None

    canon = next((l.get('href') for l in p.links if l.get('rel') == 'canonical'), None)
    ld, ld_errors = [], []
    for typ, body in p.scripts:
        if typ == 'application/ld+json':
            try:
                ld.append(json.loads(body))
            except Exception as e:  # noqa
                ld_errors.append(str(e)[:120])

    def types(o, out):
        if isinstance(o, dict):
            t = o.get('@type')
            if t:
                out.append(t if isinstance(t, str) else '/'.join(t))
            for v in o.values():
                types(v, out)
        elif isinstance(o, list):
            for v in o:
                types(v, out)
        return out

    imgs = []
    for i in p.imgs:
        src = i.get('src') or ''
        w = re.search(r'[?&]width=(\d+)', src)
        imgs.append({
            'src': src[:160], 'src_width': int(w.group(1)) if w else None,
            'srcset_max': max_srcset_w(i.get('srcset')), 'sizes': i.get('sizes'),
            'loading': i.get('loading'), 'fetchpriority': i.get('fetchpriority'),
            'alt': i.get('alt'), 'has_alt_attr': 'alt' in i, 'width': i.get('width'), 'height': i.get('height'),
        })
    words = len(re.findall(r"[A-Za-z0-9£'’-]+", ' '.join(p.text)))
    coll_links = sorted({re.sub(r'[?#].*', '', h) for h in p.anchors if '/collections/' in h})
    out = {
        'url': url,
        'title': (p.title or '').strip(),
        'title_len': len((p.title or '').strip()),
        'meta_description': meta(name='description'),
        'meta_description_len': len(meta(name='description') or ''),
        'meta_robots': meta(name='robots'),
        'canonical': canon,
        'og': {k: meta(property='og:' + k) for k in ('title', 'description', 'type', 'url', 'image', 'site_name')},
        'twitter': {k: meta(name='twitter:' + k) for k in ('card', 'title', 'description', 'site')},
        'h1': [t for h, t in p.headings if h == 'h1'],
        'h2_count': sum(1 for h, _ in p.headings if h == 'h2'),
        'jsonld_blocks': len(ld) + len(ld_errors),
        'jsonld_invalid': ld_errors,
        'jsonld_types': types(ld, []),
        'jsonld': ld,
        'img_count': len(imgs),
        'imgs': imgs,
        'visible_words': words,
        'collection_links': coll_links,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


main()
