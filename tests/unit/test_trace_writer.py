import re
from pathlib import Path
from types import SimpleNamespace

from chat2api.agents.trace_writer import _domain_dir, find_trace, write_trace


def test_domain_dir():
    assert _domain_dir("https://www.Chat.Z.ai/c/1", "x") == "chat.z.ai"
    assert _domain_dir("chat.z.ai", "x") == "chat.z.ai"
    assert _domain_dir("", "fallback") == "fallback"


def test_write_trace_datetime_name_in_domain_folder(tmp_path):
    cfg = SimpleNamespace(traces_dir=tmp_path / "traces")
    meta = {"jobId": "abc123", "url": "https://chat.z.ai/"}
    a = write_trace("abc123", "chat-z-ai", [{"kind": "click"}], meta, cfg=cfg)
    b = write_trace("abc123", "chat-z-ai", [], meta, cfg=cfg)

    pa = Path(a["json"])
    assert pa.parent == tmp_path / "traces" / "chat.z.ai"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-chat-z-ai\.json", pa.name)
    assert Path(a["md"]).is_file()
    assert a["json"] != b["json"]  # trùng giây không ghi đè

    assert find_trace(tmp_path / "traces", "abc123", "md") is not None
    assert find_trace(tmp_path / "traces", "missing", "json") is None
