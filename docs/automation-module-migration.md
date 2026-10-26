# Migration sang module website — baseline và checkpoint

## Trạng thái

### Thống nhất lịch sử/session, website chỉ cấu hình — 2026-10-22

Theo yêu cầu mới, không còn mount SessionWorkspace ở route website. Icon mở
`/websites/<id>` để chỉnh cấu hình automation hiện tại; đường `/settings` cũ
chuyển về đây. Hội thoại, model/account, Thinking/project, tác vụ ảnh và lịch sử
tập trung ở `/sessions`. Bỏ scope website ngầm khỏi request lịch sử và account
của UI; API filter tường minh cho client ngoài vẫn giữ. Liên kết “Chat với...”
chỉ chọn sẵn model, không lọc lịch sử hay trộn context của các session khác nhau.
Các component toolbar/context/image đã chuyển vào nhóm sessions, không giữ
bản workspace riêng chỉ để ẩn nó.

Svelte check 0 lỗi/0 warning; release build đạt và sidecar mới health OK.
Smoke UI read-only + behavioral fixture đã kiểm tra lịch sử chung, cấu hình
không có composer, tạo ảnh dùng chung và đổi provider không mang history cũ.
Chi tiết, giới hạn QA và lệnh kiểm tra ở `shared-sessions-ui.md`.

### Tách broker và cổng journal trước khi xóa engine — 2026-10-21

Người dùng xác nhận **chuyển hết rồi mới xóa**, giữ chức năng và dữ liệu. Đã
chuyển implementation chọn account/slot, reservation/release, khóa tab, mở profile,
storage-state rotation và các lỗi quota sang `automation/account_broker.py`,
`account_source.py`, `account_errors.py`; các bản triển khai trùng trong
BrowserRecipe đã xóa. Provider cũ đang gọi primitive chung, không có module mới
nào bọc BrowserRecipe. Persistence lượt ẩn danh được đưa qua callback ở biên cũ.

API project/catalog dùng page lease chung. Runtime có `execute_assigned_turn`
và `execute_journaled_turn`, giữ đúng account đã chọn, giới hạn cả thời gian chờ
tab, lưu metadata theo request và dùng journal hiện có (không tạo journal thứ hai).
Cổng submit journal nay kiểm tra operation prepared/busy marker; cổng mới bind
account + đánh dấu submitted trong một transaction, không cho request thua race
ghi đè account của request đã submit. Lỗi sau boundary vẫn uncertain, không resend.

**Chưa cutover hoặc xóa BrowserRecipe/FlowRunner.** Driver/module thực thi chat,
upload/media/discovery, dữ liệu custom và routing chưa chuyển đủ. Preflight mới
vẫn báo 3 nguồn SQLite-only `chat`, `gemini-2`, `grok` cần mapping riêng và
`safe_to_remove_legacy=false`. Không xóa nguồn YAML/SQLite/profile/history ở đợt này.

Kiểm chứng: **555 passed** (unit + nhóm HTTP durable/session/chat/account/target/
workspace/flow-contract và persisted-state). Test broker/runtime dùng DB thật
trong thư mục tạm và fake browser/driver, không phải xác minh website live.

### Icon launcher + domain-first/agent CLI — 2026-10-21

Theo điều chỉnh mới, sidebar không bung từng domain; `/` là trang icon Web chats.
Thêm domain lưu vào bảng `website` (migration 0010), không tạo model/driver giả.
CLI `website add/list/brief` và trang Agent CLI giúp giao yêu cầu tùy chỉnh cho
coding agent ngoài app. Brief không chạy LLM hay browser. Chi tiết ở
`website-agent-cli.md`. Đây không thay thế phần runtime migration còn thiếu.

### Chuyển giao tính năng UI/API quản trị — 2026-10-21

Các trang cũ `/recipes`, `/integrations`, `/providers` đã gỡ khỏi source.
Công cụ edit/preview/trial/record/reanalyze/reload/rename/browser-close/quota
được chuyển vào cấu hình workspace website. Direct API được tách riêng.
Admin client + route chuyển sang automations/automation-jobs/automation-targets;
route cũ không còn trong OpenAPI. `/v1/*` giữ nguyên. Nguồn SQLite chưa có
provider được hiện rõ để xem, không tự kích hoạt hay ghi đè.

Đây **không phải** hoàn tất thay engine: BrowserRecipe/flow runtime vẫn còn.
Xem `workspace-admin-migration.md` cho vị trí tính năng, mapping API và hạn chế.

### Checkpoint UI production — 2026-10-21

Đã triển khai UI mới vào app thật: danh sách website ở `/`, 10 workspace theo
website, toolbar account/model, lịch sử lọc phía server và context inspector.
Quản trị toàn hệ thống là nhóm phụ; Recipe editor chỉ còn đường nâng cao trong
giai đoạn chưa cutover. MiniMax chưa có driver nên không có composer giả.

EXE release `chat2api-desktop.exe` đã được build, so hash với target release và
mở lại. Đã xác minh cửa sổ native hiển thị directory mới và account thực; sửa
race khởi động để directory chờ sidecar health trước khi nạp account.

