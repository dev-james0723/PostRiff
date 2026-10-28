#!/usr/bin/env python3
"""Compare saved HTTP responses of two builds route by route (customer impact check). Standard library only.

usage:
  impact_compare.py plan    --routes FILE
  impact_compare.py capture --routes FILE --base URL --out DIR [--header 'Name: value' ...] [--timeout S]
  impact_compare.py compare --routes FILE --a DIR --b DIR [--a-label live] [--b-label rc] [--json OUT] [--show N]

The route file has one route per line: METHOD PATH [kind=page|api|asset|shape] [expect=REGEX] [# comment].
Only GET and HEAD are accepted: the tool is for read-only routes.

A saved response for a route lives in DIR under the route's slug (`plan` prints them) in one of three forms:
  <slug>.json     {"status": 200, "headers": [["name", "value"], ...] or {"name": "value"}, "body": "text"}
                  ("bodyBase64" instead of "body" for bytes; "route" and "url" are optional)
  <slug>.http     raw `curl -sS -i` output (the last header block wins, so `-L` output also works)
  <slug>.headers  plus <slug>.body, from `curl -sS -D <slug>.headers -o <slug>.body`

Volatile parts are normalised before comparing: Next.js asset paths and build ids, Vercel deployment ids, nonces,
timestamps, commit SHAs, UUIDs, Sentry trace data, and the Date/Age/ETag/request-id/cache-state headers. For each route
the report gives the status, the headers that matter (content type, caching, security headers, CORS, redirects and the
NAMES and flags of set-cookie, never their values), a body summary (visible text for HTML, key paths for JSON, a hash for
binary) and a verdict:

  SAME          nothing that matters differs after normalisation
  SAME-VISIBLE  status, headers and visible text are equal; only markup or script references differ
  EXPECTED      the only differences are visible-text lines that match the route's expect= pattern
  DIFF          anything else differs (status, a compared header, visible text, JSON values, bytes)
  MISSING       one side has no saved response for the route
  UNREADABLE    a saved response could not be parsed

The exit status is 1 when any route is DIFF, MISSING or UNREADABLE, otherwise 0. Nothing secret is printed: cookie
values, authorization headers and request headers given to `capture` are never written or shown.
"""
import argparse
import base64
import difflib
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser

METHODS = ('GET', 'HEAD')
KINDS = ('page', 'api', 'asset', 'shape')
COMPARED_HEADERS = (
    'content-type', 'cache-control', 'location', 'vary', 'strict-transport-security', 'content-security-policy',
    'content-security-policy-report-only', 'x-frame-options', 'x-content-type-options', 'referrer-policy',
    'permissions-policy', 'cross-origin-opener-policy', 'cross-origin-embedder-policy', 'cross-origin-resource-policy',
    'access-control-allow-origin', 'access-control-allow-credentials', 'access-control-allow-methods',
    'access-control-allow-headers', 'access-control-expose-headers', 'x-robots-tag', 'x-nextjs-prerender',
    'service-worker-allowed', 'content-disposition', 'www-authenticate', 'content-encoding')
VOLATILE_HEADERS = {
    'date', 'age', 'etag', 'last-modified', 'content-length', 'x-request-id', 'x-vercel-id', 'x-vercel-cache',
    'x-nextjs-cache', 'x-nextjs-stale-time', 'server-timing', 'x-vercel-execution-region', 'connection',
    'keep-alive', 'transfer-encoding', 'x-matched-path', 'report-to', 'nel', 'alt-svc', 'server', 'x-powered-by'}
SECRET_HEADERS = {'authorization', 'cookie', 'proxy-authorization', 'x-vercel-protection-bypass'}

