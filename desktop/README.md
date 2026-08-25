# chat2api desktop

Native desktop shell for the chat2api console, built with Tauri (Rust) and a Svelte + SvelteKit (static/SPA) frontend. It ports the same playground + integrations UI served by the Python backend at `chat2api/playground/index.html`, matching the visual system recorded in `/DESIGN.md`.

On launch, the app spawns `python -m chat2api serve --port 8100` itself (see `src-tauri/src/lib.rs`) and stops it when the window closes — no separate terminal needed. This requires chat2api to already be installed in the Python environment the app's `python` resolves to (see the repo root `README.md` for `pip install -e ".[dev]"` + `playwright install chromium`). Set `CHAT2API_PYTHON` to point at a specific interpreter (e.g. a venv's `python.exe`) if `python` on `PATH` isn't the right one.

## Prerequisites

- Node.js 18+ and npm (already used to scaffold/build the frontend).
- Rust + Cargo — install via [rustup](https://www.rust-lang.org/tools/install).
- Tauri's OS-level prerequisites — see <https://tauri.app/start/prerequisites/> (on Windows: the WebView2 runtime, usually already present, and the MSVC "Desktop development with C++" workload).
- A Python 3.11+ environment with chat2api installed, per the repo root README.

This scaffold was generated and its frontend was type-checked (`npm run check`) and built (`npm run build`) in an environment without Rust available, so the Rust/Tauri side (`src-tauri/`) has not been compiled or run yet. Run the commands below locally once Rust is installed to build and smoke-test it.

## Develop

```sh
npm install
npm run tauri dev
```

## Build an installer

```sh
npm run tauri build
```

## Project layout

- `src/routes/+page.svelte` — app shell: top bar + Playground/Integrations view switch.
- `src/lib/components/` — `TopBar`, `PlaygroundView` (`ChatPanel` + `Sidebar`), `IntegrationsView`, `RecipesTable`, `Toast`.
- `src/lib/api.ts` — fetch client for the chat2api HTTP/SSE API (health, models, chat streaming, recipes, integration jobs).
- `src/lib/stores.ts` / `src/lib/sync.ts` — shared reactive state (API key, current view, server status, models/recipes lists).
- `src/app.css` — global styles/design tokens ported from the browser playground, per `/DESIGN.md`.
- `src-tauri/src/lib.rs` — spawns and supervises the Python server sidecar, exposes `api_base_url` to the frontend.
