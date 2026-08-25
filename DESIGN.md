---
name: chat2api console
description: Bench-instrument operator console for testing an OpenAI-compatible API and turning web chat sites into models
colors:
  chassis: "#14171a"
  panel: "#1b2022"
  raised: "#21272a"
  muted: "#242b2d"
  text: "#dfe3df"
  soft: "#a9b2ad"
  faint: "#8f9894"
  line: "#333c3e"
  strong: "#4a5355"
  phosphor: "#57e08a"
  phosphor-hover: "#7be8a3"
  phosphor-dim: "#2c6b47"
  phosphor-soft: "rgba(87, 224, 138, 0.14)"
  phosphor-glow: "rgba(87, 224, 138, 0.7)"
  on-phosphor: "#0d1410"
  amber: "#f0a63e"
  amber-soft: "rgba(240, 166, 62, 0.16)"
  fault: "#ff6259"
  fault-soft: "rgba(255, 98, 89, 0.16)"
  fault-glow: "rgba(255, 98, 89, 0.7)"
  crt: "#0a0d0a"
  crt-deep: "#07120b"
  crt-text: "#8be8a8"
  phosphor-bright: "#eafff2"
  phosphor-tint: "#d7f5e2"
  phosphor-code: "#a9edc3"
  amber-tint: "#ffe1b3"
  fault-tint: "#ffd4d1"
  plate-light: "#2a3234"
  plate-dark: "#171b1c"
  housing-light: "#191e20"
  housing-dark: "#101314"
  well-light: "#121615"
  well-dark: "#0d100f"
  knob-light: "#cfd6d2"
  knob-dark: "#9aa39e"
  bezel-highlight: "rgba(255, 255, 255, 0.09)"
  well: "rgba(0, 0, 0, 0.4)"
typography:
  display:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "clamp(32px, 6vw, 96px)"
    fontWeight: 700
    lineHeight: 0.92
    letterSpacing: "0.002em"
  headline:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "clamp(30px, 4vw, 48px)"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.005em"
  title:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.02em"
  subtitle:
    fontFamily: "Big Shoulders Display, Arial Narrow, sans-serif"
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.03em"
  body:
    fontFamily: "Archivo, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  body-lg:
    fontFamily: "Archivo, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "Archivo, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Archivo, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: "0.06em"
  caption:
    fontFamily: "Archivo, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.09em"
  micro:
    fontFamily: "Archivo, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "10px"
    fontWeight: 700
    letterSpacing: "0.09em"
  nano:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "9px"
    fontWeight: 700
    letterSpacing: "0.06em"
  nano-compact:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "8px"
    fontWeight: 700
    letterSpacing: "0.06em"
  mono:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "12px"
    lineHeight: 1.65
  mono-sm:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "11px"
    lineHeight: 1.5
  readout:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1
  readout-sm:
    fontFamily: "Cascadia Code, Consolas, monospace"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1
rounded:
  xs: "4px"
  sm: "6px"
  thumb: "8px"
  toggle: "9px"
  md: "10px"
  rivet: "6px"
  pill: "999px"
  circle: "50%"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "20px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.phosphor}"
    textColor: "{colors.on-phosphor}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "38px"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "38px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.fault}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "38px"
  button-small:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "32px"
  input-field:
    backgroundColor: "{colors.chassis}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: "40px"
    padding: "9px 11px"
  panel-container:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.md}"
  stat-tile:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.phosphor}"
    rounded: "{rounded.md}"
    padding: "14px 16px"
  crt-surface:
    backgroundColor: "{colors.crt}"
    textColor: "{colors.crt-text}"
    rounded: "{rounded.sm}"
---

# Design System: chat2api console

## Overview

**Creative North Star: "The Instrument Bench"**

chat2api's console is not a chatbot demo and not a marketing page — it is a piece of bench equipment. Every panel is something the operator probes, calibrates, or reads off, never something to scroll past. The chassis is charcoal-graphite with brushed-steel bezels and engraved off-white panel labels; a single phosphor-green signal colour carries everything that is live, amber everything in progress, and calibration-red every fault. The operator selects a channel, sends a probe, watches the reply draw as a live trace, reads server vitals off a permanent left rail, and wires new sites in at a calibration bench.

This is a **dark-only** system (`color-scheme: dark`). There is deliberately no light theme: the console is read next to a terminal and the phosphor/CRT metaphor only holds on a dark chassis. Do not add a `prefers-color-scheme: light` block.

