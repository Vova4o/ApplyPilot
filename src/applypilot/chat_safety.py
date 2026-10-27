"""Pure safeguards shared by the verified HH browser chat adapter."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def numeric_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,20}', value):
        raise ValueError('Expected numeric HH identifier')
    return value


def latest_inbound_key(messages: list[dict[str, Any]], complete: bool) -> str | None:
    """Caller must normalize direction from observed HH metadata, never guess it."""
    if not complete or not messages:
        return None
    message = messages[-1]
    if message.get('direction') != 'inbound' or not message.get('id'):
        return None
    if not isinstance(message.get('text'), str) or not message['text'].strip():
        return None  # Attachment-only questions need explicit supported metadata.
    value = {'id': str(message['id']), 'text': message['text'],
             'attachments': message.get('attachments', [])}
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_binding(thread: dict[str, Any], thread_id: str,
                     vacancy_id: str, company: str, inbound_key: str) -> None:
    numeric_id(thread_id)
    numeric_id(vacancy_id)
    if (thread.get('thread_id') != thread_id or thread.get('vacancy_id') != vacancy_id
            or thread.get('company') != company or not company.strip()):
        raise ValueError('Chat/vacancy/company binding changed; reread thread')
    if not re.fullmatch(r'[0-9a-f]{64}', inbound_key):
        raise ValueError('Expected inbound key returned by chat_read')
    latest_key = latest_inbound_key(thread.get('messages', []), thread.get('complete') is True)
    if latest_key != inbound_key:
        raise ValueError('Latest inbound changed or is not safely readable; reread thread')
