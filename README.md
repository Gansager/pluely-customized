# Pluely — Customized (Gansager fork)

A personal Windows-only fork of [iamsrikanthnani/pluely](https://github.com/iamsrikanthnani/pluely) with workflow patches for live customer / engineering calls. The upstream README is preserved at [`README-upstream.md`](./README-upstream.md).

> **Platform support:** Windows 10 / 11 only. The recorder, the system audio capture pipeline, the proxy launcher scripts, and the screenshot tooling are all WASAPI / Windows-specific. macOS and Linux are **not** supported in this fork.

## What's different from upstream

Headline changes shipped on top of stock `v0.1.9`:

- **Unified listening button.** The headphones icon starts both system-audio capture and microphone VAD in one click. `[ME]` / `[THEM]` speaker tags get added automatically. AI never auto-fires — press `Ctrl+Space` to ask the model about the latest transcript.
- **Independent call recorder ("dictaphone").** Stereo WAV of mic + system audio, fully separate from the STT pipeline. Output: `~/Documents/Pluely Recordings/`. Middle-click the recorder icon to open the folder.
- **Right-click message actions.** On any message in the conversation popover, right-click for **Explain / Translate / Answer** — each runs a focused prompt that ignores the meeting-coach system prompt.
- **Permissive Ctrl+Space.** Even when a narrow system prompt is configured (e.g. "only help with project X"), the assistant will answer any question. The user's context is passed through but doesn't restrict topic.
- **Screenshot with custom proxy support.** The bundled `proxy.py` (see `pluely-proxy` setup below) saves attached screenshots to a temp PNG and hints Claude Code's CLI to open it via its Read tool. Works around the Claude Code CLI not accepting stdin images.
- **Multi-monitor selection mode fixed.** The Tauri overlay used to render opaque (white) on secondary monitors with mixed DPI. The fork now draws the captured snapshot directly as the overlay background — works on every screen.
- **Master license switch.** All paid-feature gates are unlocked (`Promote` banner, 🔒 Premium Features banner on Responses, GetLicense buttons across pages). `hasActiveLicense` is forced to `true`, `validate_license_api` is never called. `supportsImages` is also clamped to `true` so the Screenshot button is always active.
- **Manual AI mode by default.** Stock Pluely auto-runs the AI on every transcribed chunk. This fork persists the chunk and waits for `Ctrl+Space`.
- **Default to conversation view.** The System Audio popover opens in full conversation view, not single-reply mode.
- **Exit button + always-on drag handle.** Quit and move-window buttons live directly on the panel — no menu hunt, no Get License modal.
- **English UI** for the context menu and error strings.
- **Auto-recover from stuck capture state.** Stale "Capture already running" errors now self-heal.
- **Delete all conversations.** One-click wipe in the Chats tab.
- **Auto-updater disabled.** Stock updater would overwrite the fork's patches.

A full changelog and rationale for each patch lives in commit messages on `master`.

## Install (use the pre-built binary)

If you only want to use the fork, not modify it:

1. Download the latest `pluely_*.msi` or `pluely_*-setup.nsis` from the [Releases](https://github.com/Gansager/pluely/releases) tab (or build locally, see below).
2. Run the installer.
3. Configure an AI provider in **Settings → Dashboard**:
   - Direct Anthropic API (recommended for image / Claude vision support), or
   - Local Ollama (text-only unless a vision model like `llava` / `llama3.2-vision` is loaded), or
   - The bundled `pluely-proxy` setup (see below).
4. Configure an STT provider — local Whisper via the proxy is the fastest path.

## Build from source

### Prerequisites

- **Windows 10 or 11.**
- **Rust** (stable MSVC toolchain). Install via [rustup-init.exe](https://rustup.rs/) — pick "default host triple x86_64-pc-windows-msvc", "default toolchain stable", "profile minimal".
- **Visual Studio Build Tools 2022** with the *Desktop development with C++* workload and the Windows 11 SDK (22621 or newer). Easiest install: `winget install Microsoft.VisualStudio.2022.BuildTools --override "--passive --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.Windows11SDK.22621"`.
- **Node.js 20+** and **npm**.

After installing Rust, make sure `~/.cargo/bin` is on your `PATH` (`export PATH="$HOME/.cargo/bin:$PATH"` in bash).

### Build

```bash
git clone https://github.com/Gansager/pluely.git pluely-fork
cd pluely-fork
npm install
npm run tauri build
```

First clean build takes ~10 minutes (~500 Rust crates + vite frontend + bundler). Incremental Rust-only builds finish in ~2 minutes.

Outputs:

- `src-tauri/target/release/pluely.exe` — the binary
- `src-tauri/target/release/bundle/msi/*.msi` — Windows installer
- `src-tauri/target/release/bundle/nsis/*-setup.exe` — NSIS installer

### Install the freshly-built binary in place

If you already have stock Pluely installed and just want to swap the `.exe`:

```powershell
Stop-Process -Name pluely -Force -ErrorAction SilentlyContinue
Copy-Item "src-tauri\target\release\pluely.exe" "$env:LOCALAPPDATA\Pluely\pluely.exe" -Force
Start-Process "$env:LOCALAPPDATA\Pluely\pluely.exe"
```

(The first time, install via the `.msi` / `.nsis` so the `%LOCALAPPDATA%\Pluely\` folder, registry entries, and Start menu shortcut get set up.)

## Optional: `pluely-proxy` setup

If you want to route Pluely through a local Claude Code CLI proxy (so you don't burn Anthropic API credits) **and** want screenshot support via Claude Code's Read tool, set up the companion proxy:

1. Install `@anthropic-ai/claude-code` globally: `npm install -g @anthropic-ai/claude-code` and authenticate it once with `claude` interactively.
2. Place the proxy scripts somewhere local (e.g. `~/pluely-proxy/`). The proxy code is **not** in this repo — it's a private personal setup. The key file is `proxy.py` (HTTP server forwarding OpenAI-format requests to `claude -p`). Ask the maintainer if you want a copy.
3. Configure a custom AI provider in Pluely Settings pointed at `http://127.0.0.1:8765/v1/chat/completions`.

Local STT (faster than cloud) uses Whisper:

```bash
pip install -U whisper.cpp pywhispercpp  # or whatever your prefered whisper.cpp Python binding is
python whisper-server.py  # runs on http://127.0.0.1:8766
```

Then configure a custom STT provider in Pluely Settings pointed at the whisper-server.

## Keyboard shortcuts (defaults)

| Action | Shortcut |
| --- | --- |
| Manually trigger AI on the latest transcript | `Ctrl+Space` |
| Toggle conversation mode in System Audio popover | `Ctrl+K` |
| Toggle window visibility | (configured per-machine in Settings → Shortcuts) |

## Troubleshooting

- **System audio "Capture already running" error.** The fork's auto-recovery should self-heal after ~250 ms. If it doesn't, restart Pluely.
- **`Ctrl+Shift+A` doesn't work.** Some other app on the system holds that hotkey. Change the *Audio recording* shortcut in Settings → Shortcuts.
- **Screenshot is blank / Selection mode shows white screens.** Already fixed in this fork — Selection mode now uses the captured snapshot as the overlay background instead of relying on Tauri transparency. If you still see this, you're on an older build.
- **Pluely doesn't respond to system audio.** Check that Windows has the right speaker / system audio device selected and audio is actually playing. WASAPI loopback returns silence when nothing is playing.
- **Reverting to stock Pluely.** Copy any official `pluely.exe` v0.1.9 release over `%LOCALAPPDATA%\Pluely\pluely.exe`.

## License

GPL v3 (inherited from upstream — see [LICENSE](./LICENSE)).
