# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Svelte + Vite single-page frontend, packaged as a Tauri (Rust) desktop shell. Tauri spawns the existing Python chat2api server as a sidecar process on launch, so the app is self-contained (no manual `python -m chat2api serve`). Confirmed with the user for this new desktop surface.

## Users

Developers/operators running chat2api locally who want to (a) test provider integrations against the OpenAI-compatible API (streaming completions, model listing) and (b) turn a new web chat site into a callable model via the agent-driven "Integrate" flow. They currently do this through a browser-hosted playground (`chat2api/playground/index.html`) served by the local FastAPI app; the desktop app targets the same audience who want a native, self-contained local tool instead of juggling a terminal and a browser tab.

## Product Purpose

chat2api turns any web chat AI into an OpenAI-compatible API, replacing manual copy/paste between a browser and a script. The desktop app is a native shell around the same functionality: a playground for testing streaming chat completions, and an Integrate flow that uses an LLM agent to analyze a new web chat site, generate a "recipe," and register it as a usable model.

## Positioning

Unlike ad hoc browser extensions or one-off scraping scripts, chat2api has a repeatable recipe system (YAML per site) plus agent-assisted authoring of new recipes and a fallback path (agent drives the browser directly) when a recipe breaks. Packaging the console as a Tauri desktop app turns it from "run a Python command, open a browser tab" into a self-contained local app.

## Operating Context

- Backend: Python 3.11+ FastAPI app (`chat2api/main.py`), normally started via `python -m chat2api serve --port 8100`; exposes `POST /v1/chat/completions` (SSE streaming), `GET /v1/models`, and serves the playground HTML at `/`.
- Recipes live under `RECIPES_DIR` (YAML + secrets) and define how each site is driven — Playwright browser automation, or direct HTTP for OpenAI-compatible upstreams (e.g. Qwen).
- Integration flow: agent-driven browser automation analyzes a new chat site and authors a recipe (`python -m chat2api integrate <url>`); sites requiring login use a separate `login <slug>` handoff, then re-run integrate.
- Fallback: when a recipe fails repeatedly (`ENABLE_AGENT_FALLBACK=true`), the agent controls the browser directly instead of the broken recipe.
- New desktop surface: Tauri shell wrapping a Svelte + Vite SPA. Tauri manages the Python server as a sidecar (start on launch, stop on quit) so the desktop app needs no separate terminal.

## Capabilities and Constraints

- The existing browser playground already implements the functional scope to match: a streaming chat test panel (model/key selection, SSE responses), server health/metrics (models, contexts, engine), and an Integrations tab (URL submit, job log, login handoff, recipes table with health state). The desktop SPA should reach equivalent feature parity, rebuilt in Svelte rather than ported line-for-line.
- Desktop packaging must be able to locate or bundle a Python 3.11+ runtime with chat2api installed to run the sidecar. Exact approach (bundle a venv vs. require a local `pip install -e .`) is undecided.
- Undecided: target OS distribution for the desktop build (Windows-only, matching the current dev environment, vs. cross-platform Win/macOS/Linux).

## Brand Commitments

Product name "chat2api." The existing console UI (terse, technical, monospace-accented, light/dark theme, "c2a" brand mark) is evidence of the current visual system, not a binding constraint recorded here — visual direction for the new surface is decided in `new-work`/`document`, not init.

## Evidence on Hand

Working reference implementation at `chat2api/playground/index.html` (currently the app's UI, git-modified) demonstrates the full current feature set and visual system to match or evolve from. `README.md` documents setup, env vars, and the integrate/login/fallback flows.

## Product Principles

- The desktop app is a shell, not a rewrite: all business logic (routing, recipes, providers, browser automation) stays in the existing Python backend and is reached over the same HTTP/SSE API.
- Feature parity before desktop-only extras: match what the browser playground already does (playground + integrations) before adding capabilities the web version lacks.
- Self-contained by default: launching the app should not require the user to separately manage a terminal or server process.
- Keep the SPA framework lightweight (Svelte) to match a small, focused local tool rather than a large web app.

## Accessibility & Inclusion

No product-specific requirement beyond what the existing playground already implements (visible focus states, `prefers-reduced-motion` handling, responsive layout down to mobile widths).
