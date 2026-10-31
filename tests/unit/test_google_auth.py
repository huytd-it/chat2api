"""Phần thuần của google_auth: TOTP, phân loại URL, kho google_identity.

Không mở browser — luồng đăng nhập thật cần tài khoản Google thật.
"""

import pytest

from chat2api import google_auth, profiles, store


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        store.shutdown()


def test_totp_matches_rfc6238_vector():
    # RFC 6238 phụ lục B: secret ASCII "12345678901234567890", T=59 → 94287082.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert google_auth.totp(secret, at=59, digits=8) == "94287082"
    assert google_auth.totp(secret.lower().replace("GE", "ge "), at=59) == "287082"


@pytest.mark.parametrize("url,status", [
    ("https://myaccount.google.com/?hl=en", "signed_in"),
    ("https://accounts.google.com/v3/signin/identifier?continue=x", "signed_out"),
    ("https://accounts.google.com/v3/signin/challenge/pwd?TL=1", "signed_out"),
    ("https://accounts.google.com/v3/signin/challenge/ipp/collect", "verify_required"),
    ("https://accounts.google.com/signin/v2/challenge/az?x=1", "verify_required"),
    ("https://accounts.google.com/v3/signin/rejected?x=1", "verify_required"),
    ("https://www.google.com/account/about/?hl=en", "signed_out"),
    ("https://example.com/", "unknown"),
])
def test_classify_url(url, status):
    assert google_auth.classify_url(url) == status


def test_parse_list_accounts():
    text = '["gaia.l.a.r",[["gaia.l.a",1,"A","Foo.Bar@gmail.com","x",1,1,0],' \
           '["gaia.l.a",1,"B","work@corp.vn","y",1,1,0]]]'
    assert google_auth.parse_list_accounts(text) == ["foo.bar@gmail.com", "work@corp.vn"]


def test_save_identity_masks_and_keeps_secrets(db, tmp_path):
    p = profiles.ensure_profile("main", tmp_path / "profiles")
    item = google_auth.save_identity(p.id, {"email": "Me@Gmail.com", "password": "pw",
                                            "totp_secret": "GEZDGNBVGY3TQOJQ"})
    assert item["email"] == "me@gmail.com"
    assert item["has_password"] and item["has_totp"]
    assert "password" not in item and "totp_secret" not in item

    # Gửi lại mà không kèm secret ⇒ giữ nguyên mật khẩu cũ.
    google_auth.save_identity(p.id, {"email": "me@gmail.com", "password": "", "auto_login": False})
    raw = google_auth.secrets_of(p.id)
    assert raw["password"] == "pw" and raw["auto_login"] == 0

    google_auth.save_identity(p.id, {"clear_password": True})
    assert google_auth.secrets_of(p.id)["password"] == ""


def test_save_identity_rejects_bad_input(db, tmp_path):
    p = profiles.ensure_profile("main", tmp_path / "profiles")
    with pytest.raises(ValueError):
        google_auth.save_identity(p.id, {"email": "not-an-email"})
    with pytest.raises(ValueError):
        google_auth.save_identity(p.id, {"email": "a@b.co", "totp_secret": "!!!"})


def test_record_status_and_list(db, tmp_path):
    p = profiles.ensure_profile("main", tmp_path / "profiles")
    google_auth.record_status(p.id, "verify_required", detail="SMS",
                              verify_url="https://accounts.google.com/challenge/ipp")
    items = google_auth.list_identities()
    assert items[0]["profile_name"] == "main"
    assert items[0]["status"] == "verify_required" and items[0]["checked_at"]
    assert google_auth.delete_identity(p.id)
    assert google_auth.get_identity(p.id) is None


def test_label_from_email():
    assert google_auth._label_from_email("Foo.Bar+1@gmail.com") == "foo-bar-1"
