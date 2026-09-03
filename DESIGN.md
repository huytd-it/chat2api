---
name: chat2api console
description: Modern responsive developer tool for operating chat2api
stack:
  components: shadcn-svelte
  primitives: Bits UI
  styling: Tailwind CSS v4
  icons: phosphor-svelte
  theme: mode-watcher
  notifications: svelte-sonner
colors:
  primary: cobalt blue
  success: green
  warning: amber
  destructive: red
  neutral: zinc
radius:
  controls: 8px
  containers: 10px
---

# Design System: chat2api console

## Design intent

chat2api is a desktop developer tool for technical operators. The interface is compact, calm, responsive, and explicit about system state. It does not imitate hardware, terminals, CRT displays, or a marketing dashboard.

The UI supports light, dark, and system themes. Neutral zinc surfaces carry hierarchy; cobalt blue identifies interactive intent. Green, amber, and red are reserved for healthy/success, running/warning, and error/destructive semantics.

## Foundation

- **Components:** editable shadcn-svelte components in `desktop/src/lib/components/ui`.
- **Accessibility primitives:** Bits UI for keyboard behavior, focus management, dialogs, menus, tabs, sheets, and tooltips.
- **Styling:** Tailwind CSS v4 through `@tailwindcss/vite`.
- **Icons:** Phosphor Svelte throughout product code. Do not mix icon families in application UI.
- **Theme:** mode-watcher; every component must work in light and dark mode.
- **Toast:** Sonner with semantic variants.

## Color roles

Tokens are defined in `desktop/src/app.css` using OKLCH values.

- `background`: application canvas.
- `card` / `popover`: primary elevated surfaces.
- `foreground`: primary text.
- `muted` / `muted-foreground`: quiet surfaces and secondary text.
- `primary`: cobalt blue for selected navigation, primary actions, links, focus, and active controls.
- `success`: healthy and completed only.
- `warning`: running, trial, degraded, and restart-required only.
- `destructive`: errors, deletion, revoke, and irreversible actions.
- `border`, `input`, `ring`: structural and focus tokens.

Do not use status colors decoratively. Do not add glow, scanlines, graticules, rivets, faux metal, or gradients intended to mimic hardware.

## Typography

- UI: system sans (`Segoe UI` and platform fallbacks), 14px base.
- Headings: sentence case, 600 weight, restrained scale.
- Mono: identifiers, model names, domains, API key prefixes, timestamps, metrics, JSON, and logs only.
- Avoid condensed uppercase labels and oversized route headings.

## Shape and elevation

- Controls: approximately 8px radius.
- Containers: 10–12px radius.
- Surfaces are flat with light borders.
- Shadows are limited to overlays, menus, sheets, and transient floating layers.

## Application shell

- Desktop: collapsible sidebar with icon and label for Overview, Sessions, Flows, Providers, Combos, Profiles, Logs, and Settings. The legacy Recipes UI is hidden — `/recipes` redirects to `/flows`.
- Narrow windows: sidebar becomes a focus-managed Sheet.
- Header: route context, connection details, sidebar trigger, and theme control.
- Overview and Settings use constrained content widths.
- Sessions, Flows canvas, and Logs use the full workspace.

## Screen contracts

### Overview

Lead with system health, then supporting metrics. Issues provide a related action. Browser runtime and integrated providers include explicit empty/loading/error states.

### Sessions

The conversation is primary. Session list is secondary; inspector and target workbench are tertiary panes. On narrow windows secondary panes become overlays. The composer remains visible. Keep all search, archive, pin, tags, fork, export, inspect, batch target, and rotation behaviors.

### Flows

Flows replace the Recipe UI. Layout: list (`/flows`) + full-screen canvas (`/flows/<slug>`) built on Svelte Flow — pan/zoom/minimap, drag nodes, connect handles, click a node to edit params in the right panel, click an edge to delete it, save, duplicate, enable/disable, and run trial (preflight per node + real run + postflight). Node `condition` exposes `true`/`false` source handles for branching.

### Providers