**Key Characteristics:**
- A charcoal stack (chassis → panel → raised → muted) carries structure; colour is reserved for signal, progress, and fault.
- One phosphor green (`#57e08a`) means "live / primary / you are here" — never decorative.
- Condensed uppercase display type (Big Shoulders Display) for nameplates and headlines; Archivo for prose; Cascadia Code for every readout.
- Glow, not shadow, communicates state: lamps and status dots carry a coloured `box-shadow` halo.
- Panels are physical objects — hairline border, inset top highlight, and four engraved rivet dots at the corners.

## Colors

Two role families: the neutral chassis stack (nine charcoal steps from `chassis` to `strong`) and the signal colours (phosphor, amber, fault), each with a paired `-soft` tint for backgrounds and a `-glow` value for lamp halos.

### Primary
- **Phosphor** (`#57e08a`, hover `#7be8a3`, dim `#2c6b47`): the one signal colour. Primary buttons, the current nav tab, live lamps, focus rings, links, streaming trace, stat readouts. Text on a phosphor fill is **On-Phosphor** (`#0d1410`), never white.

### Neutral
- **Chassis** (`#14171a`): the outermost body, behind all panels; also the recessed fill of inputs.
- **Panel** (`#1b2022`): the resting face of cards and panels.
- **Raised** (`#21272a`): surfaces sitting above a panel — secondary buttons, rocker tabs.
- **Muted** (`#242b2d`): quiet fill for table headers, metric tiles, badges, the account flow strip.
- **Text** (`#dfe3df`): primary reading colour, an off-white engraved label tone.
- **Soft** (`#a9b2ad`): secondary text — labels, descriptions, table body copy.
- **Faint** (`#8f9894`): tertiary text — placeholders, empty-state hints, tile captions.
- **Line** (`#333c3e`): hairline borders and dividers.
- **Strong** (`#4a5355`): higher-contrast borders on interactive controls.

### Status
- **Amber** (`#f0a63e`) with **Amber Soft**: work in progress and warnings — a running job, a trial-limit badge, a setting that needs a restart, a domain with no account yet.
- **Fault** (`#ff6259`) with **Fault Soft**: errors, destructive actions, unhealthy recipes, lost connection.

### Instrument
- **CRT** (`#0a0d0a`) / **CRT Text** (`#8be8a8`): the oscilloscope ground and phosphor trace — job logs, the app log, live-view wells. Always this pair, never a themed panel.
- **CRT Deep** (`#07120b`): a step darker than CRT, for a well recessed *inside* a CRT surface (code blocks and the composer inside the trace).

### On-Surface Tints
Text sitting on a coloured fill uses a lightened tint of that signal, never plain white — it keeps the glass feeling lit from behind.
- **Phosphor Bright** (`#eafff2`): selection text, the brightest phosphor step.
- **Phosphor Tint** (`#d7f5e2`) / **Phosphor Code** (`#a9edc3`): bold text and inline code inside an assistant trace.
- **Amber Tint** (`#ffe1b3`): probe (user) message text on the amber-bordered bubble.
- **Fault Tint** (`#ffd4d1`): error message text on a fault-soft fill.

### Machined Hardware
Physical parts are two-stop gradients, not flat fills — this is what separates a control from a coloured rectangle.
- **Plate** (`#2a3234` → `#171b1c`, 155°): the brand nameplate.
- **Housing** (`#191e20` → `#101314`): the vitals rail body.
- **Well** (`#121615` → `#0d100f`): a recessed toggle track.
- **Knob** (`#cfd6d2` → `#9aa39e`): the brushed-steel toggle knob — the only near-white surface in the system.

### Named Rules
**The One Signal Rule.** Phosphor marks exactly one primary action per view plus the current nav tab, live lamps, and focus. Two competing phosphor-filled buttons in one view is a violation — demote one to secondary.

**The Glow-Means-State Rule.** A coloured `box-shadow` halo is reserved for elements reporting live state (lamps, status dots, the phosphor button). Never apply a glow to decorate a static element.

## Typography

**Display Font:** Big Shoulders Display (Arial Narrow fallback) — condensed, always uppercase, for nameplates and page headlines only.
**Body Font:** Archivo (Segoe UI, Helvetica Neue, Arial fallbacks) — all prose, labels, and controls.
**Mono Font:** Cascadia Code (Consolas fallback) — every value the machine reports.

**Character:** Three faces, three jobs. Condensed display type shouts the panel name; Archivo carries the sentence; the moment content becomes a machine-reported fact — a count, an ID, a timestamp, a latency, raw log output — it switches to Cascadia Code. That switch is the system's main typographic signal.

