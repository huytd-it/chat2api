use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

/// Fallback port used only if the OS somehow fails to hand out a free one.
const FALLBACK_PORT: u16 = 8100;

struct ServerState {
    child: Mutex<Option<Child>>,
    port: Mutex<u16>,
}

#[tauri::command]
fn api_base_url(state: State<ServerState>) -> String {
    let port = *state.port.lock().unwrap();
    format!("http://127.0.0.1:{port}")
}

fn emit_log(app: &AppHandle, line: String) {
    eprintln!("[chat2api sidecar] {line}");
    let _ = app.emit("server-log", line);
}

/// Reserves an available loopback port by binding to port 0 and reading back
/// what the OS assigned, then releasing it. Windows reserves ranges of ports
/// for its own use (e.g. Hyper-V/WSL NAT) that silently fail to bind with a
/// permissions-style error — `netsh interface ipv4 show excludedportrange
/// protocol=tcp` lists them — so a single hardcoded port (chat2api's
/// documented default of 8100 among them, on some machines) isn't reliable
/// for a bundled desktop app. There's a small window between releasing the
/// port here and the Python process binding it where another process could
/// grab it first; acceptable for a single-user local dev tool.
fn pick_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(FALLBACK_PORT)
}

/// `chat2api.config.Config` loads `.env` and resolves the default `recipes/`
/// path relative to the *process's current working directory*, not its own
/// package location. Left unset, a spawned child just inherits this app's own
/// cwd (`desktop/src-tauri` under `cargo run`), so `.env` silently fails to
/// load and `recipes/` resolves to a nonexistent folder next to the Rust
/// crate -- the server comes up with zero configured keys/models and no
/// obvious error. `CARGO_MANIFEST_DIR` is baked in at compile time as this
/// crate's own path, so walking up two levels reliably reaches the repo root
/// regardless of what directory the app happens to be launched from.
/// `CHAT2API_WORKDIR` overrides it, e.g. for a future bundled install where
/// there's no repo checkout at all.
fn resolve_workdir() -> PathBuf {
    if let Ok(dir) = std::env::var("CHAT2API_WORKDIR") {
        if !dir.trim().is_empty() {
            return PathBuf::from(dir);
        }
    }
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// A port the OS won't let us bind to — already in use, or inside a range
/// Windows reserves for its own use (Hyper-V/WSL, per `netsh interface ipv4
/// show excludedportrange protocol=tcp`) — can't serve the backend. Verify a
/// configured port before committing to it; fall back to auto-pick otherwise.
fn port_is_bindable(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// Reads a `CHAT2API_PORT`-style value from the process environment. Returns
/// None (logging why) when the variable is absent, unparsable, 0, or not
/// bindable.
fn configured_port(key: &str, source: &str) -> Option<u16> {
    let val = std::env::var(key).ok()?;
    let trimmed = val.trim();
    if trimmed.is_empty() {
        return None;
    }
    let Ok(port) = trimmed.parse::<u16>() else {
        eprintln!("[chat2api sidecar] {key}=\"{trimmed}\" ({source}) is not a valid port number, ignoring");
        return None;
    };
    if port == 0 {
        eprintln!("[chat2api sidecar] {key}=\"{trimmed}\" ({source}) is 0 (auto), ignoring");
        return None;
    }
    if !port_is_bindable(port) {
        eprintln!(
            "[chat2api sidecar] {key}=\"{trimmed}\" ({source}) is not bindable (in use or inside a Windows-excluded port range), auto-picking instead"
        );
        return None;
    }
    eprintln!("[chat2api sidecar] using {key} from {source}: {port}");
    Some(port)
}

/// Reads `CHAT2API_PORT` from the `.env` file in the sidecar workdir — the
/// same file the Python backend loads — so the port can be pinned persistently
/// (edit `.env`, double-click the exe) instead of setting an environment
/// variable on every launch. Process env wins; this is the fallback.
fn dotenv_port() -> Option<u16> {
    let env_path = resolve_workdir().join(".env");
    let Ok(contents) = std::fs::read_to_string(&env_path) else {
        return None;
    };
    for line in contents.lines() {
        let line = line.trim();
        if line.starts_with('#') || !line.contains('=') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if key.trim() != "CHAT2API_PORT" {
            continue;
        }
        let value = value.trim().trim_matches(|c| c == '"' || c == '\'');
        let Ok(port) = value.parse::<u16>() else {
            eprintln!("[chat2api sidecar] CHAT2API_PORT=\"{value}\" (.env) is not a valid port number, ignoring");
            return None;
        };
        if port == 0 {
            eprintln!("[chat2api sidecar] CHAT2API_PORT=\"{value}\" (.env) is 0 (auto), ignoring");
            return None;
        }
        if !port_is_bindable(port) {
            eprintln!(
                "[chat2api sidecar] CHAT2API_PORT=\"{value}\" (.env) is not bindable (in use or inside a Windows-excluded port range), auto-picking instead"
            );
            return None;
        }
        eprintln!("[chat2api sidecar] using CHAT2API_PORT from .env: {port}");
        return Some(port);
    }
    None
}

/// Resolves the port the backend should bind. Sources, in priority order:
///   1. The process environment variable `CHAT2API_PORT` (set by
///      `scripts/build-desktop.ps1 -Port`, `scripts/setup-and-run.ps1 -Port`).
///   2. `CHAT2API_PORT` in the sidecar workdir's `.env` — persistent config so
///      a standalone exe keeps the same port across launches.
/// Otherwise picks a free one automatically.
fn resolve_port() -> u16 {
    if let Some(port) = configured_port("CHAT2API_PORT", "environment") {
        return port;
    }
    if let Some(port) = dotenv_port() {
        return port;
    }
    pick_free_port()
}

/// Spawns the Python chat2api server as a background process and streams its
/// stdout/stderr to the frontend as `server-log` events. The process handle
/// is stored in managed state so it can be killed when the window closes.
///
/// This assumes a system Python with chat2api installed (`pip install -e .`),
/// matching the project's current dev setup — see PRODUCT.md's Capabilities
/// section for the still-undecided fully-bundled-runtime path.
fn spawn_server(app: &AppHandle) {
    let port = resolve_port();
    {
        let state: State<ServerState> = app.state();
        *state.port.lock().unwrap() = port;
    }

    let python = std::env::var("CHAT2API_PYTHON").unwrap_or_else(|_| "python".to_string());
    // The CLI's own default host is 0.0.0.0 (all interfaces), which uvicorn
    // then logs as "http://0.0.0.0:<port>" -- not an address a browser can
    // actually open. The desktop app only ever talks to it over loopback, so
    // bind there explicitly: it's both the address that's actually usable and
    // avoids exposing the API to the local network for no reason.
    let workdir = resolve_workdir();
    eprintln!(
        "[chat2api sidecar] spawning: {python} -m chat2api serve --host 127.0.0.1 --port {port} (cwd: {})",
        workdir.display()
    );
    let mut cmd = Command::new(&python);
    cmd.args([
        "-m",
        "chat2api",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        &port.to_string(),
    ])
    .current_dir(&workdir)
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());

    // Prevent a console window from flashing up alongside the app window.
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(mut child) => {
            if let Some(stdout) = child.stdout.take() {
                let app = app.clone();
                std::thread::spawn(move || {
                    for line in BufReader::new(stdout).lines().flatten() {
                        emit_log(&app, line);
                    }
                });
            }
            if let Some(stderr) = child.stderr.take() {
                let app = app.clone();
                std::thread::spawn(move || {
                    for line in BufReader::new(stderr).lines().flatten() {
                        emit_log(&app, line);
                    }
                });
            }
            let state: State<ServerState> = app.state();
            *state.child.lock().unwrap() = Some(child);
        }
        Err(e) => {
            emit_log(
                app,
                format!("failed to start chat2api server ({python} -m chat2api serve): {e}"),
            );
        }
    }
}

fn stop_server(app: &AppHandle) {
    let state: State<ServerState> = app.state();
    let child = state.child.lock().unwrap().take();
    if let Some(mut child) = child {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(ServerState {
            child: Mutex::new(None),
            port: Mutex::new(FALLBACK_PORT),
        })
        .invoke_handler(tauri::generate_handler![api_base_url])
        .setup(|app| {
            spawn_server(&app.handle().clone());

            let quit_i = MenuItem::with_id(app, "quit", "Thoát", true, None::<&str>)?;
            let open_i = MenuItem::with_id(app, "open", "Mở chat2api", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_i, &quit_i])?;
            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => {
                        stop_server(app);
                        app.exit(0);
                    }
                    "open" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                stop_server(app_handle);
            }
        });
}
