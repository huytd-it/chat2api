import concurrent.futures

import pytest

from chat2api import store
from chat2api.automation import journal
from chat2api.errors import OpenAIError


@pytest.fixture
def db(tmp_path):
    db = store.connect(tmp_path / "automation.db")
    db.migrate()
    yield db
    store.shutdown()


def test_replay_survives_restart_and_counts_once(db):
    journal.claim("book", "chunk1", "qwen/model", "digest")
    journal.submitted("chunk1")
    journal.bind("book", 4, "https://chat.qwen.ai/c/one")
    journal.complete("book", "chunk1", {"text": "translated"})
    path = db.db_path
    store.shutdown()
    store.connect(path).migrate()
    assert journal.claim("book", "chunk1", "qwen/model", "digest").result == {"text": "translated"}
    assert journal.get_session("book")["successes"] == 1
    assert journal.get_session("book")["account_id"] == 4


def test_conflict_and_unknown_outcome_block_resubmit(db):
    journal.claim("book", "chunk1", "qwen/model", "digest")
    with pytest.raises(OpenAIError) as conflict:
        journal.claim("book", "chunk1", "qwen/model", "changed")
    assert conflict.value.code == "idempotency_conflict"
    journal.submitted("chunk1")
    journal.fail("book", "chunk1", "connection lost")
    with pytest.raises(OpenAIError) as unknown:
        journal.claim("book", "chunk1", "qwen/model", "digest")
    assert unknown.value.code == "operation_unresolved"
    with pytest.raises(OpenAIError) as busy:
        journal.claim("book", "chunk2", "qwen/model", "digest2")
    assert busy.value.code == "session_unresolved"
    assert journal.get_session("book")["successes"] == 0


def test_submit_gate_requires_prepared_operation_and_its_session_reservation(db):
    with pytest.raises(OpenAIError) as missing:
        journal.submitted("missing")
    assert missing.value.code == "operation_not_prepared"
    journal.claim("book", "chunk1", "qwen/model", "digest")
    journal.submitted("chunk1")
    with pytest.raises(OpenAIError):
        journal.submitted("chunk1")
    journal.complete("book", "chunk1", {"ok": True})
    with pytest.raises(OpenAIError):
        journal.submitted("chunk1")
    journal.claim("book", "chunk2", "qwen/model", "digest2")
    with db.connection() as conn:
        conn.execute("UPDATE automation_session SET busy_operation=NULL WHERE id='book'")
    with pytest.raises(OpenAIError):
        journal.submitted("chunk2")


def test_atomic_submit_gate_cannot_rebind_a_losing_account(db):
    journal.claim("book", "chunk", "qwen/model", "digest")
    def submit(account_id):
        try:
            journal.submit_bound("book", "chunk", "qwen/model", account_id, None)
            return account_id
        except OpenAIError:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        winners = [value for value in pool.map(submit, range(1, 5)) if value is not None]
    assert len(winners) == 1
    assert journal.get_session("book")["account_id"] == winners[0]


def test_submit_gate_rejects_changed_context_without_writing(db):
    journal.claim("book", "chunk", "qwen/model", "digest")
    journal.bind("book", 7, "https://chat.qwen.ai/c/original")
    with pytest.raises(OpenAIError) as conflict:
        journal.submit_bound("book", "chunk", "qwen/model", 7, "https://chat.qwen.ai/c/other")
    assert conflict.value.code == "session_context_conflict"
    assert journal.get_session("book")["conversation_url"] == "https://chat.qwen.ai/c/original"
    assert db.query("SELECT state FROM automation_operation WHERE id='chunk'")[0]["state"] == "prepared"


def test_failure_before_submit_can_retry(db):
    journal.claim("book", "chunk1", "qwen/model", "digest")
    journal.fail("book", "chunk1", "model unavailable")
    assert journal.claim("book", "chunk1", "qwen/model", "digest").result is None


def test_atomic_claim_across_threads(db):
    def claim(number):
        try:
            journal.claim("book", f"chunk{number}", "qwen/model", str(number))
            return True
        except OpenAIError:
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(4))) == 1


def test_rollover_and_books_are_isolated(db):
    for n in range(10):
        journal.claim("book", f"chunk{n}", "qwen/model", str(n))
        journal.complete("book", f"chunk{n}", {"n": n})
    journal.bind("book", 4, "https://chat.qwen.ai/c/one")
    journal.claim("other", "other1", "qwen/model", "other")
    journal.rollover("book")
    state = journal.get_session("book")
    assert state["successes"] == 0 and state["generation"] == 1
    assert state["conversation_url"] is None and state["account_id"] == 4
    assert journal.get_session("other")["generation"] == 0
    assert journal.claim("book", "chunk0", "qwen/model", "0").result == {"n": 0}