Kiểm chứng UI: Svelte check 0 lỗi/0 warning, Vite + Tauri release build đạt,
selected Python suite 438 passed, browser smoke desktop/narrow/light/dark và
behavioral fixtures (context isolation, continuation, no automatic resend,
drawer keyboard focus/Escape) đạt. Không gửi prompt thật lên provider trong QA
UI. Chi tiết tại `automation-ui-verification.md`; thiết kế hiện tại ở
`../DESIGN.md`. Runtime migration vẫn chưa hoàn tất.

Đang triển khai theo kế hoạch đã duyệt. **Chưa cutover router, chưa gỡ engine
recipe/flow, chưa coi 9 website đã được migrate.** Các manifest mới mô tả ranh
giới module và public model ID, không phải chứng nhận tài khoản hoạt động.

## Baseline 2026-10-20

### Bổ sung phạm vi: MiniMax Agent

Người dùng yêu cầu thêm `https://agent.minimax.io/` sau checkpoint nền.
Danh sách đích hiện có **10 module**, thêm package `sites/minimax/`,
module ID `minimax`, slug nội bộ `minimax-agent`. Đây là website Agent,
không phải cấu hình provider MiniMax API trực tiếp.

Chưa probe đăng nhập, model, task lifecycle, file/artifact, project, Thinking,
resume hay quota. Manifest không có model/operation để tránh xuất bản khả năng
giả. Cần khảo sát cả tác vụ dài và artifact của website, không mặc định mọi
tương tác là chat completion. Không tạo recipe YAML mới cho MiniMax.

Các số liệu baseline 9 recipe bên dưới là snapshot trước khi bổ sung website,
không phải danh sách module đích hiện tại.

- Checkout sạch trước khi bắt đầu đợt này. Không tạo worktree.
- `RECIPES_DIR=./recipes`, `CHAT2API_DATA_DIR=./data`; không có `flow.json`
  trong thư mục flows hiện tại. Công cụ preflight vẫn kiểm kê flows ở cài đặt khác.
- 9 recipe browser trong repo, 12 recipe browser trong SQLite. Thêm 1 provider
  `gemini_native` trong SQLite được giữ ngoài migration browser này.
- 3 recipe browser chỉ có trong SQLite: `chat`, `gemini-2`, `grok`. Chúng khác
  cấu hình mặc định, không được tự gộp/xóa vì cùng hostname.
- 9 bản recipe chuẩn trong SQLite khớp fingerprint bản file lúc kiểm kê.
- Profile/account/session/project/journal không bị sửa bởi preflight. Database
  đang được ứng dụng khác sử dụng, nên số lượng session có thể tăng giữa hai lần
  đọc; không lấy số lượng bằng nhau làm bằng chứng an toàn migration.

### Bảng tương đương cần giữ

| Module | Slug/model local hiện có | Hoàn tất phản hồi cũ | Nội dung cần giữ/kiểm chứng |
|---|---|---|---|
| Qwen | `qwen-web`: `qwen3.7-plus`, `qwen3.8-max`, `image`, `qwen-web` | Stop biến mất + quiet | Model menu, Thinking/Fast, project/file/instructions, resume, ảnh thực, quota |
| ChatGPT | `chatgpt-web`: `default`, `image` | Stop biến mất + quiet | Think toggle, project/Sources, resume, ảnh blob, challenge/login |
| DeepSeek | `deepseek-web`: `default` | Copy sau message | New chat, reply freshness, copy fallback, resume cần probe |
| Gemini | `gemini-web`: `gemini-web` | Copy sau message | Markdown, delay input, new chat URL, resume cần probe |
| Grok | `grok-web`: `default` | Copy trong message | New chat, quota pattern/cooldown, resume cần probe |
| Kimi | `kimi`: `default` | Copy trong message | Markdown/HTML, input delay, quota, new chat/resume cần probe |
| Dola | `dola`: `dola-pro` | Copy ở page | Rich text input, timeout 300s, new chat/resume cần probe |
| Tencent | `tencent`: `default` | Copy sau message | Click submit, new chat/resume cần probe |
| Z.ai | `chat-z-ai`: `default` | Copy sau message | Model picker, new chat/resume cần probe |

Public ID luôn là `<slug>/<model local>`. Model discovery theo account có thể
thêm ID ngoài manifest; runtime hoàn chỉnh phải hỗ trợ catalog này trước cutover.
Không được biến alias thành ID mới mà bỏ client cũ.

### Các nguồn tùy chỉnh là migration blocker

| Nguồn DB | Website tương ứng | Public ID | Khác biệt cấu trúc so với mặc định |
|---|---|---|---|
| `chat` | Qwen | `chat/qwen-web` | Login, model, prompt, response; thiếu flow ảnh/model mới |
| `gemini-2` | Gemini | `gemini-2/gemini-web` | Login và response format/done signal |
| `grok` | Grok | `grok/default` | Flow text, model, prompt, response; cấu hình new chat khác |

Phải lưu cấu hình gốc trong backup migration và quyết định mapping riêng. Chỉ
thêm alias không đủ nếu làm mất hành vi selector, quota hoặc định dạng output.

