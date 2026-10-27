from concurrent.futures import ThreadPoolExecutor

from applypilot.chat_journal import ChatJournal


def test_reply_reservation_survives_restart_and_uncertainty(tmp_path):
    path = tmp_path / 'private' / 'chat.sqlite3'
    journal = ChatJournal(path)
    assert journal.reserve('account', '123', '456', 'inbound', 'Reply')
    assert ChatJournal(path).status('account', '123', 'inbound') == 'unknown'
    assert not ChatJournal(path).reserve('account', '123', '456', 'inbound', 'Different')
    journal.finish('account', '123', 'inbound', 'sent')
    assert journal.status('account', '123', 'inbound') == 'sent'
    assert path.stat().st_mode & 0o777 == 0o600
    assert journal.reserve('account', '123', '456', 'next-inbound', 'Reply')


def test_concurrent_reservation_only_one_wins(tmp_path):
    journal = ChatJournal(tmp_path / 'chat.sqlite3')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: journal.reserve('a', '1', '2', 'k', 'r'), range(2)))
    assert sorted(results) == [False, True]
