---
name: chat2api console
description: Technical operator console for testing an OpenAI-compatible API and turning web chat sites into models
colors:
  page: "#f3f5f7"
  panel: "#fbfcfd"
  raised: "#ffffff"
  muted: "#edf1f4"
  text: "#17202a"
  soft: "#536170"
  faint: "#687686"
  line: "#d7dee5"
  strong: "#b6c0ca"
  accent: "#1769e0"
  accent-hover: "#0f58c3"
  accent-soft: "#e4efff"
  danger: "#b82d3d"
  danger-soft: "#fbe8eb"
  success: "#13734a"
  success-soft: "#e1f4ea"
  terminal: "#182027"
  terminal-text: "#d8e2ea"
typography:
  display:
    fontFamily: "Segoe UI Variable, Aptos, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(1.875rem, 4.5vw, 3.25rem)"
    fontWeight: 400
    lineHeight: 1.02
    letterSpacing: "-0.05em"
  headline:
    fontFamily: "Segoe UI Variable, Aptos, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(1.5625rem, 3vw, 2.375rem)"
    fontWeight: 400
    lineHeight: 1.08
    letterSpacing: "-0.04em"
  title:
    fontFamily: "Segoe UI Variable, Aptos, Helvetica Neue, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Segoe UI Variable, Aptos, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Segoe UI Variable, Aptos, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 700
  mono:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "12px"
    lineHeight: 1.65
rounded:
  sm: "7px"
  md: "9px"
  lg: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "20px"
  xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#f7faff"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "#f7faff"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.danger}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  input-field:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    height: "42px"
    padding: "9px 11px"
  panel-container:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
---

# Design System: chat2api console

## Overview

**Creative North Star: "The Ops Console"**

chat2api's console is a plain-spoken operator surface, not a marketing page: a developer testing streaming completions or watching an integration job run needs to trust every number and status word at a glance. The system is built from a cool neutral gray scale with a single confident blue doing all the emphasis work — one accent, used sparingly, so it always means "primary action" or "you are here." Numbers, IDs, model names, and logs shift into a monospace face so they read as data rather than prose. Motion is a light entrance fade, never a flourish; the interface should feel calm even while a background job is polling every second.

The system already supports light and dark via `prefers-color-scheme`, with tokens re-mapped 1:1 rather than a separate palette — this is a hard invariant, not a nice-to-have, since the console is used long-session in either a bright office or a dark terminal-adjacent setup.

**Key Characteristics:**
- Cool neutral grays (page/panel/raised/muted) carry structure; color is reserved for accent, success, and danger states.
- One accent blue (`#1769e0` / `#63a1ff` dark) marks primary actions and the "selected" tab state — never decorative.
- Monospace (Cascadia Code) for anything numeric or log-like: metrics, latency, job logs, table model IDs, the brand mark.
- Sharp negative letter-spacing on display/headline sizes keeps large text feeling engineered, not editorial.
- Flat by default; a single soft ambient shadow lifts panels off the page, nothing else.

## Colors

Two role families: neutral structure (nine cool-gray steps from `page` to `strong`) and semantic accent/status colors (accent, success, danger), each with a paired `-soft` background tint. All values are re-declared inside a `prefers-color-scheme: dark` block with 1:1 token names, so the same component code renders correctly in both.

### Primary
- **Console Blue** (`#1769e0`, dark: `#63a1ff`): the one accent. Primary buttons, selected nav tab, focus rings, links, user chat bubble. The One Accent Rule below governs its use.

### Neutral
- **Page** (`#f3f5f7`, dark `#111417`): the outermost background, behind all panels.
- **Panel** (`#fbfcfd`, dark `#161a1e`): the resting surface for cards and panels.
- **Raised** (`#ffffff`, dark `#1b2025`): surfaces that sit above a panel — inputs, buttons, the assistant chat bubble.
- **Muted** (`#edf1f4`, dark `#20262c`): quiet fill for the segmented nav-tabs track, metric tiles, table headers.
- **Text** (`#17202a`, dark `#edf1f5`): primary reading color.
- **Soft** (`#536170`, dark `#b4bec8`): secondary text — labels, descriptions, table body copy.
- **Faint** (`#687686`, dark `#929eaa`): tertiary text — placeholders, empty-state hints, metric captions.
- **Line** (`#d7dee5`, dark `#303840`): hairline borders and dividers.
- **Strong** (`#b6c0ca`, dark `#46515c`): higher-contrast borders on interactive controls (inputs, buttons on hover).
- **Terminal** (`#182027`, dark `#0c1013`) / **Terminal Text** (`#d8e2ea`, dark `#dce5ed`): the job-log console, fixed dark regardless of page theme — it reads as an embedded terminal, not a themed panel.

