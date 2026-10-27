"""HH chat browser adapter using selectors observed in an authenticated session."""
from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from itertools import pairwise
from urllib.parse import urlparse

from .chat_safety import latest_inbound_key, numeric_id, validate_binding
from .session import classify_session_page


class ChatUnavailable(RuntimeError):
    pass


def clean_company(value):
    return ' '.join(value.split())


def frame_thread(url):
    parsed = urlparse(url)
    match = re.fullmatch(r'/chat/([0-9]{1,20})', parsed.path.rstrip('/'))
    if parsed.scheme != 'https' or parsed.hostname != 'chatik.hh.ru' or not match:
        return None
    return match.group(1)


def vacancy_from_url(url):
    parsed = urlparse(url)
    match = re.fullmatch(r'/vacancy/([0-9]{1,20})', parsed.path.rstrip('/'))
    if parsed.scheme != 'https' or parsed.hostname != 'hh.ru' or not match:
        raise ChatUnavailable('Chat vacancy link not verified')
    return match.group(1)


@contextmanager
def browser_page(config):
    from playwright.sync_api import sync_playwright

    from .cli import _hh_proxy
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(config.root / 'private' / 'browsers'))
    with _hh_proxy() as proxy, sync_playwright() as pw:
        kwargs = {'headless': True}
        if proxy:
            kwargs['proxy'] = {'server': proxy}
        browser = pw.chromium.launch(**kwargs)
        context = None
        try:
            context = browser.new_context(storage_state=str(config.data_dir / 'hh_session.json'))
            page = context.new_page()
            page.set_default_timeout(10000)
            yield page
        finally:
            if context is not None:
                context.close()
            browser.close()


def open_thread(page, vacancy_id=None, thread_id=None):
    if vacancy_id is not None:
        numeric_id(vacancy_id)
    if thread_id is not None:
        numeric_id(thread_id)
    page.goto('https://hh.ru/applicant/negotiations', wait_until='domcontentloaded', timeout=20000)
    auth = classify_session_page(page.url, page.locator('body').inner_text())
    if auth.status != 'confirmed':
        raise ChatUnavailable('Authenticated HH application page unavailable')
    rows = page.locator('[data-qa="negotiations-item"]')
    selected = None
    for index in range(min(rows.count(), 100)):
        row = rows.nth(index)
        link = row.locator('[data-qa="negotiations-item-vacancy"]').first
        href = link.get_attribute('href') or ''
        absolute = 'https://hh.ru' + href if href.startswith('/') else href
        try:
            matches = vacancy_from_url(absolute) == vacancy_id
        except ChatUnavailable:
            matches = False
        if matches or (thread_id is not None and row.locator('[data-qa="open_chat"]').count()):
            selected = row
            break
    if selected is None:
        raise ChatUnavailable('Vacancy not on current authenticated applications page')
    selected.locator('[data-qa="open_chat"]').click()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        frames = [frame for frame in page.frames if frame_thread(frame.url)]
        if len(frames) == 1:
            frame = frames[0]
            if thread_id is not None and frame_thread(frame.url) != thread_id:
                frame.locator('[data-qa="chatik-back-to-chats-button"]').click()
                walk_chat_links(frame, 100, target=thread_id)
                anchor = frame.locator(f'[data-qa="chatik-open-chat-{thread_id}"]')
                if not anchor.count():
                    raise ChatUnavailable('Thread not found in bounded virtual chat list')
                href = anchor.get_attribute('href') or ''
                if frame_thread('https://chatik.hh.ru' + href) != thread_id:
                    raise ChatUnavailable('Thread link not verified')
                anchor.click()
                frame.wait_for_url(lambda url: frame_thread(str(url)) == thread_id)
            if thread_id is not None and frame_thread(frame.url) != thread_id:
                raise ChatUnavailable('Requested chat navigation not confirmed')
            frame.locator('[data-qa="chatik-header-vacancy-link"]').wait_for(state='visible')
            return frame
        page.wait_for_timeout(100)
    raise ChatUnavailable('Verified HH chat iframe unavailable')


