# chat2api

Biến web chat AI bất kỳ thành API OpenAI-compatible. Thay việc copy/paste thủ công.

## Cài đặt

    python 3.11+
    pip install -e ".[dev]"
    playwright install chromium

## Chạy

    python -m chat2api serve --port 8100

## Desktop app (Windows)

Desktop app cần thêm Node.js, Rust + MSVC C++ build tools và WebView2. Script
dưới đây kiểm tra từng thứ, chỉ cài cái nào còn thiếu, rồi chạy `npm run tauri
dev` — chạy lại bao nhiêu lần cũng được:

    powershell -ExecutionPolicy Bypass -File .\desktop\scripts\setup-and-run.ps1

- `-NoRun`: chỉ cài đặt, không mở app.
- `-Port <số>`: ghim cổng backend (mặc định: hỏi, bỏ trống = tự chọn cổng rảnh).
  Windows giữ riêng vài dải cổng TCP mà bind vào là hỏng im lặng — **8100 và
  8200 nằm trong dải đó trên nhiều máy** — nên cổng nằm trong dải bị loại sẽ bị
  từ chối và script quay về tự chọn. Xem dải của máy bạn bằng
  `netsh interface ipv4 show excludedportrange protocol=tcp`.

Vài bước cài máy-rộng (MSVC Build Tools, WebView2, Python) đi qua winget và có
thể cần PowerShell chạy Administrator.

## Dùng như API chuẩn OpenAI

    POST /v1/chat/completions  {model, messages, stream}
    GET  /v1/models

Model id: `<provider>/<model>`, ví dụ `gemini/gemini-flash`, `qwen/qwen-max`.

### Request đi tới Account/Profile nào

Với recipe chạy bằng browser, server tự chọn một account (và profile Chromium
của nó) cho **từng** request rồi nói ra ngay trong header response — không cần
client gửi gì thêm:

    X-Chat2api-Session-Id        phiên đã ghi request này
    X-Chat2api-Account-Id        id account trong kho
    X-Chat2api-Account-Label     nhãn account, vd "main"
    X-Chat2api-Profile-Name      profile Chromium đã chạy
    X-Chat2api-Target            "profile/host/account" gộp sẵn một dòng
    X-Chat2api-Headed            request này có mở cửa sổ nhìn thấy được không
    X-Chat2api-Conversation-Url  link hội thoại thật trên site (chỉ ở chế độ non-stream)

Header có ngay từ byte đầu, kể cả khi `stream: true` và chưa có delta nào.
Cùng thông tin đó được lưu vào `request_log` và `session`, nên trang Sessions
hiện được "→ profile · host · account" dưới từng message và có nút **Xem trực
tiếp** mở lại hội thoại trong đúng profile đã tạo ra nó.

Muốn ghim một request vào đúng một account thì gửi
`X-Chat2api-Account-Id: <id>` — chỉ định tường minh luôn thắng mọi chiến lược.

### Nhiều request cùng lúc

Hai request đến cùng lúc được chia sang **hai account/profile khác nhau**, và
mỗi cái là một session riêng. Bốn khoá ở nhóm **API** của trang Settings điều
khiển việc này:

| Khoá | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `API_ACCOUNT_STRATEGY` | `least_busy` | `least_busy` chọn account rảnh nhất; `round_robin` xoay vòng đều; `sticky_session` ghim một session vào một account; `off` giữ cách cũ (storage_state, request không gắn profile). |
| `API_MAX_CONCURRENT_PER_ACCOUNT` | `1` | Số request chạy song song trên **một** account — mỗi slot là một tab riêng trong cùng profile. Vượt thì xếp hàng. |
| `API_MAX_CONCURRENT_REQUESTS` | `0` | Trần request chat song song toàn server (0 = không giới hạn). Vượt trần thì chờ, không bị từ chối. |
| `API_SESSION_MODE` | `per_request` | `per_request`: request không kèm `X-Chat2api-Session-Id` là một session riêng. `client_window`: gom theo client + model trong cửa sổ 30 phút. |
| `API_HEADED` | `always` | `always`: mọi request API mở cửa sổ Chromium nhìn thấy được. `never`: luôn chạy ẩn. `auto`: theo ô "Chạy ẩn" của từng profile. |

