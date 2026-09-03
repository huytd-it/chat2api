from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False

    def as_list(self) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in self.messages]


class ImageGenerateRequest(BaseModel):
    model: str
    prompt: str = Field(min_length=1, max_length=4000)
    n: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024")
    response_format: str = Field(default="b64_json")
    quality: str | None = None
    style: str | None = None
    user: str | None = None


class ImageData(BaseModel):
    url: str | None = None
    b64_json: str | None = None
    revised_prompt: str | None = None


class IntegrateRequest(BaseModel):
    url: str
    headed: bool = False
    # Bắt buộc chọn trước: đăng nhập lúc tích hợp gắn thẳng vào profile này
    # thay vì rơi vào một profile tự sinh ngoài ý muốn ở lần khởi động sau.
    profile_id: int


class RecipeRenameRequest(BaseModel):
    slug: str


class RecipeReanalyzeRequest(BaseModel):
    """Phân tích lại recipe đã có bằng AI — giữ nguyên slug, ghi đè YAML."""
    url: str | None = None
    headed: bool = False
    profile_id: int | None = None


class RecordRequest(BaseModel):
    """Mở phiên ghi thao tác (headed browser, user click/gõ, trace selector)."""

    url: str
    profile_id: int
    slug: str | None = None  # ghi lại recipe đang có thì truyền slug hiện có


class RecordSegmentRequest(BaseModel):
    """Mở/đóng một đoạn ghi trong phiên đang chạy.

    ``action="start"`` mở đoạn cho ``flow`` (đóng đoạn đang mở nếu có);
    ``action="stop"`` đóng đoạn hiện tại và không cần ``flow``.
    """

    action: str = "start"           # start | stop
    flow: str | None = None         # select_model | text | image | video


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
    use_copy_result: bool | None = None
    exclude: str | None = None              # loại nút Copy không thuộc reply
    fallback_quiet_ms: int | None = None    # copy_button: đường lùi về stable_text


class RecipeResponseSpec(BaseModel):
    last_message_selector: str = ""
    done_signal: RecipeDoneSignalSpec = RecipeDoneSignalSpec()
    # "markdown" giữ lại cấu trúc khối (heading, list, code) khi đọc câu trả
    # lời; bỏ trống là lấy text thuần.
    format: str | None = None
    # Kèm HTML gốc của câu trả lời trong bản ghi session, để soi lại sau.
    capture_html: bool | None = None
    # Selector ảnh cho image generation. Nếu có, recipe được coi là image-capable.
    image_selector: str | None = None
    # Nút copy riêng cho từng ảnh (khác nút copy response). Mỗi ảnh có 1 nút.
    # Nếu đặt, flow tạo ảnh sẽ bấm từng nút và đọc clipboard thay vì fetch src.
    image_copy_selector: str | None = None
    image_copy_scope: str | None = None          # after | inside | page (mặc định after)
    image_copy_exclude: str | None = None        # loại nút không thuộc ảnh


class RecipeNewChatSpec(BaseModel):
    url: str | None = None
    selector: str | None = None


class RecipeTimingSpec(BaseModel):
    ready_delay_ms: int | None = None
    input_delay_ms: int | None = None
    ready_timeout_ms: int | None = None


class RecipeAccountSpec(BaseModel):
    name: str
    storage_state: str


class RecipeLoginSpec(BaseModel):
    strategy: str = "round_robin"
    quota: int = 50
    storage_state: str | None = None
    accounts: list[RecipeAccountSpec] | None = None


class RecipeModeSpec(BaseModel):
    # Dropdown chuyển chế độ (thường là Chat vs Image). Nếu site dùng chung 1 URL
    # nhưng chế độ tạo ảnh nằm trong dropdown, đặt selector/action ở đây để
    # _run_images tự bấm trước khi nhập prompt.
    selector: str | None = None            # selector của nút/select chính (để chờ visible)
    image_action: str | None = None        # vd: click:.mode-btn;click:[data-value='image']
    chat_action: str | None = None         # vd: click:.mode-btn;click:[data-value='chat']


