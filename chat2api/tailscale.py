"""Mở cổng API ra tailnet bằng `tailscale serve --tcp`.

App desktop spawn sidecar ở 127.0.0.1 (desktop/src-tauri/src/lib.rs), nên máy
khác không gọi tới được. Thay vì bind lại 0.0.0.0 — mở luôn cho cả LAN và phải
restart server — module này nhờ tailscaled chuyển tiếp TCP từ
`<ip tailscale>:<port>` về `127.0.0.1:<port>`. Chỉ máy trong tailnet thấy, bật
tắt được lúc server đang chạy, và server không cần biết Tailscale tồn tại.

Cấu hình serve nằm trong tailscaled (`--bg`) nên sống qua cả lần khởi động lại
app lẫn máy; nó gắn với số cổng, vì vậy nên ghim `CHAT2API_PORT`.

Mọi hàm ở đây gọi tiến trình con (blocking) — handler async phải bọc
`asyncio.to_thread`.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT_S = 15


class TailscaleError(RuntimeError):
    pass


def find_cli() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    # Bộ cài Windows/macOS không phải lúc nào cũng thêm CLI vào PATH của tiến
    # trình đang chạy (sidecar thừa hưởng PATH từ lúc app desktop được mở).
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe",
        Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
    ]
    return next((str(p) for p in candidates if p.is_file()), None)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    cli = find_cli()
    if cli is None:
        raise TailscaleError("Không tìm thấy lệnh `tailscale` — cài Tailscale trước.")
    kwargs = {}
    if sys.platform == "win32":
        # Sidecar chạy không có console; thiếu cờ này mỗi lần gọi CLI sẽ nháy
        # một cửa sổ cmd lên màn hình.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.run(
            [cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=TIMEOUT_S, **kwargs)
    except subprocess.TimeoutExpired:
        raise TailscaleError(f"`tailscale {' '.join(args)}` không trả lời sau {TIMEOUT_S}s.")
    except OSError as error:
        raise TailscaleError(f"Không chạy được tailscale: {error}")


def _json(args: list[str]) -> dict:
    proc = _run(args)
    if proc.returncode != 0:
        raise TailscaleError((proc.stderr or proc.stdout).strip() or "tailscale báo lỗi")
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        raise TailscaleError("tailscale trả về JSON không đọc được")
    return data if isinstance(data, dict) else {}


def _check_port(port: int) -> int:
    if not isinstance(port, int) or not 0 < port < 65536:
        raise TailscaleError(f"cổng không hợp lệ: {port!r}")
    return port


def status(port: int) -> dict:
    """Trạng thái Tailscale và forwarder TCP của `port`. Không bao giờ raise."""
    out = {"installed": find_cli() is not None, "running": False, "state": "",
           "port": port, "open": False, "target": "", "ips": [], "dns_name": "",
           "urls": [], "error": ""}
    if not out["installed"]:
        return out
    try:
        node = _json(["status", "--json"])
        out["state"] = str(node.get("BackendState") or "")
        out["running"] = out["state"] == "Running"
        me = node.get("Self") or {}
        out["ips"] = [str(ip) for ip in me.get("TailscaleIPs") or []]
        out["dns_name"] = str(me.get("DNSName") or "").rstrip(".")
        if out["running"]:
            serve = _json(["serve", "status", "--json"])
            entry = (serve.get("TCP") or {}).get(str(port)) or {}
            # Cổng đang phục vụ HTTP/HTTPS của serve thì không có TCPForward —
            # đó không phải forwarder của mình.
            out["target"] = str(entry.get("TCPForward") or "")
            out["open"] = bool(out["target"])
    except TailscaleError as error:
        out["error"] = str(error)
    # IPv4 trước: đó là địa chỉ người dùng quen dán vào client.
    hosts = [ip for ip in out["ips"] if ":" not in ip]
    if out["dns_name"]:
        hosts.append(out["dns_name"])
    out["urls"] = [f"http://{host}:{port}" for host in hosts]
    return out


def open_tcp(port: int) -> dict:
    _check_port(port)
    proc = _run(["serve", "--bg", "--tcp", str(port), f"tcp://127.0.0.1:{port}"])
    if proc.returncode != 0:
        raise TailscaleError((proc.stderr or proc.stdout).strip() or "tailscale serve thất bại")
    return status(port)


def close_tcp(port: int) -> dict:
    _check_port(port)
    current = status(port)
    if current["installed"] and not current["open"] and not current["error"]:
        return current  # đã đóng sẵn: `serve ... off` sẽ báo lỗi "config does not exist"
    proc = _run(["serve", "--tcp", str(port), "off"])
    if proc.returncode != 0:
        raise TailscaleError((proc.stderr or proc.stdout).strip() or "tailscale serve off thất bại")
    return status(port)
