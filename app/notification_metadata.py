"""Extract notification fields from already fetched headers; no remote reads."""

import unicodedata
from email import policy
from email.errors import HeaderParseError
from email.parser import BytesParser


def display_text(value, limit=200):
    text = ''.join(char for char in str(value) if not unicodedata.category(char).startswith('C')).strip()
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