_RULES = [
    # Next.js and Vercel build artefacts: every hashed asset path collapses to its kind and extension.
    (re.compile(r'/_next/static/[^"\'\s?#)\\<>]+?(\.[A-Za-z0-9]{1,8})(?=["\'\s?#)\\<>]|$)'), r'/_next/static/<asset>\1'),
    (re.compile(r'/_next/image\?[^"\'\s)\\<>]+'), '/_next/image?<image>'),
    (re.compile(r'\bdpl_[A-Za-z0-9]{8,}'), '<deployment>'),
    (re.compile(r'([?&](?:v|ver|h|hash|dpl)=)[A-Za-z0-9_-]{6,}'), r'\1<hash>'),
    (re.compile(r'(\\?"(?:buildId|b)\\?"\s*:\s*\\?")[A-Za-z0-9_-]{8,}(\\?")'), r'\1<build>\2'),
    # Per-request values.
    (re.compile(r'(nonce=["\']?)[A-Za-z0-9+/=_-]{8,}'), r'\1<nonce>'),
    (re.compile(r"'nonce-[A-Za-z0-9+/=_-]+'"), "'nonce-<nonce>'"),
    (re.compile(r'(<meta[^>]+name=["\'](?:sentry-trace|baggage)["\'][^>]*content=["\'])[^"\']*'), r'\1<sentry>'),
    (re.compile(r'(sentry-(?:trace_id|release|public_key|sample_rand|sampled|environment)=)[^,&"\'\s]+'), r'\1<sentry>'),
    (re.compile(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?\b'), '<time>'),
    (re.compile(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT\b'), '<time>'),
    (re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I), '<uuid>'),
    (re.compile(r'\b[0-9a-f]{40}\b'), '<sha>'),
    (re.compile(r'\b[0-9a-f]{32}\b'), '<hex32>'),
]


def normalise(text):
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


# --- routes -----------------------------------------------------------------------------------------------------------

def parse_routes(path):
    routes = []
    with open(path, encoding='utf-8') as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.split(' #', 1)[0].strip() if not raw.lstrip().startswith('#') else ''
            if not line:
                continue
            parts = line.split()
            method, target = parts[0].upper(), parts[1] if len(parts) > 1 else ''
            if method not in METHODS or not target.startswith('/'):
                raise SystemExit('%s:%d: expected "GET /path" or "HEAD /path" (read-only routes only)' % (path, number))
            route = {'method': method, 'path': target, 'kind': 'page', 'expect': None, 'line': number}
            for option in parts[2:]:
                key, _, value = option.partition('=')
                if key == 'kind' and value in KINDS:
                    route['kind'] = value
                elif key == 'expect' and value:
                    route['expect'] = value
                else:
                    raise SystemExit('%s:%d: unknown option %r' % (path, number, option))
            if route['expect']:
                re.compile(route['expect'])
            route['slug'] = slug(method, target)
            routes.append(route)
    if len({r['slug'] for r in routes}) != len(routes):
        raise SystemExit('%s: two routes share a slug' % path)
    return routes


def slug(method, target):
    base = method.lower() + '_' + (re.sub(r'[^A-Za-z0-9._-]+', '_', target.strip('/')).strip('_') or 'root')
    if len(base) > 100 or '?' in target:
        base = base[:90] + '-' + hashlib.sha1((method + ' ' + target).encode()).hexdigest()[:8]
    return base


# --- reading saved responses --------------------------------------------------------------------------------------------

def _header_block(raw):
    """Parse the last HTTP header block of raw `curl -i` style bytes. Returns (status, headers, body bytes)."""
    blocks, rest = [], raw
    while re.match(rb'HTTP/\d(?:\.\d)? \d{3}', rest):
        split = re.search(rb'\r?\n\r?\n', rest)
        head, rest = (rest, b'') if split is None else (rest[:split.start()], rest[split.end():])
        blocks.append(head)
    if not blocks:
        raise ValueError('no HTTP status line')
    return _parse_head(blocks[-1].decode('iso-8859-1')) + (rest,)


def _parse_head(text):
    lines = [line for line in text.replace('\r\n', '\n').split('\n')]
    match = re.match(r'HTTP/\d(?:\.\d)? (\d{3})', lines[0].strip())
    if not match:
        raise ValueError('no HTTP status line')
    headers = []
    for line in lines[1:]:
        if ':' in line:
            name, value = line.split(':', 1)
            headers.append((name.strip().lower(), value.strip()))
    return int(match.group(1)), headers


def load(directory, route):
    base = os.path.join(directory, route['slug'])
    if os.path.exists(base + '.json'):
        with open(base + '.json', encoding='utf-8') as handle:
            data = json.load(handle)
        raw_headers = data.get('headers') or []
        if isinstance(raw_headers, dict):
            pairs = []
            for name, value in raw_headers.items():
                for item in (value if isinstance(value, list) else [value]):
                    pairs.append((str(name).lower(), str(item)))
        else:
            pairs = [(str(name).lower(), str(value)) for name, value in raw_headers]
        if 'bodyBase64' in data:
            body = base64.b64decode(data['bodyBase64'])
        else:
            body = str(data.get('body') or '').encode('utf-8')
        return int(data['status']), pairs, body
    if os.path.exists(base + '.http'):
        with open(base + '.http', 'rb') as handle:
            return _header_block(handle.read())
    if os.path.exists(base + '.headers'):
        with open(base + '.headers', 'rb') as handle:
            status, pairs, _ = _header_block(handle.read())
        body = b''
        if os.path.exists(base + '.body'):
            with open(base + '.body', 'rb') as handle:
                body = handle.read()
        return status, pairs, body
    return None


# --- summarising ---------------------------------------------------------------------------------------------------------

class _Visible(HTMLParser):
    """Visible text, one line per block element, plus the metadata and link targets a person or crawler sees."""
    SKIP = {'script', 'style', 'noscript', 'template', 'svg'}
    BLOCK = {'address', 'article', 'aside', 'blockquote', 'body', 'br', 'button', 'caption', 'dd', 'details', 'dialog',
             'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
             'header', 'hr', 'label', 'legend', 'li', 'main', 'nav', 'ol', 'option', 'p', 'pre', 'section', 'select',
             'summary', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'title', 'tr', 'ul'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.text, self.meta, self.links, self.lang, self.current = 0, [], [], [], None, []

    def _flush(self):
        value = ' '.join(' '.join(self.current).split())
        if value:
            self.text.append(value)
        self.current = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.depth += 1
            return
        if tag in self.BLOCK:
            self._flush()
        if tag == 'html' and attrs.get('lang'):
            self.lang = attrs['lang']
        if tag == 'meta' and (attrs.get('name') or attrs.get('property')) and 'content' in attrs:
            key = (attrs.get('name') or attrs.get('property')).lower()
            if key not in ('sentry-trace', 'baggage', 'next-size-adjust'):
                self.meta.append('%s=%s' % (key, normalise(attrs['content'] or '')))
        if tag == 'link' and attrs.get('rel') in ('canonical', 'alternate', 'manifest', 'icon', 'apple-touch-icon'):
            self.links.append('%s %s' % (attrs['rel'], normalise(attrs.get('href') or '')))
        if tag == 'a' and attrs.get('href'):
            self.links.append('a ' + normalise(attrs['href']))
        if tag == 'form':
            self.links.append('form %s %s' % ((attrs.get('method') or 'get').lower(), normalise(attrs.get('action') or '')))
        label = attrs.get('alt') if tag == 'img' else attrs.get('aria-label') if tag in ('input', 'button', 'a', 'nav', 'section') else None
        if label and not self.depth:
            self.current.append('[%s: %s]' % (tag, label))

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            if self.depth:
                self.depth -= 1
            return
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.depth:
            self.current.append(data)

    def close(self):
        super().close()
        self._flush()


def summarise(status, headers, body, kind):
    names = {}
    for name, value in headers:
        names.setdefault(name, []).append(value)
    compared = {}
    for name in COMPARED_HEADERS:
        if name in names:
            values = [normalise(v) for v in names[name]]
            if name == 'location':
                values = [re.sub(r'^https?://[^/]+', '', v) for v in values]
            compared[name] = ' | '.join(values)
    cookies = []
    for value in names.get('set-cookie', []):
        parts = [p.strip() for p in value.split(';')]
        flags = sorted({p.split('=', 1)[0].lower() for p in parts[1:] if p})
        cookies.append('%s [%s]' % (parts[0].split('=', 1)[0], ','.join(flags)))
    if cookies:
        compared['set-cookie (names and flags)'] = ' | '.join(sorted(cookies))
    other = sorted(set(names) - set(COMPARED_HEADERS) - VOLATILE_HEADERS - SECRET_HEADERS - {'set-cookie'})
    content_type = (names.get('content-type') or [''])[0].split(';')[0].strip().lower()
    summary = {'status': status, 'headers': compared, 'otherHeaderNames': other, 'bytes': len(body),
               'contentType': content_type}
    if content_type in ('text/html', 'application/xhtml+xml') or (not content_type and body.lstrip()[:15].lower().startswith((b'<!doctype', b'<html'))):
        text = body.decode('utf-8', errors='replace')
        parser = _Visible()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            pass
        assets = re.findall(r'/_next/static/[^"\'\s?#)\\<>]+', text)
        summary.update(body='html', visible=[normalise(t) for t in parser.text],
                       meta=sorted(set(parser.meta)), links=sorted(set(parser.links)), lang=parser.lang,
                       assets={'js': len({a for a in assets if a.endswith('.js')}),
                               'css': len({a for a in assets if a.endswith('.css')})},
                       normalised=hashlib.sha256(normalise(text).encode()).hexdigest())
    elif 'json' in content_type or (not content_type and body.lstrip()[:1] in (b'{', b'[')):
        try:
            value = json.loads(body.decode('utf-8'))
            summary.update(body='json', json=_flatten(value),
                           normalised=hashlib.sha256(json.dumps(_normalise_json(value), sort_keys=True).encode()).hexdigest())
        except ValueError:
            summary.update(body='text', visible=normalise(body.decode('utf-8', errors='replace')).splitlines(),
                           normalised=hashlib.sha256(normalise(body.decode('utf-8', errors='replace')).encode()).hexdigest())
    elif content_type.startswith('text/') or content_type in ('application/javascript', 'application/xml', 'application/manifest+json'):
        text = normalise(body.decode('utf-8', errors='replace'))
        summary.update(body='text', visible=text.splitlines(), normalised=hashlib.sha256(text.encode()).hexdigest())
    else:
        summary.update(body='binary', normalised=hashlib.sha256(body).hexdigest())
    return summary


def _normalise_json(value):
    if isinstance(value, dict):
        return {key: _normalise_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_json(item) for item in value]
    return normalise(value) if isinstance(value, str) else value


def _flatten(value, prefix=''):
    """Key path -> normalised scalar, lists by index. Bounded so a huge body cannot blow up the report."""
    out = {}
    stack = [(prefix, value)]
    while stack and len(out) < 20000:
        path, item = stack.pop()
        if isinstance(item, dict):
            if not item:
                out[path or '$'] = '{}'
            for key in sorted(item, reverse=True):
                stack.append(('%s.%s' % (path, key) if path else key, item[key]))
        elif isinstance(item, list):
            if not item:
                out[path or '$'] = '[]'
            for index in range(len(item) - 1, -1, -1):
                stack.append(('%s[%d]' % (path, index), item[index]))
        else:
            out[path or '$'] = json.dumps(normalise(item) if isinstance(item, str) else item)
    return out


# --- comparing -------------------------------------------------------------------------------------------------------------

def compare_route(route, a, b):
    """hard: never expectable (status, compared headers, body kind, bytes). soft: content lines expect= may cover."""
    hard, soft, notes = [], [], []
    if a['status'] != b['status']:
        hard.append('status %s -> %s' % (a['status'], b['status']))
    for name in sorted(set(a['headers']) | set(b['headers'])):
        left, right = a['headers'].get(name), b['headers'].get(name)
        if left != right:
            hard.append('header %s: %s -> %s' % (name, _short(left), _short(right)))
    added = sorted(set(b['otherHeaderNames']) - set(a['otherHeaderNames']))
    removed = sorted(set(a['otherHeaderNames']) - set(b['otherHeaderNames']))
    if added or removed:
        notes.append('other header names: +%s -%s' % (added or '[]', removed or '[]'))
    if a['body'] != b['body']:
        hard.append('body kind %s -> %s' % (a['body'], b['body']))
    elif a['body'] in ('html', 'text'):
        soft.extend('text' + line for line in difflib.unified_diff(a.get('visible', []), b.get('visible', []), lineterm='', n=0)
                    if line[:1] in '+-' and not line.startswith(('+++', '---')))
        if a['body'] == 'html':
            for key in ('meta', 'links'):
                soft.extend('%s+ %s' % (key, item) for item in sorted(set(b[key]) - set(a[key])))
                soft.extend('%s- %s' % (key, item) for item in sorted(set(a[key]) - set(b[key])))
            if a.get('lang') != b.get('lang'):
                hard.append('html lang %s -> %s' % (a.get('lang'), b.get('lang')))
            if a['assets'] != b['assets']:
                notes.append('Next.js asset references js %d->%d, css %d->%d' % (a['assets']['js'], b['assets']['js'], a['assets']['css'], b['assets']['css']))
    elif a['body'] == 'json':
        keys = set(a['json']) | set(b['json'])
        soft.extend('json+ %s=%s' % (k, b['json'][k]) for k in sorted(keys) if k not in a['json'])
        soft.extend('json- %s=%s' % (k, a['json'][k]) for k in sorted(keys) if k not in b['json'])
        soft.extend('json~ %s: %s -> %s' % (k, a['json'][k], b['json'][k]) for k in sorted(keys)
                    if k in a['json'] and k in b['json'] and a['json'][k] != b['json'][k])
    elif a['normalised'] != b['normalised']:
        hard.append('bytes differ (%d -> %d)' % (a['bytes'], b['bytes']))
    if a['bytes'] != b['bytes']:
        notes.append('size %d -> %d bytes' % (a['bytes'], b['bytes']))
    if not hard and not soft:
        verdict = 'SAME' if a['normalised'] == b['normalised'] else 'SAME-VISIBLE'
    elif not hard and route['expect'] and all(re.search(route['expect'], line) for line in soft):
        verdict = 'EXPECTED'
    else:
        verdict = 'DIFF'
    findings = hard + (['%d content line(s) changed%s' % (len(soft), '' if verdict != 'DIFF' or not route['expect'] else
                        ', %d outside expect=' % sum(not re.search(route['expect'], line) for line in soft))] if soft else [])
    return {'route': '%s %s' % (route['method'], route['path']), 'kind': route['kind'], 'verdict': verdict,
            'status': [a['status'], b['status']], 'findings': findings, 'notes': notes, 'textChanges': soft}


def _short(value, limit=160):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if text is None or len(text) <= limit else text[:limit - 1] + '…'


def compare(routes, dir_a, dir_b):
    results = []
    for route in routes:
        loaded = []
        for directory in (dir_a, dir_b):
            try:
                loaded.append(load(directory, route))
            except (ValueError, KeyError, TypeError, OSError) as error:
                loaded.append(error)
        problem = next((('UNREADABLE', str(x)) for x in loaded if isinstance(x, Exception)), None)
        if problem is None and None in loaded:
            problem = ('MISSING', 'no saved response on side ' + ('A' if loaded[0] is None else 'B'))
        if problem:
            results.append({'route': '%s %s' % (route['method'], route['path']), 'kind': route['kind'], 'verdict': problem[0],
                            'status': [None, None], 'findings': [problem[1]], 'notes': [], 'textChanges': []})
            continue
        results.append(compare_route(route, summarise(*loaded[0], route['kind']), summarise(*loaded[1], route['kind'])))
    return results


def report(results, label_a, label_b, show):
    width = max([len(r['route']) for r in results] + [5])
    print('%-*s  %-12s  %-9s  %s' % (width, 'route', 'verdict', 'status', 'what differs (%s -> %s)' % (label_a, label_b)))
    for item in results:
        status = '%s/%s' % tuple('-' if s is None else s for s in item['status'])
        print('%-*s  %-12s  %-9s  %s' % (width, item['route'], item['verdict'], status, '; '.join(item['findings']) or '-'))
        for note in item['notes']:
            print('%-*s  %-12s  %-9s  note: %s' % (width, '', '', '', note))
        for line in item['textChanges'][:show]:
            print('%-*s  %-12s  %-9s  %s' % (width, '', '', '', _short(line)))
        if len(item['textChanges']) > show:
            print('%-*s  %-12s  %-9s  … %d more (see --json)' % (width, '', '', '', len(item['textChanges']) - show))
    counts = {}
    for item in results:
        counts[item['verdict']] = counts.get(item['verdict'], 0) + 1
    print('TOTAL %d routes: %s' % (len(results), ', '.join('%s %d' % (k, counts[k]) for k in sorted(counts))))
    return counts


# --- capture (any base URL the operator chooses; the tests use localhost) --------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def capture(routes, base, out, headers, timeout):
    os.makedirs(out, exist_ok=True)
    opener = urllib.request.build_opener(_NoRedirect)
    for route in routes:
        request = urllib.request.Request(base.rstrip('/') + route['path'], method=route['method'], headers=headers)
        try:
            response = opener.open(request, timeout=timeout)
            status, pairs, body = response.status, list(response.getheaders()), response.read()
        except urllib.error.HTTPError as error:
            status, pairs, body = error.code, list(error.headers.items()), error.read()
        saved = []
        for name, value in pairs:
            name = name.lower()
            if name in SECRET_HEADERS:
                continue
            if name == 'set-cookie':
                # Keep the cookie name and attribute flags only; the value never reaches disk.
                parts = [p.strip() for p in value.split(';')]
                value = '; '.join([parts[0].split('=', 1)[0] + '=<redacted>'] + [p.split('=', 1)[0] for p in parts[1:] if p])
            saved.append([name, value])
        record = {'route': '%s %s' % (route['method'], route['path']), 'status': status, 'headers': saved}
        try:
            record['body'] = body.decode('utf-8')
        except UnicodeDecodeError:
            record['bodyBase64'] = base64.b64encode(body).decode()
        with open(os.path.join(out, route['slug'] + '.json'), 'w', encoding='utf-8') as handle:
            json.dump(record, handle, ensure_ascii=False, indent=1)
        print('%s %s -> %s' % (route['method'], route['path'], status))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan', help='list routes and the file names a capture must produce')
    plan.add_argument('--routes', required=True)
    cap = sub.add_parser('capture', help='fetch every route from one base URL into a directory')
    cap.add_argument('--routes', required=True)
    cap.add_argument('--base', required=True)
    cap.add_argument('--out', required=True)
    cap.add_argument('--header', action='append', default=[], help="extra request header 'Name: value' (never stored)")
    cap.add_argument('--timeout', type=float, default=20)
    cmp_ = sub.add_parser('compare', help='compare two capture directories')
    cmp_.add_argument('--routes', required=True)
    cmp_.add_argument('--a', required=True)
    cmp_.add_argument('--b', required=True)
    cmp_.add_argument('--a-label', default='A')
    cmp_.add_argument('--b-label', default='B')
    cmp_.add_argument('--json')
    cmp_.add_argument('--show', type=int, default=8, help='changed text lines to print per route')
    args = parser.parse_args(argv)
    routes = parse_routes(args.routes)
    if args.command == 'plan':
        for route in routes:
            print('%-5s %-60s %-6s %s.{json|http|headers+body}' % (route['method'], route['path'], route['kind'], route['slug']))
        print('example: curl -sS -i -X GET "$BASE<path>" > DIR/<slug>.http   (add -I for HEAD)')
        return 0
    if args.command == 'capture':
        extra = {}
        for item in args.header:
            name, _, value = item.partition(':')
            extra[name.strip()] = value.strip()
        capture(routes, args.base, args.out, extra, args.timeout)
        return 0
    results = compare(routes, args.a, args.b)
    counts = report(results, args.a_label, args.b_label, args.show)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as handle:
            json.dump({'a': args.a_label, 'b': args.b_label, 'counts': counts, 'routes': results}, handle, indent=1, ensure_ascii=False)
    return 1 if any(k in counts for k in ('DIFF', 'MISSING', 'UNREADABLE')) else 0


if __name__ == '__main__':
    sys.exit(main())
