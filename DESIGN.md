# Design system: chat2api website workspaces

## Product surface

The production UI is now website-first. `/` is the website directory;
`/websites/<site>` is a scoped workspace. Each workspace exposes only models,
accounts and history belonging to that website. MiniMax Agent is listed but
has no executable driver/model yet: its empty state explains this and does not
offer a composer or pretend that integration is complete.

This UI change is not backend runtime cutover. The current browser providers
still execute through the existing engine; the Context inspector says so.
Do not relabel a declared module capability as a verified account capability.

## Visual world

An operator desk, not a generic API playground or a decorative dashboard.
The user-approved direction is recorded in `docs/automation-workspace-design.md`.
Its production direction contract is emitted by `desktop/src/routes/+layout.svelte`
(seed `210f6e51`).

- Cool slate canvas and quiet white panels in light mode; deep slate in dark.
- Cobalt blue identifies selection, links, primary action and focus.
- Green, amber and red are semantic status only. Configured accounts are counted
  neutrally: existence of an account is not proof of login or readiness.
- Flat surfaces, subtle separators; no grid background, artificial terminal
  decoration, decorative gradients, glows or nested dashboard cards.
- 8px control radius, restrained 10–12px panel radius. Shadows belong to overlays.

## Foundation

- Svelte 5 + SvelteKit SPA, Tailwind v4.
- shadcn-svelte/Bits UI for accessible controls, dialogs, menus and sheets.
- Native labelled selects for the compact workspace account/model/Thinking row.
- Phosphor icons in product UI. ProviderIcon uses available provider marks and a
  neutral fallback; a generic fallback is not an invented brand logo.
- `mode-watcher` for light/dark/system and Sonner for transient feedback.
- Tokens: `desktop/src/app.css`. Light primary `oklch(0.5 0.17 260)`, dark primary
  `oklch(0.75 0.13 255)`. Components consume tokens, not literal theme colors.
- Font: Aptos/Segoe UI Variable/Segoe UI/system sans; base 14px. Monospace only for
  IDs, model values, timing and diagnostics. Headings are not condensed.

## Application shell

The collapsible website rail is primary: all websites, then the ten individual
workspaces. Administration is secondary: Profiles/account, API/integrations,
Combos, global history/API, system overview, logs and integration authoring.
Settings and actual backend status stay at the foot of the rail.

The header provides breadcrumbs, sidebar toggle, backend connection and theme.
The old Overview remains available at `/overview`; global session tools remain
at `/sessions`. The Recipe editor is no longer a primary navigation item, but is
reachable as advanced engine configuration until backend migration can safely
remove it. Do not claim it has been deleted.

## Directory

`WebsiteDirectory.svelte` uses one scan-friendly list, not a grid of metric cards:
website/domain, configured account count, loaded model count or unconfigured
state, then a clear navigation affordance. Counts come from server APIs.
Search, refresh, loading, failed catalog/account reads and no matches are explicit.

## Workspace

`SessionWorkspace.svelte` reuses the established history/message tools but is
now parameterized by a server-supplied `WebsiteInfo` and given a new layout:

1. `WebsiteToolbar`: website identity, open exact selected profile, account,
   model, model refresh, optional Thinking and project controls.
2. Task navigation: conversation, image generation only when a loaded model
   actually advertises image capability, diagnostics and new session.
3. History rail: server-side website filtering before LIMIT, full-text search,
   model/archive filters, selection and destructive confirmation.
4. Conversation and composer: output is primary; files, context choice, headed
   browser, sample prompts and account batch workbench remain available.
5. `WorkspaceContext`: actual account/project, persisted generation/count,
   session/operation identifiers, errors, website link and runtime explanation.

`ImageStudio` calls the real image endpoint on explicit user action. It creates
one image request; no automatic retry. Successful output is opened in its saved
session, using the existing attachment preview/download controls.

Qwen/ChatGPT use the durable new-message contract. A legacy recording is not
silently converted into a durable conversation. Changing model/project/pinned
account starts a new durable session instead of mixing a previous context.
Other websites retain the current API path until their runtime migration.

## Interaction and accessibility

- Loading, empty, error, busy and disabled states are explicit; errors provide a
  retry or a route to configuration. No fabricated browser step progress.
- Project/Thinking controls follow implemented site operations and account
  evidence; unavailable features are not presented as successful.
- Destructive session actions delete explicit IDs in the current visible filter,
  not the entire global database behind a scoped view.
- Wide screens keep the context inspector inline. Below 1280px it is a Bits UI
  Sheet with dialog name/description, focus containment and Escape handling.
- Below 1024px history is a drawer; when hidden it is also visually hidden so
  offscreen controls are not keyboard-focusable. App rail uses its existing Sheet.
- Header controls wrap, composer stays visible, narrow pages do not overflow
  horizontally. Respect reduced motion, visible focus and theme contrast.

## Verification and limitations

Read `docs/automation-ui-verification.md` for reproducible commands and coverage.
Browser QA uses fresh contexts, not the user's saved website profiles. Live UI
checks are read-only; behavioral API tests use intercepted fixtures. Neither is
evidence of a new live Qwen/ChatGPT/MiniMax provider verification.

The prior design document is preserved in
`docs/design-before-website-workspaces.md` as historical reference, including its
trace/flow notes; it is not current UI authority.