def read_frame(frame):
    thread_id = frame_thread(frame.url)
    if not thread_id:
        raise ChatUnavailable('Unexpected chat origin')
    header = frame.locator('[data-qa="participant-info-title"]').first
    company = clean_company(header.inner_text())
    vacancy_id = vacancy_from_url(frame.locator(
        '[data-qa="chatik-header-vacancy-link"]').first.get_attribute('href') or '')
    roots = frame.locator('[data-qa^="chatik-chat-message-"]')
    messages = []
    for index in range(min(roots.count(), 400)):
        root = roots.nth(index)
        qa = root.get_attribute('data-qa') or ''
        match = re.fullmatch(r'chatik-chat-message-([0-9]+)', qa)
        if not match:
            continue  # Ignore observed nested ...-text nodes.
        classes = root.evaluate('(node) => [node, ...node.querySelectorAll("[class]")]'
                                '.map(n => String(n.className)).join(" ")')
        if 'chat-bubble_outgoing--' in classes or 'message_my--' in classes:
            direction = 'outbound'
        elif 'chat-bubble_bot--' in classes or 'chat-bubble_with-left-tail--' in classes:
            direction = 'inbound'
        else:
            direction = 'unknown'
        text = root.locator('[data-qa="chat-bubble-text"]').first
        value = text.inner_text() if text.count() else ''
        messages.append({'id': match.group(1), 'direction': direction, 'text': value})
    # DOM message order must agree with the observed ascending message IDs.
    ordered = all(int(left['id']) < int(right['id'])
                  for left, right in pairwise(messages))
    complete = (bool(messages) and ordered and roots.count() <= 400
                and len(messages[-1]['text']) <= 12000)
    result = {'thread_id': thread_id, 'vacancy_id': vacancy_id, 'company': company,
              'complete': complete, 'messages': messages[-100:]}
    result['latest_inbound_key'] = latest_inbound_key(result['messages'], complete)
    return result


def read_stable(frame):
    frame.locator('[data-qa^="chatik-chat-message-"]').first.wait_for(state='visible')
    previous = read_frame(frame)
    for _ in range(5):
        frame.page.wait_for_timeout(200)
        current = read_frame(frame)
        if current == previous:
            return current
        previous = current
    previous['complete'] = False
    previous['latest_inbound_key'] = None
    return previous


def read_chat(config, thread_id):
    with browser_page(config) as page:
        return read_stable(open_thread(page, thread_id=thread_id))


def list_chats(config, limit=20):
    with browser_page(config) as page:
        frame = open_first_thread(page)
        frame.locator('[data-qa="chatik-back-to-chats-button"]').click()
        result = walk_chat_links(frame, limit)
        return {'chats': result, 'incomplete': True,
                'reason': 'Bounded HH virtual list scroll; older chats may be absent'}


def walk_chat_links(frame, limit, target=None):
    anchors = frame.locator('[data-qa^="chatik-open-chat-"]')
    anchors.first.wait_for(state='visible')
    collected = {}
    no_progress = 0
    for _ in range(30):
        previous_count = len(collected)
        for index in range(anchors.count()):
            anchor = anchors.nth(index)
            href = anchor.get_attribute('href') or ''
            thread_id = frame_thread('https://chatik.hh.ru' + href)
            if not thread_id:
                continue  # Actual list skeleton uses /chat/-1.
            if target == thread_id:
                return list(collected.values())
            title = anchor.locator('[data-qa="chat-cell-title"]').first
            subtitle = anchor.locator('[data-qa="chat-cell-subtitle"]').first
            collected[thread_id] = {
                'thread_id': thread_id,
                'title': title.inner_text()[:500] if title.count() else '',
                'subtitle': subtitle.inner_text()[:1000] if subtitle.count() else '',
                'has_badge': anchor.locator('[data-qa="chatik-info-badges"]').count() > 0}
            if target is None and len(collected) >= limit:
                return list(collected.values())[:limit]
        no_progress = no_progress + 1 if len(collected) == previous_count else 0
        if no_progress >= 3 or not anchors.count():
            break
        moved = anchors.first.evaluate('''(n) => {
            for (let p=n; p; p=p.parentElement) {
                if (p.scrollHeight > p.clientHeight+20 &&
                    /auto|scroll/.test(getComputedStyle(p).overflowY)) {
                    const before=p.scrollTop;
                    p.scrollTop += p.clientHeight * 0.8;
                    return p.scrollTop !== before;
                }
            }
            return false;
        }''')
        frame.page.wait_for_timeout(600)
        if not moved and no_progress >= 2:
            break
    return list(collected.values())[:limit]