Mặc định `always`: gửi một request qua API là thấy ngay cửa sổ Chromium chạy
recipe, đúng đường mà nút **Gửi** ở bàn test Sessions đang dùng — cũng là cách
duy nhất để biết recipe kẹt ở bước nào. Đây cũng là thứ cần cho site chặn
headless (Cloudflare, bot-detect). Chạy trên máy chủ không có màn hình thì đặt
`API_HEADED=never`; muốn quyết định theo từng profile thì đặt `auto` rồi dùng ô
"Chạy ẩn" ở tab Profiles. Client gửi `X-Chat2api-Headed: true|false` thì header
thắng cả cài đặt lẫn profile; không gửi header nghĩa là "tuỳ server".

Chỉ có bấy nhiêu account thì request thứ N+1 xếp hàng sau chúng — thêm account
cho domain đó (trang Browser profiles) là cách duy nhất để chạy song song hơn.

## Tích hợp sẵn (không cần agent)

- **Gemini**: dán cookie từ trình duyệt vào `recipes/secrets/gemini-cookies.txt`
  (JSON `{"cookie": "...", "sapisid": "..."}` hoặc chuỗi cookie thô).
- **Qwen / upstream OpenAI bất kỳ**: sửa `recipes/openai/qwen.yaml` (base_url + key env).

## Tích hợp web chat mới bằng agent

Đặt env:

    AGENT_LLM_BASE_URL=https://api.openai.com/v1   # hoặc Claude/Gemini/Ollama...
    AGENT_LLM_API_KEY=sk-...
    AGENT_LLM_MODEL=gpt-4o

Rồi bấm **Phân tích** ở trang **Integrations** của desktop app, hoặc:

    python -m chat2api integrate https://chat.example.com

Tick ô **"Hiện browser khi test (không headless)"** dưới ô URL để xem
Chromium thao tác trực tiếp trên trang web song song với app. Đây là cửa sổ
Chromium thật trên máy chạy server; nếu nó không hiện ra (remote desktop,
sandbox...) thì đọc nhật ký job thay vì trông vào cửa sổ.

> Bản trước có "live view" — ảnh màn hình tự refresh 700ms/lần. Đã bỏ: mỗi
> lần chụp làm cửa sổ Chromium chớp một cái, nhìn nhiều tab cùng lúc thì
> nháy liên tục. `GET /admin/watch/{id}/screenshot` cũng không còn.

Site cần đăng nhập: chạy `python -m chat2api login <slug>`, đăng nhập tay,
chạy lại integrate.

Site KHÔNG bắt buộc đăng nhập (chat được ngay ở chế độ ẩn danh) vẫn được
publish, nhưng chỉ cho dùng thử `ANON_TRIAL_LIMIT` lượt (mặc định 20) —
hết lượt thì `/v1/chat/completions` trả lỗi `trial_limit_exceeded` (403) cho
tới khi có tài khoản đăng nhập. Thêm tài khoản bất cứ lúc nào ở trang
**Integrations** — mở hàng của recipe rồi bấm **+ Thêm account** (hoặc
`python -m chat2api login <slug> --account <tên>`); Chrome sẽ mở để đăng nhập,
sau đó model dùng account đó thay vì giới hạn ẩn danh.

## Account dùng chung theo domain

Account thuộc về **domain**, không thuộc recipe. State đăng nhập nằm ở
`recipes/.accounts/<domain>/<tên>.json`, nên đăng nhập `chat.qwen.ai` một lần
là **mọi recipe trỏ vào chat.qwen.ai tự động dùng lại được** — kể cả recipe
tạo sau, và cả lúc Integrate đang thử recipe mới.

- Khai báo `login.accounts` trong recipe.yaml vẫn chạy và **thắng khi trùng
  tên**, để recipe ghim được file state riêng nếu cần.
- Account kiểu cũ (`recipes/<slug>/auth/*.json`) được **chép** vào kho chung
  một lần lúc khởi động; file gốc giữ nguyên.
- Quản lý ở trang **Integrations**: account nằm ngay trong hàng recipe (gom
  theo domain của recipe) — thêm, đăng nhập lại khi hết hạn, xóa.
- Không biết domain? Để trống ô Domain trong dialog: browser mở trang trắng,
  bạn tự vào site và đăng nhập, server đọc cookie phiên để suy ra domain và tạo
  mới nếu chưa có. Domain khác còn đăng nhập trong cùng phiên được gợi ý luôn.

## Các trang trong app