### Status
- **Success** (`#13734a`, dark `#70d7a5`) with **Success Soft** (`#e1f4ea`, dark `#18392b`): healthy recipe state, "server ready" dot.
- **Danger** (`#b82d3d`, dark `#ff8692`) with **Danger Soft** (`#fbe8eb`, dark `#47252b`): error messages, delete actions, unhealthy recipe state.

### Named Rules
**The One Accent Rule.** Console Blue appears only on the primary action of a given view (send, integrate, selected tab) and on links/focus. Two competing primary buttons in one view is a violation; demote one to secondary.

## Typography

**Display/Body Font:** Segoe UI Variable, with Aptos, Helvetica Neue, Arial, sans-serif fallbacks — the OS-native UI face, deliberately not a bespoke display font, because this is a tool, not a brand moment.
**Mono Font:** Cascadia Code, with Consolas fallback — every numeric, identifier, or log value.

**Character:** A plain system sans carries prose and labels; the moment content becomes data (a count, an ID, a timestamp, raw log output) it switches face into mono. That switch is the system's main typographic signal, doing the work color usually does.

### Hierarchy
- **Display** (400, `clamp(1.875rem, 4.5vw, 3.25rem)`, 1.02, -0.05em): the Integrations page headline only.
- **Headline** (400, `clamp(1.5625rem, 3vw, 2.375rem)`, 1.08, -0.04em): the empty-chat state headline.
- **Title** (750, 17px, 1.2, -0.02em): panel/section headings (`h1`/`h2` inside a `.panel-head`).
- **Body** (400, 15px, 1.5): all prose, labels' surrounding text, message content.
- **Label** (700, 12px): field labels, uppercase table headers (`letter-spacing: .05em` on table headers specifically).
- **Mono** (400, 12px, 1.65): metrics, latency readout, job log, recipe model-id column, brand mark.

### Named Rules
**The Data-Switches-Face Rule.** Any value that is counted, measured, timestamped, or logged renders in Cascadia Code, never the body sans — this is how the eye tells "system-reported fact" from "written copy" without needing color.

## Layout

Single-column app shell: a sticky 68px topbar (brand, segmented nav tabs, health indicator) above a `main` region capped at `min(1400px, 100%)` and centered, with 24px side padding (16px under 640px). Two top-level views (Playground, Integrations) share the shell and swap via `hidden`, each fading in (`.view` keyframe, disabled under `prefers-reduced-motion`).

**Playground view:** a `workspace` grid, content column (`minmax(0,1fr)`) plus a fixed 310px sidebar, gap 20px. The chat panel itself is a three-row grid (header / scrollable message list / composer). Below 900px the grid collapses to a single column and the sidebar becomes a 2-up grid; below 640px everything stacks to one column and the composer's two actions become a 1:1 grid.

**Integrations view:** capped narrower at `min(1120px, 100%)`, a page heading followed by a two-column grid (`1.15fr` integration form : `0.85fr` "how it works" steps), then a full-width recipes table panel below. Below 900px the grid collapses to one column with the steps card reordered above the form.

Spacing rhythm is tight and consistent: 20px between major blocks, 14–18px panel padding, 7–13px between related fields. Cards never nest more than one level deep.

## Elevation & Depth

Mostly flat: panels sit on a slightly darker page background with a 1px `line` border, not a shadow, to separate regions. A single soft ambient shadow (`--shadow`) lifts every `.panel` and the toast off the page — one shadow value for the whole system, no per-component elevation scale.

### Shadow Vocabulary
- **Panel** (`0 18px 48px rgba(40,55,70,.08)`, dark `0 22px 58px rgba(0,0,0,.28)`): the only shadow in the system. Used on `.panel` and `.toast`.