Browser providers are read-only here: Reload, open the matching Flow (`/flows/<slug>` for edits, duplication, trials), and close browsers. All selector editing moved to Flows. The legacy Recipe YAML backend still runs underneath but has no UI.

### Integrations

Order follows the workflow:

1. Add integration.
2. Observe analyzer progress and log.
3. Manage integrated sites/accounts.
4. Manage browser profiles.

The Recipe creation tab is removed — converted flows appear under Flows. All destructive actions use Alert Dialog; account creation uses Dialog.

### Logs

Use a modern mono log surface without scanlines. Preserve 1.5-second polling. The toolbar controls pause, copy, clear, and level filtering. Clearing populated logs requires confirmation.

### Settings

Group client authentication, runtime settings, browser profiles, API keys, and restart-required values. Secret fields have reveal controls. A new API key has an assertive one-time visibility warning. Revoke and purge use Alert Dialog.

## Interaction and accessibility

Every route provides appropriate loading skeletons, actionable empty states, inline errors with retry, disabled/busy states, success feedback, and destructive confirmation.

- Keyboard navigation and visible focus are mandatory.
- Live connection, streams, integration jobs, and logs use `aria-live` appropriately.
- Respect `prefers-reduced-motion`.
- Maintain WCAG AA contrast in both themes.
- Icon-only controls require accessible names and tooltips when their meaning is not obvious.

## Flows — canvas kiểu n8n thay UI Recipe

- Mỗi flow con là một file `data/flows/<slug>/flow.json` (`{slug, kind, flow_type, capability, enabled, model, account, meta, nodes[], edges[]}`) — 1 flow = 1 model, tên flow đặt như tên model, cho phép duplicate nhanh. Theo `CHAT2API_DATA_DIR` (`config.py:flows_dir`, ghi đè bằng `FLOWS_DIR`).
- Validate bằng `flow_store.validate_flow` (đúng 1 node `start`, ≥1 node `output`, kiểu node thuộc catalog, edges trỏ tới node có thật). Ghi atomic (temp + rename).
- Auto-convert lúc startup: `flow_converter.migrate_all` tách mỗi `recipes/*/recipe.yaml` thành N flow con, idempotent (chỉ tạo mới, không đè flow đã sửa, không ghi ngược về recipe).
- Thực thi: `flow_compiler.compile_flow` dựng dict recipe chuẩn → `FlowRunner` (subclass `BrowserRecipe`) tái dùng toàn bộ helpers browser (account/assign, pool/page, done_signal, media, copy). `flow_executor` đi từng node theo edges (DAG + rẽ nhánh `condition` qua `sourceHandle` true/false), fail dừng tại node đó.
- Tương thích chat: `router.py:_flow_loaders` nạp flows **sau** recipes nên flow cùng slug **ghi đè** recipe cũ — model id giữ nguyên, Combos/Test-targets/Sessions/Domains không gãy. API: `GET /admin/flows`, `GET/PUT/DELETE /admin/flows/{slug}`, `POST .../duplicate`, `POST .../reload`, `POST .../test` (preflight từng node + run thật + postflight, theo triết lý 3 chặng của `trial.py`).
- UI Recipe cũ (sidebar link, tab tạo, `RecipeCreatePanel/EditorSheet/Fields`, sửa/xóa/đổi tên/phân tích/ghi thao tác trong Providers) đã ẩn — backend recipe vẫn chạy ngầm.

## Trace — Ghi thao tác giàu (Phase 1-5)

Mục tiêu: selector mỏng ban đầu (1c) được bổ sung thành trace giàu để sinh/sửa `recipe.yaml` bền, kể cả khi site đổi DOM.

### Kiến trúc

```
page JS --enriched RECORDER_JS--> __c2aRecord --> trace_sink --> job["trace"]
  --> trace_writer.py (atomic write) --> data/traces/<jobId>-<slug>.{json,md}
  --> analyzer vẫn dùng RAM như cũ  +  GET /admin/record/{id}/trace(.json/.md)  +  GET /admin/traces
  --> CLI đọc filesystem nếu cùng máy hoặc qua API nếu remote; desktop nút Tải trace
```