### Hierarchy
- **Display** (700, `clamp(32px, 6vw, 96px)`, 0.92, uppercase): the page headline on a top-level page (`.page-heading h1`).
- **Headline** (700, `clamp(30px, 4vw, 48px)`, 1.0, uppercase): the empty-chat state.
- **Title** (700, 20px, uppercase): integration card headings.
- **Subtitle** (700, 17px, uppercase): the brand nameplate.
- **Body** (400, 15px, 1.55): all prose and message content.
- **Body Large** (400, 16px): page-heading lede paragraph.
- **Body Small** (400, 13px): dense panel copy, list rows, toast.
- **Label** (700, 12px, `.06em`): field labels and nav tabs (uppercase).
- **Caption** (700, 11px, `.09em`, uppercase): table headers, state chips.
- **Micro** (700, 10px, `.09em`, uppercase): tile captions, live-view and log labels.
- **Nano** (700 mono, 9px, `.06em`, uppercase): rail labels, the settings apply tag.
- **Nano Compact** (700, 8px, uppercase): the vitals rail only, below 640px — the smallest step in the system. When the rail narrows from 52px to 36px its label *and* value both drop to this size, in their own faces. Nothing else may use 8px.
- **Mono** (12px, 1.65): job log, app log, metric values, model IDs.
- **Mono Small** (11px): badges, rail values, channel meta.
- **Readout** (700 mono, 30px): the dashboard stat number.
- **Readout Small** (700 mono, 18px): nixie-style metric tiles.

### Named Rules
**The Data-Switches-Face Rule.** Any value that is counted, measured, timestamped, identified, or logged renders in Cascadia Code, never Archivo — this is how the eye separates "system-reported fact" from "written copy" without needing colour.

**The Uppercase-Display Rule.** Big Shoulders Display is always uppercase. If a heading would read better in sentence case, it is body copy, not a display heading.

## Layout

App shell: a permanent 52px vitals **rail** down the left edge, a sticky 64px **topbar** (nameplate, rocker-switch nav, health indicator) and a `main` region. The topbar's inner grid is `minmax(180px,1fr) auto minmax(180px,1fr)` capped at `min(1400px, 100%)`, padded left by `calc(var(--rail-w) + 20px)` to clear the rail.

Navigation is **real routes**, one per workspace: `/` (overview), `/playground`, `/recipes`, `/accounts`, `/integrations`, `/logs`, `/settings`. Each page fades in via the `.view` keyframe (disabled under `prefers-reduced-motion`). The nav strip scrolls horizontally rather than wrapping when the window is narrow.

**Page widths:** `.page` and `.logs` cap at `min(1280px, 100%)`; `.integrations` caps narrower at `min(1120px, 100%)`; `.workspace` (playground) fills the shell as `minmax(0,1fr)` plus a fixed 310px sidebar.

**Playground:** the chat panel is a three-row grid (header / scrollable trace / composer). Below 900px the grid collapses to one column and the sidebar becomes 2-up; below 640px everything stacks.

**Page pattern:** every management page is `.page` — a `.page-heading`, then `.panel` blocks. Dense grids auto-fit (`stat-grid` at 150px min, `dash-grid` at 300px, `settings-grid` at 260px) so pages reflow without per-breakpoint rules.

Spacing rhythm: 20px between major blocks, 14–20px panel padding, 7–13px between related fields. Cards never nest more than one level deep.

## Elevation & Depth

Depth is physical, not floaty. Panels sit on the darker chassis with a hairline border, a strong ambient shadow, and an inset top highlight that reads as light catching a bezel edge. Recessed controls (inputs, the composer, log wells) invert the metaphor with an inner shadow so they read as milled into the chassis.

### Shadow Vocabulary
- **Panel** (`0 26px 60px rgba(0, 0, 0, 0.6)`): the ambient lift under `.panel` and `.toast`.
- **Bezel highlight** (`inset 0 1px 0 rgba(255, 255, 255, 0.035)`): paired with the panel shadow on every raised surface and control.
- **Lamp glow** (`0 0 8–16px` of a `-glow` colour): live state only.

### Named Rules
**The Rivet Rule.** `.panel` carries four engraved corner dots via `::before`, inset 7px. It is what makes a panel read as a machined face — do not build a new top-level container that skips it.

## Shapes

Two radius steps carry the whole system: 6px (`--radius-sm`) on controls — buttons, inputs, chips, badges — and 10px (`--radius`) on containers. Pills (`999px`) are reserved for state chips, saved-account tokens, and the settings apply tag. Circles (`50%`) are for lamps, status dots, avatars, and the toggle knob. Borders are hairline (1px) throughout.

