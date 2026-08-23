from chat2api.prompt import flatten_messages
from chat2api.schemas import ChatRequest


def test_single_user():
    assert flatten_messages([{"role": "user", "content": "hi"}]) == "User: hi"


def test_system_first_then_turns():
    msgs = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    assert flatten_messages(msgs) == "System: be brief\n\nUser: q1\n\nAssistant: a1\n\nUser: q2"


def test_empty_assistant_dropped():
    msgs = [{"role": "assistant", "content": ""}, {"role": "user", "content": "q"}]
    assert flatten_messages(msgs) == "User: q"


def test_chat_request_as_list():
    req = ChatRequest.model_validate(
        {"model": "a/b", "messages": [{"role": "user", "content": "x"}], "stream": True}
    )
    assert req.as_list() == [{"role": "user", "content": "x"}]
    assert req.stream is True
