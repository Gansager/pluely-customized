<div align="center">

<img src="./docs/memora-logo.svg" alt="Memora" width="380" />

# Memora — Private Meeting Memory

**Record meetings, generate summaries with any AI model, and never lose important context again.**

_Record. Remember. Recall._

</div>

---

Memora is a **privacy-first, local-first desktop AI meeting assistant**. It records your meetings, captures screen and audio, generates transcripts and summaries, and lets you query your meeting history using **any AI model you choose** — your data stays on your machine.

> **Platform support:** Windows 10 / 11. The recorder, system-audio capture, screen capture, and proxy launcher scripts are WASAPI / Windows-specific. macOS and Linux are not supported in this build.

## Why Memora

- **🔒 Privacy-first** — recordings, transcripts, and chat history live in local SQLite + on-disk files. Nothing is sent anywhere except the AI provider *you* configure.
- **🏠 Local-first architecture** — runs fully offline with local STT + local models (Ollama / Whisper). No account, no cloud lock-in required.
- **🧠 Bring your own AI model** — Claude, OpenAI, Gemini, Ollama, local models, or any custom OpenAI-compatible endpoint. No vendor lock-in.
- **🎙️ Meeting recording** — one-click stereo dictaphone (mic + system audio) independent of the live assistant.
- **🖥️ Screen recording** — capture the screen with system audio + mic to a seekable `.webm`.
- **📝 Meeting summaries** — auto-generated Markdown summary the moment a recording stops.
- **🔎 Search across previous meetings** — every conversation is saved and queryable.

## Supported providers

| | |
| --- | --- |
| **Claude** (Anthropic) | **OpenAI** |
| **Gemini** (Google) | **Ollama** (local) |
| **Local models** | **Custom OpenAI-compatible APIs** |

## How it works

1. **Listen** — one button starts system-audio capture + microphone. Speech is transcribed locally and tagged `[ME]` / `[THEM]`.
2. **Ask** — press `Ctrl+Space` to ask your configured model about the latest transcript. The AI never auto-fires.
3. **Record** — the dictaphone and screen recorder save to `~/Documents/Pluely Recordings/`; a summary `.md` is written next to each recording on stop.
4. **Recall** — every conversation is stored locally and searchable in the Chats tab.

## Headline features

- **Unified listening button** — system audio + mic VAD in one click, with automatic `[ME]` / `[THEM]` speaker tags.
- **Independent call recorder ("dictaphone")** — stereo WAV (mic + system), separate from the STT pipeline. Middle-click the recorder icon to open the folder. Auto-summary on stop.
- **Screen recording with audio** — video + system audio + mic to a seekable `.webm`, with an auto-generated summary on stop.
- **Right-click message actions** — Explain / Translate / Answer on any message.
- **Resilient transcription** — STT requests auto-retry on transient network/provider stalls.
- **"Hide from Screen Sharing" toggle** — Memora is invisible to screen capture by default; flip it off in Settings to show it in shares.
- **Manual AI mode by default**, full conversation view, exit button + drag handle on the panel, delete-all-chats, auto-recovery from stuck capture.

## Install (pre-built binary)

1. Download the latest `*.msi` or `*-setup.exe` from the [Releases](https://github.com/Gansager/pluely-customized/releases) tab (or build locally, below).
2. Run the installer.
3. Configure an AI provider in **Settings → Dashboard** (Claude / OpenAI / Gemini / Ollama / custom).
4. Configure an STT provider — local Whisper or the bundled proxy is the fastest path.

## Build from source

### Prerequisites

- **Windows 10 or 11.**
- **Rust** (stable MSVC) via [rustup-init.exe](https://rustup.rs/) — host triple `x86_64-pc-windows-msvc`, toolchain `stable`, profile `minimal`.
- **Visual Studio Build Tools 2022** with *Desktop development with C++* + Windows 11 SDK (22621+).
- **Node.js 20+** and **npm**.

Ensure `~/.cargo/bin` is on your `PATH`.

### Build

```bash
git clone https://github.com/Gansager/pluely-customized.git memora
cd memora
npm install
npm run tauri build
```

First clean build ~10 min (~500 Rust crates + vite + bundler); incremental Rust-only builds ~2 min.

Outputs:

- `src-tauri/target/release/pluely.exe` — the binary
- `src-tauri/target/release/bundle/msi/*.msi` — Windows installer
- `src-tauri/target/release/bundle/nsis/*-setup.exe` — NSIS installer

> **Note on internal names:** the build still produces `pluely.exe` and installs to `%LOCALAPPDATA%\Pluely\`. These internal identifiers are intentionally preserved so existing meeting history and configuration (stored under that path) are not lost on upgrade. They are never shown in the UI.

### Swap a freshly-built binary in place

```powershell
Stop-Process -Name pluely -Force -ErrorAction SilentlyContinue
Copy-Item "src-tauri\target\release\pluely.exe" "$env:LOCALAPPDATA\Pluely\pluely.exe" -Force
Start-Process "$env:LOCALAPPDATA\Pluely\pluely.exe"
```

## Optional: companion proxy stack

A local proxy stack lives under [`proxy/`](./proxy/):

- **Claude Code CLI proxy** (`proxy.py`, port 8765) — route AI calls through your local `claude` CLI login.
- **Google Cloud Speech-to-Text server** (`google-stt-server.py`, port 8766) — high-accuracy RU/UK/EN STT, ~1–2 s latency.
- **Local Whisper fallback** (`whisper-server.py`, port 8766) — offline, no API key.
- **Meeting / recording summarizers** (`summarize-meeting.py`, `summarize-video.py`) — Markdown summaries via `claude -p`.
- **One-click launchers** that bring up the whole stack and start Memora.

See [`proxy/README.md`](./proxy/README.md).

## Keyboard shortcuts (defaults)

| Action | Shortcut |
| --- | --- |
| Ask the AI about the latest transcript | `Ctrl+Space` |
| Toggle conversation mode in the popover | `Ctrl+K` |
| Toggle window visibility | (set per-machine in Settings → Shortcuts) |

## Built on

Memora is built on top of [iamsrikanthnani/pluely](https://github.com/iamsrikanthnani/pluely) (GPL-3.0). The original upstream README is preserved at [`README-upstream.md`](./README-upstream.md). All Memora-specific changes are documented in the commit history on `master`.

## License

GPL v3 — see [LICENSE](./LICENSE).
