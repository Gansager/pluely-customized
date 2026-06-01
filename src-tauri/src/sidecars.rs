// Bundled helper servers (STT + optional Claude proxy) spawned by the app itself,
// so a packaged install needs no external Python / Node / .cmd launchers.
//
// Layout (bundled as a Tauri resource folder "sidecar-servers", or found next to
// the exe for raw test builds):
//   sidecar-servers/stt/stt.exe          - faster-whisper STT (port 8766)
//   sidecar-servers/proxy/proxy.exe      - Claude CLI proxy   (port 8765)
//   sidecar-servers/models/whisper-base  - bundled STT model
//
// The active brain ("ollama" | "claude") is read from dist-mode.txt next to the
// exe (written by the installer). Default: ollama (fully local, no proxy needed).

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

#[derive(Default)]
pub struct SidecarState {
    children: Mutex<Vec<Child>>,
}

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn log_line(msg: &str) {
    use std::io::Write;
    let path = std::env::temp_dir().join("pluely-sidecars.log");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(f, "{}", msg);
    }
    eprintln!("[sidecars] {}", msg);
}

fn exe_dir() -> Option<PathBuf> {
    std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|p| p.to_path_buf()))
}

/// Strip the Windows verbatim prefix (\\?\) that resource_dir() returns — some
/// bundled tools (ctranslate2 / faster-whisper) can't open such paths.
fn deverbatim(p: PathBuf) -> PathBuf {
    let s = p.to_string_lossy();
    match s.strip_prefix(r"\\?\") {
        Some(rest) => PathBuf::from(rest),
        None => p,
    }
}

/// Locate the bundled servers folder. Prefer the Tauri resource dir, fall back
/// to a folder next to the exe (used when running the raw release build).
fn servers_root(app: &tauri::AppHandle) -> Option<PathBuf> {
    match app.path().resource_dir() {
        Ok(res) => {
            let p = res.join("sidecar-servers");
            log_line(&format!("resource_dir={} exists={}", p.display(), p.exists()));
            if p.exists() {
                return Some(deverbatim(p));
            }
        }
        Err(e) => log_line(&format!("resource_dir error: {}", e)),
    }
    if let Some(dir) = exe_dir() {
        let p = dir.join("sidecar-servers");
        log_line(&format!("exe_dir candidate={} exists={}", p.display(), p.exists()));
        if p.exists() {
            return Some(deverbatim(p));
        }
    }
    None
}

/// Read the install mode written by the installer (dist-mode.txt next to exe).
pub fn dist_install_mode() -> String {
    if let Some(dir) = exe_dir() {
        if let Ok(s) = std::fs::read_to_string(dir.join("dist-mode.txt")) {
            let m = s.trim().to_lowercase();
            if m == "claude" || m == "ollama" {
                return m;
            }
        }
    }
    "ollama".to_string()
}

fn spawn_server(children: &mut Vec<Child>, exe: PathBuf, args: &[String]) {
    if !exe.exists() {
        log_line(&format!("not found, skipping: {}", exe.display()));
        return;
    }
    let mut cmd = Command::new(&exe);
    cmd.args(args);
    if let Some(dir) = exe.parent() {
        cmd.current_dir(dir);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    log_line(&format!("spawning {} {:?}", exe.display(), args));
    match cmd.spawn() {
        Ok(child) => {
            log_line(&format!("started ok pid={:?}: {}", child.id(), exe.display()));
            children.push(child);
        }
        Err(e) => log_line(&format!("failed to start {}: {}", exe.display(), e)),
    }
}

/// Spawn the helper servers. STT always; the Claude proxy only in claude mode.
/// Servers that fail to bind (e.g. port already taken by an external launcher)
/// simply exit on their own — harmless.
pub fn spawn_all(app: &tauri::AppHandle) {
    log_line(&format!("spawn_all start; mode={}", dist_install_mode()));
    let root = match servers_root(app) {
        Some(r) => r,
        None => {
            log_line("servers root not found; nothing to spawn");
            return;
        }
    };
    log_line(&format!("servers root = {}", root.display()));
    let pid = std::process::id().to_string();
    let state = app.state::<SidecarState>();
    let mut children = match state.inner().children.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    };

    // STT (both modes).
    let stt = root.join("stt").join("stt.exe");
    let model = root.join("models").join("whisper-base");
    spawn_server(
        &mut children,
        stt,
        &[
            "--model".into(),
            model.to_string_lossy().to_string(),
            "--port".into(),
            "8766".into(),
            "--parent-pid".into(),
            pid.clone(),
        ],
    );

    // Claude CLI proxy (only when the install chose the Claude brain).
    if dist_install_mode() == "claude" {
        let proxy = root.join("proxy").join("proxy.exe");
        spawn_server(
            &mut children,
            proxy,
            &["--port".into(), "8765".into(), "--parent-pid".into(), pid.clone()],
        );
    }
}

/// Kill any spawned helpers (called on app exit).
pub fn kill_all(app: &tauri::AppHandle) {
    let state = app.state::<SidecarState>();
    if let Ok(mut children) = state.inner().children.lock() {
        for mut c in children.drain(..) {
            let _ = c.kill();
        }
    }
}

#[tauri::command]
pub fn get_dist_install_mode() -> String {
    dist_install_mode()
}
