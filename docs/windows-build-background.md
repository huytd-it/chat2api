# Build EXE va chay nen tren Windows

## Build va khoi chay

Tu thu muc goc cua du an, chay:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-and-run.ps1 -Background
```

Lenh nay build ban Tauri release va mo ung dung nhu mot tien trinh nen. PowerShell se tra ve ngay sau khi app khoi dong.

## Tuy chon

Chi build EXE, khong chay app:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-and-run.ps1 -NoRun
```

Ghim cong loopback cua Python backend:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-and-run.ps1 -Background -Port 9123
```

## Dau ra va yeu cau

File EXE release nam trong `desktop\src-tauri\target\release\`.

Ban release la GUI app, nen khong mo cua so console. Python backend duoc app tu khoi dong lam sidecar va cung chay an. May chay EXE van can Python co `chat2api` va Playwright, ke ca Chromium. Chay script sau it nhat mot lan de cai dat cac phu thuoc:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\setup-and-run.ps1 -NoRun
```