- `data/traces/<jobId>-<slug>.{json,md}` giữ **vĩnh viễn** (không TTL), theo `CHAT2API_DATA_DIR` (`config.py:traces_dir`).
- `.json`: `{metadata:{jobId,slug,url,profile,startedAt,finishedAt,flows}, events:[{kind,selector,selectors:{primary,parent,grandparent,cssPath,xpath},attributes:{id,class,data-testid,role,aria-*},bbox:{x,y,w,h},text:{innerText≤500,outerHTML≤2000},frame:{url,chain},shadow:{hostSelector,depth},snapshotDiff≤10000, value≤8000, flow, ts, url, tag, label}], snapshot?:string}`.
- `.md`: Metadata bảng + Tóm tắt theo flow + Events (bảng selectors/attrs/bbox + code `outerHTML` + `snapshotDiff`) + Snapshot cuối + Gợi ý recipe + banner PII. Do `recorder.py:format_trace_as_markdown` sinh.
- Persist trước `login_manager.complete()` và cả trên `cancel`/`record_timeout` để không mất trace khi người dùng huỷ. Ghi atomic (temp + rename).
- Tương thích ngược: event cũ chỉ có `selector:string` vẫn đọc được (`recorder.py:enrich_event` chuẩn hoá hai chiều `selector ↔ selectors.primary`, clamp sizes).

### Luồng JS → file

1. `chat2api/agents/dom.py` — các mảnh `XPATH_FN_JS/CSS_PATH_FN_JS/ATTRS_FN_JS/BBOX_FN_JS/FRAME_CHAIN_FN_JS` + `__c2aSel` legacy + `__c2aEnrich` gom đủ; `SNAPSHOT_JS` dùng `__c2aSel` legacy (không đổi contract).
2. `chat2api/agents/recorder.py` — `RECORDER_JS` gọi `__c2aEnrich`, push `selector` (giữ) + `selectors/attributes/bbox/text/frame/shadow/snapshotDiff`; `enrich_event`/`format_trace_as_markdown`/`_row` xử lý cả đời cũ.
3. `chat2api/agents/trace_writer.py` — `_traces_dir(cfg)` theo `CHAT2API_DATA_DIR`, `_atomic_write_*`, `write_trace()` ghi cả `.json` + `.md` (md qua `recorder.format_trace_as_markdown`).
4. `chat2api/jobs.py` — `_trace_metadata` + `_persist_trace` trước `complete()`; gọi cả trong `_finish_record_timeout` và `_cancel_job` (record); `_snapshot` expose `trace_path/trace_md_path`; `config.py:traces_dir` + `on_trace` gọi `enrich_event`.
5. `chat2api/main.py` — `GET /admin/record/{id}/trace(.json|.md)` (extension path là contract chính, `?format=` là alias), `GET /admin/traces` trả `{traces:[{name,size,mtime}],count}`.

### Skill

- Nguồn chính: `skills/trace-analyzer/SKILL.md` + `skills/trace-analyzer/references/recipe-schema.md`.
- Sync ra `.claude/skills/trace-analyzer/`, `.opencode/skills/trace-analyzer/`, `.codex/skills/trace-analyzer/` bằng `scripts/sync-skills.ps1` / `.sh`.
- Workflow skill: liệt kê trace (`GET /admin/traces` hoặc `ls data/traces/`), đọc `.md` (`GET .../trace.md`), phân tích `selectors/attrs/bbox/outerHTML/snapshotDiff` → đề xuất `recipe.yaml` (theo `references/recipe-schema.md`) → sửa → `python -m chat2api test` / `POST /admin/recipes/<slug>/reload`.

### Rủi ro & edge

- Perf: ~5 DOM query/click, <5ms, ~600KB json / ~1MB md cho 200 events.
- Canvas/WebComponents: fallback `cssPath + bbox`.
- Traces giữ vĩnh viễn nên cần dọn tay khi phình (chưa có retention).
- PII banner trong `.md`; không commit `data/traces/` (chỉ giữ `README.md`).