## Dependency/cutover checklist

- Router hiện nạp recipe YAML, provider API trực tiếp/native và legacy flow có
  branch/eval. `BrowserRecipe` đang sở hữu cả tài khoản, profile lease, polling,
  upload/media lẫn DSL action. Không thể chỉ đổi tên class.
- `main.py`, durable service, projects, catalog, combo, trials, CLI và integration
  authoring còn dựa vào loại/thuộc tính BrowserRecipe. Phải đổi cùng hợp đồng
  provider hoặc port mới trước khi xóa class.
- Luồng authoring/analyzer/recorder/trial hiện tạo và test recipe. Trước gỡ cần
  đầu ra thay thế và tài liệu quản trị, không để nút tạo website ghi YAML vô dụng.
- UI đang có Sessions, Recipes, Providers, Combos, Profiles, Logs, Settings và
  Integrations. Tìm kiếm, archive/pin/tags, export/fork/inspect, batch targets,
  rotation, headed mode, profile open/close và quản trị API key phải có chỗ mới.
- Qwen/ChatGPT project, Thinking và ảnh đã từng test thật ở đợt trước; **không**
  dùng bằng chứng đó để chứng nhận driver mới chưa chạy.

## Code mới trong checkpoint này

- `automation/contracts.py`: manifest/model bất biến, khả năng có evidence riêng
  theo account, turn/reply và protocol thao tác site.
- `automation/sites/<site>/`: 9 manifest riêng, giữ ID hiện có. Chưa có driver
  production; không đánh dấu đã migrate.
- Các controls project/Thinking của Qwen và ChatGPT đã chuyển sang
  `sites/qwen/controls.py` và `sites/chatgpt/controls.py`. Factory import cũ tạm
  re-export để caller production không gãy trong lúc chuyển runtime. Đây là
  chuyển implementation thật, không phải thêm một bản sao controls.
- `automation/registry.py`: catalog explicit, không quét YAML hay nạp plugin ngầm.
- `automation/runtime.py`: thực thi một turn qua driver được cấp page; không launch
  browser, không chọn account, không retry. Trước submit bắt buộc callback journal
  thành công. Mọi lỗi/cancel sau boundary là uncertain.
- `automation/inventory.py` và `scripts/automation_inventory.py`: preflight chỉ đọc
  file + SQLite URI read-only; báo khác biệt, custom sources, flows và parse errors.
  Không in credential/cookie path/prompt/file payload; không tự chạy migration.
- Runtime mới chưa nối vào durable service/router: broker account, upload/media,
  discovery model, driver thật và dữ liệu migration vẫn còn phải thực hiện.

Chạy preflight với đường dẫn explicit của cài đặt:

```powershell
.venv/Scripts/python.exe scripts/automation_inventory.py --recipes-dir recipes --data-dir data
```

Có thể thêm `--flows-dir` khi cài đặt dùng thư mục flows riêng. Công cụ này không
đọc `.env` hoặc khởi tạo Config/Store để tránh thay đổi môi trường/schema. Report
luôn trả `safe_to_remove_legacy=false` cho đến khi có cơ chế chứng nhận cutover;
manifest hoặc test mock không được tự cho phép xóa source.

## Kiểm thử checkpoint

- 44 test mới cho registry/contracts, URL boundary, evidence, lifecycle submit,
  lỗi journal/cancel/deadline, controls Think đã chuyển, kiến trúc không import
  engine cũ và inventory không sửa database/không lộ payload.
- Toàn bộ unit: **415 passed**; cộng durable HTTP: **419 passed**.
- Durable HTTP + journal cũ: **9 passed**.
- Full suite chưa hoàn tất: lần đầu vượt 300s sau khi có failure; lần chạy lại
  vượt 180s. Không tuyên bố full suite xanh.
- Đã tái hiện failure có trước trong
  `test_chat_endpoints.py::test_test_recipe_edit_runs_the_merged_draft`:
  mock `fake_trial` chỉ nhận tối đa 6 đối số, route truyền 7. Đợt này chưa sửa
  `main.py` hay test đó. Các test browser bị treo chưa được đối soát hết.
- Chưa chạy website thật bằng runtime mới; chưa chỉnh UI production. Bố cục
  workspace đã được người dùng duyệt, lưu tại `automation-workspace-design.md`.
- `ruff` không có trong venv nên chưa chạy lint; `git diff --check` không có
  lỗi whitespace (chỉ cảnh báo LF/CRLF của Git).

## Tiếp theo

1. Tách broker account/profile và persistence port khỏi BrowserRecipe, nối journal
   hiện có qua callback thay vì tạo journal thứ hai.
2. Driver chat Qwen/ChatGPT thật với test DOM cục bộ, rồi các site còn lại;
   controls project/Thinking đã chuyển, upload/media/discovery vẫn cần chuyển.
3. Dựng UI theo bố cục workspace đã duyệt; module không hỗ trợ chức năng nào
   không được hiện tab/control gây hiểu nhầm.
4. Migration có backup/dry-run/version; giữ custom config và alias. Cutover và gỡ
   legacy chỉ khi dependency audit, dữ liệu và parity test đã hoàn tất.
