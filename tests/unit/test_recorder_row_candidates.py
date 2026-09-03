"""`_row` / `enrich_event` phải đọc được cả trace đời cũ lẫn trace có `candidates`.

`_row` là thứ LLM thực sự đọc khi sinh recipe, nên `unique=` phải luôn có mặt và
phải nói đúng sự thật — kể cả với trace ghi bằng bản recorder trước khi có ứng viên.
"""

from chat2api.agents.recorder import _best_selector, _first_unique, _row, enrich_event


def test_old_trace_without_candidates_still_renders():
    ev = {"kind": "click", "selector": "#send", "tag": "button", "label": "Gửi"}
    enrich_event(ev)
    assert ev["candidates"] == []
    assert ev["selectors"]["best"] == ""
    row = _row(1, ev)
    # Không có ứng viên nào được verify => phải nói unique=false, không được im lặng.
    assert "sel='#send'" in row
    assert "unique=false" in row


def test_verified_candidate_becomes_the_headline_selector():
    ev = {
        "kind": "click",
        "selector": "div:nth-of-type(3)",
        "selectors": {"primary": "div:nth-of-type(3)", "best": '[data-testid="send"]'},
        "candidates": [
            {"sel": '[data-testid="send"]', "kind": "testid", "unique": True, "count": 1},
            {"sel": "button.send", "kind": "cls", "unique": False, "count": 4},
        ],
        "tag": "button",
        "label": "Gửi",
    }
    enrich_event(ev)
    row = _row(1, ev)
    assert "sel='[data-testid=\"send\"]'" in row
    assert "unique=true" in row
    assert "div:nth-of-type(3)" not in row
    assert " alt=" not in row  # đã duy nhất thì không cần bày ứng viên thay thế


def test_ambiguous_selector_is_flagged_and_offers_alternatives():
    ev = {
        "kind": "click",
        "selectors": {"primary": "button", "best": ""},
        "candidates": [
            {"sel": '[aria-label="Sao chép"]', "kind": "aria", "unique": False, "count": 2},
            {"sel": "button.copy", "kind": "cls", "unique": False, "count": 2},
        ],
        "tag": "button",
        "label": "Sao chép",
    }
    enrich_event(ev)
    row = _row(1, ev)
    assert "unique=false" in row
    assert "alt=" in row and "Sao chép" in row


def test_best_is_derived_from_candidates_when_absent():
    """Event chỉ có `candidates` (thiếu `selectors.best`) vẫn suy ra được."""
    ev = {
        "kind": "click",
        "selectors": {"primary": "button"},
        "candidates": [
            {"sel": "button.x", "kind": "cls", "unique": False, "count": 3},
            {"sel": "#composer button", "kind": "anchored", "unique": True, "count": 1},
        ],
    }
    enrich_event(ev)
    assert ev["selectors"]["best"] == "#composer button"
    assert "unique=true" in _row(1, ev)


def test_actionable_candidates_used_for_icon_only_button():
    ev = {
        "kind": "click",
        "selectors": {"primary": "div", "best": ""},
        "candidates": [],
        "tag": "div",
        "actionable": {
            "isSelf": False,
            "tag": "button",
            "selector": "button",
            "cssPath": "body > div:nth-of-type(2) > button",
            "best": '[data-testid="send"]',
            "candidates": [
                {"sel": '[data-testid="send"]', "kind": "testid", "unique": True, "count": 1},
            ],
        },
    }
    enrich_event(ev)
    row = _row(1, ev)
    assert "actionable='[data-testid=\"send\"]'" in row
    assert "actionableUnique=true" in row
    # cssPath giòn không được lên làm selector của nút nữa
    assert "nth-of-type" not in row


def test_helpers_tolerate_garbage():
    assert _first_unique(None) == ""
    assert _first_unique([{"unique": True}]) == ""  # thiếu `sel` thì bỏ qua
    assert _best_selector(None, None, "#fb") == ("#fb", False, [])
