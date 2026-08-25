use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager, State};

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

/// Honors an explicit `CHAT2API_PORT` override (e.g. set by
/// `scripts/setup-and-run.ps1 -Port`) so the port can be pinned when a fixed
/// value is wanted; otherwise picks a free one automatically.
fn resolve_port() -> u16 {
    if let Ok(val) = std::env::var("CHAT2API_PORT") {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            match trimmed.parse::<u16>() {
                Ok(port) => {
                    eprintln!("[chat2api sidecar] using CHAT2API_PORT override: {port}");
                    return port;
                }
                Err(_) => {
                    eprintln!(
                        "[chat2api sidecar] CHAT2API_PORT=\"{trimmed}\" is not a valid port number, ignoring"
                    );
                }
            }
        }
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
    eprintln!("[chat2api sidecar] spawning: {python} -m chat2api serve --host 127.0.0.1 --port {port}");
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
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                stop_server(&window.app_handle().clone());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