### Named Rules
**The Flat-By-Default Rule.** Depth comes from the page/panel/raised background stack and hairline borders first; the single ambient shadow is a finishing touch on top-level containers, never a per-button or per-input effect.

## Shapes

Two radius steps carry the whole system: 7–9px on small interactive controls (buttons, inputs, chips, table-header corners) and 12px (`--radius`) on containers (panels, message bubbles). Nothing is fully rounded (pill) except the health-status dot, which is a plain circle. Borders are hairline (1px, `line` or `strong`) throughout; no heavy strokes.

## Components

### Buttons
- **Shape:** 9px radius, 40px min-height (34px `.small` variant).
- **Primary:** Console Blue background, `#f7faff` text, 700 weight, `9px 14px` padding; darkens to `--accent-hover` on hover, scales to 0.98 on active press.
- **Secondary:** `raised` background, hairline `line` border, `text` color; border brightens to `strong` and background shifts to `muted` on hover.
- **Danger:** transparent background, `danger`-tinted hairline border, `danger` text — used only for destructive actions (delete recipe).
- **Disabled:** 0.55 opacity, not-allowed cursor, no hover transform.

### Chat Messages
- **Shape:** 12px radius, max width 78% (min 92% on mobile), `13px 15px` padding, fade-and-rise entrance.
- **User:** Console Blue fill, white text, right-aligned, uppercase "Bạn" label above in translucent white.
- **Assistant:** `raised` background with hairline border, left-aligned, uppercase "Assistant" label in `faint`; shows a placeholder label while streaming is empty.
- **Error:** danger-soft background, danger-tinted border and text, uppercase "Lỗi" label.

### Cards / Panels
- **Corner Style:** 12px radius.
- **Background:** `panel`.
- **Shadow Strategy:** the single ambient panel shadow (see Elevation & Depth).
- **Border:** 1px `line`.
- **Internal Padding:** 15–18px panel head, 17px side-section body.

### Inputs / Fields
- **Style:** `raised` background, 1px `strong` border, 9px radius, 42px min-height.
- **Focus:** 3px outline in a 32%-mixed accent tint, 2px offset — same treatment across inputs, buttons, selects, and tabs.
- **Textarea (composer):** vertical-resize only, 48–180px height range.

### Navigation
- **Nav tabs:** segmented control — `muted` track, 10px radius, 4px padding; the selected tab is a `raised` pill with a soft shadow and full-weight text, the unselected tab is transparent with `soft` text.
- **Metrics tiles:** 2×2 grid of `muted`-filled tiles, mono value + `faint` caption label.
- **Health indicator:** dot + label; dot is `faint` while loading, `success` when connected, `danger` on connection loss.

### Recipes Table
- **Header:** `muted` background, `faint` uppercase 11px labels, `.05em` tracking.
- **Rows:** hairline top border between rows, no zebra striping.
- **State chip:** pill, `success-soft`/`success` when healthy, `danger-soft`/`danger` when `unhealthy`.
- **Mobile:** collapses to stacked label-less rows below 640px (table semantics preserved for accessibility, visual layout becomes block).

### Job Log
- **Style:** fixed-dark terminal surface (`terminal`/`terminal-text`) regardless of page theme, mono 12px/1.65, `min-height: 245px`, scrolling, hairline border in a slightly warmer dark gray than the terminal background.

### Toast
- **Style:** fixed bottom-right, `raised` background, hairline border, panel shadow, 13px text, auto-dismiss ~3.2s.

## Do's and Don'ts

### Do:
- **Do** keep exactly one accent-colored primary action visible per view.
- **Do** render counts, IDs, timestamps, and log output in Cascadia Code mono, never the body sans.
- **Do** reuse the single panel shadow for any new top-level container instead of inventing a new elevation value.
- **Do** keep light/dark token pairs 1:1 named so a component never needs theme-conditional logic beyond the CSS custom properties.

### Don't:
- **Don't** introduce a second accent hue; success/danger stay reserved for status, never for a second "primary" action.
- **Don't** give the job-log terminal a light-mode variant — it is deliberately theme-fixed.
- **Don't** add drop shadows to buttons, inputs, or table rows; elevation is reserved for panel-level containers.
- **Don't** exceed 12px corner radius anywhere; the system has no "large rounded" card language.