Three smaller radii exist only for named hardware and should not be reached for on new components: **4px** on the brand nameplate, **8px** on the scrollbar thumb, **9px** on the toggle track.

The rivet ring is derived, not fixed: `--radius-rivet: calc(var(--radius) - 4px)` so the engraved inset keeps tracking the panel corner if the container radius ever changes. Use the token, never the literal.

## Components

### Buttons — lit rocker switches
- **Shape:** 6px radius, 38px min-height (32px `.small`).
- **Primary:** phosphor gradient fill, `#0d1410` text, 700/12px uppercase, phosphor glow; brightens on hover, presses 1px down and scales 0.99 on active.
- **Secondary:** `raised`→`panel` gradient, `line` border, `text` colour; border lifts to `strong` and fill to `muted` on hover.
- **Danger:** transparent, fault-tinted hairline border, fault text — destructive actions only.
- **Disabled:** 0.5 opacity, not-allowed cursor, no transform.
- Anchors styled as buttons must add `display: inline-flex; align-items: center; text-decoration: none`.

### Navigation — rocker tabs
- **Nav tab:** `raised`→`panel` gradient pill, 36px, uppercase 12px label. The current route (`[aria-current="page"]`) fills phosphor with `#0d1410` text and a phosphor glow.
- **Vitals rail:** fixed 52px column; vertical (`writing-mode: vertical-rl`) mono values with a lamp per reading — `on` phosphor, `warn` amber, `fault` red.
- **Health indicator:** dot + uppercase mono label; faint while loading, phosphor when connected, fault on loss.

### Panels
- **Corner:** 10px radius, hairline `line` border, panel gradient over `panel`, ambient shadow + bezel highlight, four rivet dots.
- **`.panel-head`:** ≥66px, title left with optional sub-line, actions right, divided by a hairline.
- **`.dash-body`:** 16px/20px padded content grid, 10px gap — the standard body for a management panel.

### Readouts
- **Stat tile (`.stat`):** 30px phosphor mono number over a 10px uppercase faint caption. The dashboard's primary instrument.
- **Metric tile (`.metric`):** 2-up muted tiles, 18px mono value + faint caption.
- **Alert (`.alert`):** a soft-tinted, coloured-text block — `ok` phosphor, `amber` in-progress/warning, `fault` error. Alerts state a condition; they never carry a button.
- **Status dot (`.dot`):** 8px circle with a glow when `on` or `fault`.

### Inputs / Fields
- **Style:** recessed `chassis` fill, 1px `strong` border, 6px radius, 40px min-height, inset highlight. Global `input, select` styling covers these — do not add a per-page input class.
- **Focus:** 2px phosphor outline, 2px offset, applied uniformly to inputs, buttons, selects, and tabs.
- **Composer textarea:** 48–200px, no manual resize.

### Tables
- **Header:** `muted` fill, faint uppercase 10–11px labels, `.09em` tracking.
- **Rows:** hairline top border, no zebra striping. Action cells right-align via `.recipe-actions` / `.col-actions`.
- **State chip:** pill with a glowing dot — phosphor-soft when healthy, fault-soft when unhealthy.

### Instrument surfaces
- **Job log / app log:** CRT ground with phosphor trace, mono 12px/1.65, scrolling, min-height 245px, with an empty-state message via `:empty:before`.
- **Live view:** CRT-grounded well, phosphor-dim border, micro uppercase label, screenshot refreshed ~700ms.

### Toast
- Fixed bottom-right, `panel` fill, phosphor-dim border, panel shadow, 13px, leading phosphor dot, auto-dismiss ~3.2s.

## Do's and Don'ts

### Do:
- **Do** keep exactly one phosphor-filled primary action visible per view.
- **Do** render counts, IDs, timestamps, domains, and log output in Cascadia Code, never Archivo.
- **Do** give any new top-level container the `.panel` treatment — border, ambient shadow, bezel highlight, rivets.
- **Do** use `.alert` with the right status tint to state a condition, and put the fix in a nearby button.
- **Do** reach for the auto-fit grids (`stat-grid`, `dash-grid`, `settings-grid`) before writing new breakpoints.

### Don't:
- **Don't** add a light theme or a `prefers-color-scheme: light` block; the CRT and phosphor metaphors require the dark chassis.
- **Don't** introduce a second signal hue — amber and fault stay reserved for progress and failure, never for a second "primary".
- **Don't** put a glow on anything that is not reporting live state.
- **Don't** set Big Shoulders Display in sentence case, or use it below 17px — smaller labels belong to Archivo.
- **Don't** exceed the 10px container radius; pills are only for chips, tokens, and tags.
