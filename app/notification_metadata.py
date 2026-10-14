"""Extract notification fields from already fetched headers; no remote reads."""

import unicodedata
from email import policy
from email.errors import HeaderParseError
from email.parser import BytesParser
from html.parser import HTMLParser


def display_text(value, limit=200):
    text = ' '.join(''.join(' ' if char.isspace() else char for char in str(value or '') if char.isspace() or not unicodedata.category(char).startswith('C')).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def notification_metadata(raw):
    message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    try:
        subject = display_text(message.get('Subject', '')) or None
    except (ValueError, HeaderParseError):
        subject = None
    sender = None
    try:
        headers = message.get_all('From', [])
        if len(headers) == 1 and not headers[0].defects:
            header = headers[0]
            addresses = header.addresses
            if len(addresses) == 1 and not any(group.display_name for group in header.groups):
                address = addresses[0]
                value = address.addr_spec
                if address.username and address.domain and not any(
                        char.isspace() or unicodedata.category(char).startswith('C') for char in value):
                    sender = value
    except (ValueError, AttributeError, IndexError, HeaderParseError):
        pass
    return sender, subject


class _PreviewHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if not self.hidden and tag in ('br', 'p', 'div', 'li', 'tr', 'hr'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        if not self.hidden:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _body_parts(message):
    if message.get_content_disposition() == 'attachment' or message.get_filename():
        return
    if message.get_content_maintype() == 'message':
        return
    if message.is_multipart():
        for child in message.iter_parts():
            yield from _body_parts(child)
    elif message.get_content_type() in ('text/plain', 'text/html'):
        yield message


def notification_details(raw):
    sender, subject = notification_metadata(raw)
    name = None
    preview = None
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        if sender:
            name = display_text(message['From'].addresses[0].display_name) or None
        parts = list(_body_parts(message))
        for content_type in ('text/plain', 'text/html'):
            for part in parts:
                if part.get_content_type() != content_type:
                    continue
                try:
                    content = part.get_content(errors='replace')
                    if content_type == 'text/html':
                        parser = _PreviewHTML()
                        parser.feed(content)
                        content = ''.join(parser.parts)
                    preview = display_text(content) or None
                except (ValueError, LookupError, TypeError):
                    continue
                if preview:
                    break
            if preview:
                break
    except (ValueError, AttributeError, IndexError, HeaderParseError):
        pass
    return sender, subject, name, preview
