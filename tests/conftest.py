import atexit
import os
import shutil
import tempfile

import pytest

# Phải đặt TRƯỚC mọi import chạm tới `chat2api.main`: module đó dựng `Config()`
# ngay lúc import, và `Config()` đổ bảng `setting` của DB trong CHAT2API_DATA_DIR
# vào os.environ. Trỏ vào kho thật của máy đang code thì một lần bấm Lưu ở app
# sẽ lặng lẽ đổi kết quả cả suite — đúng những gì đã xảy ra với POOL_MAX_PROFILES.
_DATA_DIR = tempfile.mkdtemp(prefix="chat2api-tests-")
os.environ["CHAT2API_DATA_DIR"] = _DATA_DIR
atexit.register(shutil.rmtree, _DATA_DIR, True)

from chat2api import settings  # import phải nằm sau khi ghim CHAT2API_DATA_DIR


@pytest.fixture(autouse=True)
def _isolate_settings_env():
    """Trả os.environ và trạng thái module `settings` về nguyên trạng sau mỗi test.

    `settings.save()` và `settings.preload()` cố ý ghi vào `os.environ` — đó là
    cách giá trị trong bảng `setting` đến được Config và các provider. Nhưng
    trong một tiến trình pytest thì os.environ dùng chung cho cả phiên: một test
    lưu `BROWSER_ENGINE=cloak` sẽ lặng lẽ đổi engine của mọi test chạy sau nó.
    """
    keys = tuple(settings.BY_KEY)
    before = {key: os.environ.get(key) for key in keys}
    env_keys, injected = set(settings._env_keys), set(settings._injected)
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    settings._env_keys = env_keys
    settings._injected = injected
