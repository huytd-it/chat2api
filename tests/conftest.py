import os

import pytest

from chat2api import settings


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