| Trang | Dùng để |
|---|---|
| `/` Tổng quan | Trạng thái server, cảnh báo recipe hỏng / domain chưa có account |
| `/sessions` | Chat + xem lại mọi hội thoại: pretty / markdown / HTML gốc / JSON, tìm toàn văn, fork, xuất file |
| `/integrations` | Ba panel: thêm site bằng agent · site đã tích hợp (recipe + account) · profile trình duyệt |
| `/logs` | Log hoạt động server + output tiến trình nền |
| `/settings` | Sửa delay/timeout/engine... ghi thẳng vào `.env` |

## Profile trình duyệt (tuỳ chọn)

Mặc định mỗi recipe chạy trong một browser context riêng, khôi phục từ
`storage_state` (chỉ cookie + localStorage). Đặt `BROWSER_PROFILE_MODE=profile`
để chuyển sang Chromium profile thật:

```
BROWSER_PROFILE_MODE=profile   # storage_state (mặc định) | profile
POOL_MAX_PROFILES=6            # số tiến trình Chromium giữ mở
PROFILE_MAX_TABS=8             # tab tối đa trong một profile
```

Hai trần này chỉ dọn profile/tab **đang rảnh**: request đang chạy không bao giờ
bị đóng giữa chừng, kể cả khi bàn test Sessions mở nhiều profile hơn trần (lúc
đó pool tạm vượt trần và ghi cảnh báo vào log).

Một profile = một thư mục `data/profiles/<tên>/` giữ cookie + localStorage +
IndexedDB + service worker của **mọi** domain cùng lúc, nên:

- Một lần đăng nhập Google dùng được cho nhiều site trong cùng profile.
- Nhiều recipe chạy **song song**, mỗi recipe một tab, chung một tiến trình.
- Recipe tự chọn profile theo thứ tự: `recipe.profile_id` đã ghim → profile của
  account trên domain của recipe → profile mặc định.
- Account cũ (`recipes/.accounts/*.json`) được đổ vào profile ở lần mở đầu tiên
  rồi thôi; file JSON giữ nguyên làm bản sao lưu.

Một `user_data_dir` chỉ được một tiến trình Chromium mở, nên profile có khoá
pid. Khi bị tiến trình khác giữ — hoặc bất kỳ lỗi nào khác — request **vẫn chạy**
bằng đường `storage_state` cũ. Chế độ profile không áp dụng cho engine `cloak`
và cho request bật "hiện browser".

Panel **Profile trình duyệt** ở trang `/integrations` quản lý phần này: tạo,
sửa số tab / headless, đặt mặc định, mở cửa sổ để đăng nhập tay, **dò** xem
profile còn đăng nhập domain nào chưa khai báo, đóng, xóa. Tương đương
`GET/POST/PATCH/DELETE /admin/profiles` và `POST /admin/profiles/{id}/detect`.

## Lưu hội thoại

Mọi request qua `/v1/chat/completions` được ghi vào `session` + `message` +
`request_log`, kể cả request từ client API ngoài. Đúng hai transaction cho mỗi
request (mở và đóng) — không ghi từng SSE delta.

- Header `X-Chat2api-Session-Id` (tùy chọn) nối nhiều lượt vào cùng một phiên;
  server luôn trả lại header này để client biết mình vừa ghi vào đâu.
- Không gửi header thì được lưu dưới `kind='api'`, mỗi request một session
  (`API_SESSION_MODE=per_request`). Đặt `client_window` để quay lại cách gom
  theo model + hash của `Authorization` và `User-Agent` trong cửa sổ 30 phút.
- `request_log` ghi luôn `account_id`, `profile_id` và `conversation_url` của
  từng request, nên một session trải qua nhiều account vẫn truy được từng lượt.
- Reply lỗi / timeout / hết lượt / client ngắt giữa chừng đều được lưu kèm phần
  text đã nhận được, không mất trắng.
- Recipe khai báo `response.capture_html: true` thì lưu thêm outerHTML gốc của
  site, trang Sessions render nó trong `<iframe sandbox>` để xem bảng/công thức
  đúng như trên site. Mặc định tắt.

Kho rỗng (chưa mở được SQLite) chỉ làm mất phần lịch sử — API chat vẫn chạy.

## Duy trì browser & delay khi chạy recipe