def open_first_thread(page):
    # Select only a real existing application row, then obtain its observed chat iframe.
    page.goto('https://hh.ru/applicant/negotiations', wait_until='domcontentloaded', timeout=20000)
    if classify_session_page(page.url, page.locator('body').inner_text()).status != 'confirmed':
        raise ChatUnavailable('Authenticated HH application page unavailable')
    buttons = page.locator('[data-qa="negotiations-item"] [data-qa="open_chat"]')
    if not buttons.count():
        raise ChatUnavailable('No application chat controls available')
    buttons.first.click()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        frames = [frame for frame in page.frames if frame_thread(frame.url)]
        if len(frames) == 1:
            frames[0].locator('[data-qa="chatik-header-vacancy-link"]').wait_for(state='visible')
            return frames[0]
        page.wait_for_timeout(100)
    raise ChatUnavailable('Verified HH chat iframe unavailable')


def send_chat(config, journal, account, thread_id, vacancy_id, company, inbound_key, reply):
    with browser_page(config) as page:
        frame = open_thread(page, thread_id=thread_id)
        before = read_stable(frame)
        validate_binding(before, thread_id, vacancy_id, clean_company(company), inbound_key)
        if not journal.reserve(account, thread_id, vacancy_id, inbound_key, reply):
            return {'status': journal.status(account, thread_id, inbound_key), 'sent': False,
                    'retry': False, 'reason': 'Reply already reserved; no duplicate send'}
        clicked = False
        try:
            composer = frame.locator('[data-qa="chatik-message-input"] [data-qa="text-input"]')
            composer.fill(reply)
            current = read_stable(frame)
            validate_binding(current, thread_id, vacancy_id, clean_company(company), inbound_key)
            previous_ids = {message['id'] for message in current['messages']}
            boundary = max(int(message_id) for message_id in previous_ids)
            clicked = True  # Any click exception is uncertain, never retry automatically.
            frame.locator('[data-qa="chatik-do-send-message"]').click()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                after = read_frame(frame)
                verified = any(message['id'] not in previous_ids and int(message['id']) > boundary
                               and message['direction'] == 'outbound' and message['text'] == reply
                               for message in after['messages'])
                if (verified and after['thread_id'] == thread_id
                        and after['vacancy_id'] == vacancy_id
                        and after['company'] == clean_company(company)):
                    journal.finish(account, thread_id, inbound_key, 'sent')
                    return {'status': 'sent', 'sent': True, 'retry': False}
                page.wait_for_timeout(200)
            journal.finish(account, thread_id, inbound_key, 'unknown')
            return {'status': 'unknown', 'sent': False, 'retry': False,
                    'reason': 'No new exact outgoing message confirmed; inspect thread manually'}
        except Exception:  # noqa: BLE001 - an uncertain send must never be retried automatically
            state = 'unknown' if clicked else 'stale'
            journal.finish(account, thread_id, inbound_key, state)
            return {'status': state, 'sent': False, 'retry': False,
                    'reason': 'Chat changed or browser failed; '
                              'inspect thread before another action'}
