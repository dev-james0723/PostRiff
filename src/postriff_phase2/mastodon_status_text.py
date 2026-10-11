"""Read-back text comparison bound to this status's reported mention identities.

No profile lookup or URL fetch occurs. Never drop a remote handle's domain to
make publication appear verified. Other text keeps its exact approved spelling.
"""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

USER = r'[A-Za-z0-9_]+'
HOST = r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?'
HANDLE = re.compile(r'(?<![\w/@])@(' + USER + r')(?:@(' + HOST + r'))?(?![\w@-])')


def identities(rows, instance):
    result = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        username, acct, url, identifier = row.get('username'), row.get('acct'), row.get('url'), row.get('id')
        if not all(isinstance(v, str) for v in (username, acct, url, identifier)) or not 1 <= len(identifier) <= 120:
            continue
        if not re.fullmatch(USER, username) or len(acct) > 320 or len(url) > 2048:
            continue
        user, separator, host = acct.partition('@')
        host = host if separator else instance
        if user.casefold() != username.casefold() or not re.fullmatch(HOST, host):
            continue
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment
        except ValueError:
            valid = False
        if not valid:
            continue
        identity = (username.casefold(), '@' + user.casefold() + '@' + host.casefold(), identifier)
        if url in result and result[url] != identity:
            result[url] = None  # Ambiguous metadata cannot verify a rendered mention.
        elif url not in result:
            result[url] = identity
    return result


class MentionText(HTMLParser):
    def __init__(self, known):
        super().__init__(convert_charrefs=True)
        self.known, self.output, self.used = known, [], set()
        self.anchor = None
        self.invalid = False
        self.closed_paragraph = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            if self.anchor is not None:
                self.invalid = True
            mention = 'mention' in (attrs.get('class') or '').split()
            self.anchor = {'mention': mention, 'identity': self.known.get(attrs.get('href')), 'text': []}
        elif tag == 'br':
            self.handle_data('\n')
        elif tag == 'p' and self.output:
            self.closed_paragraph = False
            self.handle_data('\n\n')
        if tag == 'p':
            self.closed_paragraph = False

    def handle_endtag(self, tag):
        if tag == 'p':
            self.closed_paragraph = True
        if tag != 'a' or self.anchor is None:
            return
        anchor, self.anchor = self.anchor, None
        text = ''.join(anchor['text'])
        if anchor['mention']:
            identity = anchor['identity']
            if not identity or text.casefold() not in ('@' + identity[0], identity[1]):
                self.invalid = True
                return
            text = identity[1]
            self.used.add(text)
        self.output.append(text)

    def handle_data(self, data):
        if self.closed_paragraph and data.isspace():
            return
        (self.anchor['text'] if self.anchor is not None else self.output).append(data)


def matches_text(status, approved, instance, plain_content):
    content = status.get('content', '')
    if not isinstance(content, str):
        return False
    parser = MentionText(identities(status.get('mentions'), instance))
    try:
        parser.feed(content)
        parser.close()
    except (ValueError, TypeError):
        return False
    if parser.invalid or parser.anchor is not None:
        return False
    if not parser.used:
        return plain_content(content) == approved.strip()

    def canonical(match):
        user, host = match.groups()
        handle = '@' + user.casefold() + '@' + (host or instance).casefold()
        return handle if handle in parser.used else match.group(0)

    return ''.join(parser.output).strip() == HANDLE.sub(canonical, approved.strip())
