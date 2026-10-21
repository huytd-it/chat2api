# Website workspace UI — verification

## Shipped surface

- Root directory for ten websites, including MiniMax Agent's unconfigured state.
- Website rail, scoped workspace route, top account/model controls, optional
  project/Thinking/image tools, history/message area and context inspector.
- Secondary administration preserves global history, batch workbench, profiles,
  combo, providers, logs and settings. Advanced legacy engine editor is still
  reachable while backend migration is pending.
- API: read-only `GET /admin/websites`; optional `site` scope on
  `GET /admin/sessions`; persisted context metadata in session detail.
- Public chat/image contracts remain unchanged. Durable tracing headers are
  exposed by CORS for browser clients.
- Directory waits for sidecar health before its first account read, avoiding a
  stale connection-refused warning on packaged desktop startup.

## Automated checks

```powershell
npm --prefix desktop run check
npm --prefix desktop run build
.venv/Scripts/python.exe -m pytest tests/unit tests/integration/test_automation_durable.py tests/integration/test_sessions_endpoints.py -q
```

Results in this implementation: Svelte check 0 errors/0 warnings, Vite and Tauri
release builds succeeded; selected Python suite **438 passed**. This is not a
claim that the entire repository/browser integration suite passed.

The workspace endpoint tests cover filtering before LIMIT, database-only aliases,
exact slug boundaries, underlying website classification for combo recordings,
read-only catalog, unconfigured MiniMax and persisted context metadata. Existing
session and durable API regression tests remain included.

## Browser checks

Read-only smoke/visual script (a local backend and frontend must be running):

```powershell
$env:UI_BASE_URL='http://127.0.0.1:5199'
$env:UI_API_URL='http://127.0.0.1:8877'
$env:CHAT2API_TEST_KEY='<local test key>'
$env:CHAT2API_BROWSER_EXECUTABLE='<installed supported Chromium executable>'
node desktop/scripts/check-website-ui.mjs
```

The script opens a fresh browser context and reads real catalog/history/target
APIs. It does not submit prompts, create images, open website profile browsers or
delete anything. Checks: directory navigation, scoped model/history queries,
image studio visibility, capability-specific controls, MiniMax no-send state,
dark theme, no horizontal overflow and a visible narrow-window composer.

Screenshots were captured at desktop 1440×1000 and mobile 390×844 in two bounded
inspection rounds. Files stay under the approved local temporary directory:
`%LOCALAPPDATA%/Temp/opencode/website-ui-final/`.

Behavioral script with fully intercepted API fixtures:

```powershell
node desktop/scripts/test-workspace-behavior.mjs
```

It never reaches a real provider. It checks one new user message per durable
request, legacy recording isolation, continuing the same durable session,
unique request IDs, model change opening a new session, unresolved errors not
  resending automatically, and keyboard containment/Escape for the narrow context
  drawer. These are client behavior tests, not website certification.

The actual native EXE was also launched and captured successfully after replacing
the running build. Its final capture, with account counts loaded, is
`%LOCALAPPDATA%/Temp/opencode/website-ui-native-final.png`.

The mechanical Impeccable detector returned `[]` for the changed UI. The emitted
direction contract is retained in the production JavaScript build.

## Finish assessment

- Intent/scope: the shipped root and per-site navigation replace the old entry
  surface; this is actual app UI, not the earlier interactive mockup.
- Craft: cool slate/cobalt, restrained typography, flat hierarchy, readable target
  controls and context inspector match the approved operator-desk direction.
- Functional safety: UI does not advertise MiniMax execution, does not silently
  merge legacy/durable context, scopes history at the server and deletes explicit
  visible IDs only. No provider behavior was newly certified here.
- Responsive/a11y: desktop and narrow screenshots checked; Sheet primitives used
  for the new narrow inspector; hidden history controls removed from tab order.
- Verdict: UI ready with backend migration explicitly pending. Independent
  finish-review delegation was attempted twice and both attempts failed with
  provider HTTP 502, so the assessment above is in-thread, not an independent
  review. Do not label it as independently approved.

## Remaining backend work

Runtime cutover, all website drivers, custom recipe migration and removal of the
legacy engine are separate unfinished steps in the saved migration plan. The
workspace Context panel makes the current legacy runtime visible. A website's
listed model count or configured account count does not prove active login.
