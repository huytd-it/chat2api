from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False

    def as_list(self) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in self.messages]


class IntegrateRequest(BaseModel):
    url: str
    headed: bool = False
    # Bắt buộc chọn trước: đăng nhập lúc tích hợp gắn thẳng vào profile này
    # thay vì rơi vào một profile tự sinh ngoài ý muốn ở lần khởi động sau.
    profile_id: int


class RecipeRenameRequest(BaseModel):
    slug: str


class RecipePromptSpec(BaseModel):
    input_selector: str
    input_mode: str = "fill"      # fill | type
    submit: str = "Enter"         # "Enter" hoặc "click:<css selector nút gửi>"


class RecipeDoneSignalSpec(BaseModel):
    type: str = "stable_text"     # stable_text | selector_appear | selector_disappear | copy_button
    selector: str | None = None
    quiet_ms: int | None = None
    timeout_ms: int | None = None
    scope: str | None = None                # copy_button: after | inside | page
    fallback_quiet_ms: int | None = None    # copy_button: đường lùi về stable_text


class RecipeResponseSpec(BaseModel):
    last_message_selector: str
    done_signal: RecipeDoneSignalSpec = RecipeDoneSignalSpec()
    # "markdown" giữ lại cấu trúc khối (heading, list, code) khi đọc câu trả
    # lời; bỏ trống là lấy text thuần.
    format: str | None = None
    # Kèm HTML gốc của câu trả lời trong bản ghi session, để soi lại sau.
    capture_html: bool | None = None


class RecipeNewChatSpec(BaseModel):
    url: str | None = None
    selector: str | None = None


class RecipeTimingSpec(BaseModel):
    ready_delay_ms: int | None = None
    input_delay_ms: int | None = None
    ready_timeout_ms: int | None = None


class RecipeModelSpec(BaseModel):
    id: str


class RecipeManualSpec(BaseModel):
    """Recipe tự nhập tay (không qua analyzer AI) — người dùng tự khai CSS
    selector, thường là khi site quá lạ hoặc analyzer đoán selector sai."""

    slug: str
    url: str
    prompt: RecipePromptSpec
    response: RecipeResponseSpec
    models: list[RecipeModelSpec]
    new_chat: RecipeNewChatSpec | None = None
    timing: RecipeTimingSpec | None = None
    keep_context: bool = True
    # Số lượt chạy ẩn danh cho phép trước khi bắt buộc thêm account đăng nhập.
    # Để trống = không giới hạn (site không cần đăng nhập, hoặc thêm account sau).
    anon_trial_limit: int | None = None

    def to_recipe_dict(self) -> dict:
        data = self.model_dump(exclude={"anon_trial_limit"}, exclude_none=True)
        if self.anon_trial_limit is not None:
            data.setdefault("login", {})["anon_trial_limit"] = self.anon_trial_limit
        return data


class RecipeTestRequest(RecipeManualSpec):
    # Hiện browser để người dùng quan sát lúc kiểm tra selector — recipe lưu
    # xuống đĩa vẫn luôn chạy headless, cờ này chỉ áp dụng cho lượt test.
    headed: bool = False


class RecipeEditRequest(BaseModel):
    """Sửa một recipe ĐÃ có, theo một trong hai đường.

    `yaml`: toàn văn recipe.yaml do người dùng tự gõ — đường mạnh nhất, giữ
    được cả những khóa mà biểu mẫu không mô hình hóa (`response.format`,
    `login.accounts`...).

    `patch`: mảnh recipe do biểu mẫu dựng, server deep-merge vào file đang có
    nên các khóa ngoài biểu mẫu KHÔNG bị mất. Giá trị `null` trong patch nghĩa
    là xóa khóa đó (ví dụ bỏ `new_chat`).
    """

    yaml: str | None = None
    patch: dict | None = None


class RecipeEditTestRequest(RecipeEditRequest):
    # Chạy thử bản đang sửa mà chưa ghi xuống đĩa.
    headed: bool = False


class AddAccountRequest(BaseModel):
    name: str


class AccountLoginRequest(BaseModel):
    """Mở browser đăng nhập cho một domain (không buộc vào recipe nào)."""

    domain: str = ""
    url: str = ""
    name: str = ""


class SaveAccountRequest(BaseModel):
    """Lưu phiên đăng nhập vừa mở.

    `domain` để trống là hợp lệ: server đọc cookie của context rồi tự suy ra
    domain (§6.1, bậc 4 của "tự dò domain").
    """

    domain: str = ""
    name: str


class ProfileCreateRequest(BaseModel):
    name: str
    engine: str | None = None
    headless: bool | None = None
    max_tabs: int | None = None
    proxy: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    timezone: str | None = None
    viewport: str | None = None
    notes: str | None = None


class ProfileUpdateRequest(ProfileCreateRequest):
    name: str | None = None
    is_default: bool | None = None


class ProfileOpenRequest(BaseModel):
    url: str = ""
    # Khóa tab tùy chọn cho màn test hàng loạt. Bỏ trống giữ nguyên tab mở tay
    # truyền thống; mỗi khóa khác nhau tạo một tab riêng trong cùng profile.
    tab_key: str = ""


class TestTargetOpenRequest(BaseModel):
    # Bỏ trống ⇒ server tự chọn recipe đầu tiên phục vụ domain của account. Mở
    # nhiều domain một lượt thì client không có sẵn model cho từng cái.
    model: str = ""
    account_id: int


class ProfileAccountRequest(BaseModel):
    domain: str
    label: str = ""


class SettingsRequest(BaseModel):
    values: dict[str, str]


class ApiKeyCreateRequest(BaseModel):
    label: str
    # "chat" = gọi /v1/*, "admin" = gọi /admin/*. Bỏ trống ⇒ cả hai.
    scopes: str | None = None

class SessionUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = None


class SessionDeleteRequest(BaseModel):
    ids: list[str] | None = None
    all: bool = False


class SessionForkRequest(BaseModel):
    up_to_seq: int
