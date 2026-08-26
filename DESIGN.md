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

- Desktop: collapsible sidebar with icon and label for Overview, Sessions, Integrations, Logs, and Settings.
- Narrow windows: sidebar becomes a focus-managed Sheet.
- Header: route context, connection details, sidebar trigger, and theme control.
- Overview and Settings use constrained content widths.
- Sessions and Logs use the full workspace.

## Screen contracts

### Overview

Lead with system health, then supporting metrics. Issues provide a related action. Browser runtime and integrated providers include explicit empty/loading/error states.

### Sessions

The conversation is primary. Session list is secondary; inspector and target workbench are tertiary panes. On narrow windows secondary panes become overlays. The composer remains visible. Keep all search, archive, pin, tags, fork, export, inspect, batch target, and rotation behaviors.

### Integrations

Order follows the workflow:

1. Add integration.
2. Observe analyzer progress and log.
3. Manage integrated sites/accounts.
4. Manage browser profiles.

All destructive actions use Alert Dialog; account creation uses Dialog.

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