Browser context **không bao giờ tự đóng**: trả lời xong cửa sổ vẫn còn nguyên,
mỗi recipe dùng lại đúng một tab cho mọi request (không mở tab mới, không đóng
tab cũ). Chỉ 3 cách tắt, đều do người dùng chủ động:

- tự đóng cửa sổ browser bằng tay (request sau tự mở lại);
- bấm **Tắt browser** ở bảng recipes (`POST /admin/recipes/<slug>/browser/close`);
- tắt server.

Vì tab được dùng lại, site nào khôi phục hội thoại cũ khi mở lại thì khai báo
`new_chat` để mỗi request bắt đầu một phiên chat mới:

```yaml
new_chat:
  selector: "button[aria-label='New chat']"   # bấm nút tạo chat mới sau khi load
  # url: https://example.com/chat/new         # hoặc mở thẳng URL chat mới
timing:
  ready_delay_ms: 2000    # chờ sau khi ô input hiện ra, để web thật sự sẵn sàng
  input_delay_ms: 600     # chờ trước khi đổ prompt vào ô input
  ready_timeout_ms: 20000 # hạn chờ ô input xuất hiện
keep_context: false       # tùy chọn: dựng context sạch mỗi request (chậm hơn)
```

Không khai báo `timing` thì lấy mặc định từ env `RECIPE_READY_DELAY_MS` (1200),
`RECIPE_INPUT_DELAY_MS` (400), `RECIPE_READY_TIMEOUT_MS` (20000).

## Fallback khi recipe hỏng

    ENABLE_AGENT_FALLBACK=true
    # recipe lỗi ≥ 3 lần → agent điều khiển browser trực tiếp, vẫn trả lời được

## Env chính

CHAT2API_KEYS · RECIPES_DIR · CHAT2API_DATA_DIR (mặc định `./data`) · AGENT_LLM_* ·
ENABLE_AGENT_FALLBACK · POOL_MAX_CONTEXTS · BROWSER_ENGINE=playwright|cloak ·
BROWSER_PROFILE_MODE=storage_state|profile · POOL_MAX_PROFILES · PROFILE_MAX_TABS ·
RECIPE_TIMEOUT_MS · INTEGRATE_MAX_ROUNDS ·
ANON_TRIAL_LIMIT (0 = không giới hạn dùng thử ẩn danh) ·
RECIPE_READY_DELAY_MS · RECIPE_INPUT_DELAY_MS · RECIPE_READY_TIMEOUT_MS ·
API_ACCOUNT_STRATEGY · API_MAX_CONCURRENT_PER_ACCOUNT ·
API_MAX_CONCURRENT_REQUESTS · API_SESSION_MODE · API_HEADED

Các khoá trên giờ lưu trong bảng `setting` của kho SQLite và sửa được từ trang
Settings. Đặt trong môi trường thật hay `.env` vẫn **thắng** hàng trong kho —
đó là đường bootstrap cho CI và cho container; trang Settings hiện rõ khoá nào
đang bị `.env` ghim.

## API key

Trang Settings tạo và thu hồi được từng key một (nhãn + scope `chat` cho
`/v1/*`, `admin` cho `/admin/*`). Kho chỉ giữ sha256 của key, nên key thô chỉ
đọc được đúng một lần lúc tạo — chép ngay, mất là phải tạo cái khác.
`request_log` ghi lại key nào đã gọi request nào.

`CHAT2API_KEYS` (CSV) vẫn dùng được song song làm key bootstrap cho CI và cho
lần chạy đầu khi chưa có kho; key kiểu này không có hàng trong DB nên không
liệt kê và không thu hồi từ UI được. Không đặt key ở cả hai nơi ⇒ server mở.

## Kho dữ liệu

`CHAT2API_DATA_DIR` (mặc định `./data`) chứa `chat2api.db` — kho SQLite của log,
job và (từ pha sau) session/recipe/account. Thư mục chỉ được tạo khi server chạy,
và nằm trong `.gitignore`. DB hỏng hay không mở được thì server vẫn chat bình
thường, chỉ mất phần lưu lịch sử.

`GET /admin/logs` đọc ring buffer trong RAM (poll theo cursor);
`GET /admin/logs/history?level=&source=&q=&before=` đọc từ DB nên thấy được cả
log trước lần restart gần nhất.

Thiết kế đầy đủ cho các pha còn lại: [`docs/design-v2.md`](docs/design-v2.md).