class RecipeModelSpec(BaseModel):
    id: str
    # Action chạy trước khi nhập prompt. Bỏ trống để website giữ model mặc định.
    action: str | None = None       # nhiều bước ngăn bằng ;: click:<selector> | select:<selector>
    value: str | None = None        # option value, mặc định dùng id
    capability: str | None = None   # chat | image | both, mặc định chat
    # Flow mà model này chạy — chọn model chính là chọn flow. Thắng `capability`
    # và là cách DUY NHẤT trỏ tới flow tên tự đặt (`flows.deep_research`…).
    flow: str | None = None


class RecipeAnalyzeRequest(BaseModel):
    url: str
    headed: bool = False
    profile_id: int | None = None


class RecipeModelDiscoveryRequest(BaseModel):
    url: str
    headed: bool = False


class RecipeManualSpec(BaseModel):
    """Recipe tự nhập tay (không qua analyzer AI) — người dùng tự khai CSS
    selector, thường là khi site quá lạ hoặc analyzer đoán selector sai."""

    slug: str
    url: str
    prompt: RecipePromptSpec
    response: RecipeResponseSpec
    models: list[RecipeModelSpec]
    mode: RecipeModeSpec | None = None
    new_chat: RecipeNewChatSpec | None = None
    timing: RecipeTimingSpec | None = None
    login: RecipeLoginSpec | None = None
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
    # Flow đem ra thử: select_model | text | image | video. `select_model` chỉ
    # chạy tới bước chọn model rồi dừng, không gửi prompt.
    flow: str = "text"
    # Prompt riêng cho lượt thử; để trống thì dùng mặc định theo flow. KHÔNG
    # đặt tên `prompt` — khóa đó đã là `RecipePromptSpec` của chính recipe.
    test_prompt: str | None = None

    def to_recipe_dict(self) -> dict:
        # Tuỳ chọn của lượt thử không phải một phần của recipe; để lọt vào là
        # `validate_recipe` soi một dict không giống thứ sẽ được ghi xuống đĩa.
        data = super().to_recipe_dict()
        for key in ("headed", "flow", "test_prompt"):
            data.pop(key, None)
        return data


class FlowDuplicateRequest(BaseModel):
    slug: str


class FlowSaveRequest(BaseModel):
    """Lưu toàn văn một flow (nodes/edges/meta). Slug lấy từ URL."""

    flow_type: str | None = None
    type: str | None = None
    kind: str | None = None
    capability: str | None = None
    enabled: bool | None = None
    keep_context: bool | None = None
    model: dict | None = None
    account: dict | None = None
    meta: dict | None = None
    nodes: list[dict] | None = None
    edges: list[dict] | None = None

    model_config = {"extra": "allow"}


class FlowTestRequest(BaseModel):
    """Chạy thử một flow đã lưu (preflight từng node + run thật)."""

    headed: bool = False
    prompt: str | None = None
    n: int = 1


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
    # Flow đem ra thử: select_model | text | image | video.
    flow: str = "text"
    # Prompt riêng cho lượt thử; để trống thì dùng mặc định theo flow.
    test_prompt: str | None = None


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


class ComboMemberSpec(BaseModel):
    model_id: str
    weight: int = 1
    priority: int = 0


class ComboCreateRequest(BaseModel):
    slug: str
    display_name: str | None = None
    strategy: str = "round_robin"
    description: str | None = None
    enabled: bool = True
    members: list[ComboMemberSpec]


class ComboUpdateRequest(BaseModel):
    display_name: str | None = None
    strategy: str | None = None
    description: str | None = None
    enabled: bool | None = None
    members: list[ComboMemberSpec] | None = None


class OpenAIModelSpec(BaseModel):
    id: str
    capability: str | None = "chat"


class OpenAIProviderCreateRequest(BaseModel):
    slug: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    models: list[OpenAIModelSpec]
    stream: bool = True


class OpenAIProviderUpdateRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    models: list[OpenAIModelSpec] | None = None
    stream: bool | None = None
