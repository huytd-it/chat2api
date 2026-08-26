import os
from pathlib import Path

from dotenv import load_dotenv

from . import settings


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Config:
    def __init__(self) -> None:
        # Giữ lại đường dẫn để trang Settings ghi vào đúng file đã nạp.
        self.env_path = Path.cwd() / ".env"
        load_dotenv(self.env_path, override=False)
        # Kho SQLite + profile Chromium + blob đính kèm (docs/design-v2.md §1).
        # Thư mục chỉ được tạo khi server thật sự chạy, không phải lúc import.
        self.data_dir = Path(_env("CHAT2API_DATA_DIR", "./data"))
        self.db_path = self.data_dir / "chat2api.db"
        # Chốt xem khoá nào do môi trường/.env đặt (chúng thắng DB), rồi đổ bảng
        # `setting` vào os.environ cho phần còn lại. Phải chạy TRƯỚC mọi _env()
        # bên dưới, và chỉ đọc — `Config()` chạy lúc import module main.
        settings.capture_env()
        settings.preload(self.db_path)
        self.api_keys = [k.strip() for k in _env("CHAT2API_KEYS").split(",") if k.strip()]
        self.recipes_dir = Path(_env("RECIPES_DIR", "./recipes"))
        self.agent_llm_base_url = _env("AGENT_LLM_BASE_URL").rstrip("/")
        self.agent_llm_api_key = _env("AGENT_LLM_API_KEY")
        self.agent_llm_model = _env("AGENT_LLM_MODEL")
        self.enable_fallback = _env("ENABLE_AGENT_FALLBACK", "false").lower() == "true"
        self.pool_max_contexts = int(_env("POOL_MAX_CONTEXTS", "3"))
        self.pool_acquire_timeout = int(_env("POOL_ACQUIRE_TIMEOUT", "30"))
        self.browser_engine = _env("BROWSER_ENGINE", "playwright")
        # storage_state (mặc định) | profile. Đường profile dùng
        # launch_persistent_context: một profile giữ đăng nhập của MỌI domain và
        # chạy nhiều recipe song song, mỗi recipe một tab. Đây là opt-in lâu dài,
        # không phải giai đoạn chuyển tiếp — xem docs/design-v2.md §9.
        mode = _env("BROWSER_PROFILE_MODE", "storage_state").strip().lower()
        self.browser_profile_mode = mode if mode in {"storage_state", "profile"} else "storage_state"
        self.profiles_dir = self.data_dir / "profiles"
        # Số profile (mỗi profile = 1 tiến trình Chromium) giữ mở cùng lúc.
        # Bàn test Sessions mở nhiều profile/domain/account song song, nên trần
        # 2 là quá chật — profile đang chạy sẽ bị đóng ngay giữa request.
        self.pool_max_profiles = max(1, int(_env("POOL_MAX_PROFILES", "6")))
        # Trần số tab trong một profile; vượt thì đóng tab RẢNH ít dùng nhất.
        self.profile_max_tabs = max(1, int(_env("PROFILE_MAX_TABS", "8")))
        self.recipe_timeout_ms = int(_env("RECIPE_TIMEOUT_MS", "120000"))
        self.integrate_max_rounds = int(_env("INTEGRATE_MAX_ROUNDS", "5"))
        # Site không yêu cầu đăng nhập vẫn được publish, nhưng chỉ cho dùng thử
        # giới hạn số lượt trước khi bắt buộc thêm tài khoản (0 = không giới hạn).
        self.anon_trial_limit = int(_env("ANON_TRIAL_LIMIT", "20"))
