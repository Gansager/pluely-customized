# Memora companion proxy (`pluely-proxy`)

Companion services for Memora. None of this is required to run Memora — it's an opt-in stack that adds:

- **`proxy.py`** — OpenAI-compatible HTTP server on `127.0.0.1:8765` that forwards chat requests to the Anthropic Claude Code CLI (`claude -p`). Lets you point Memora's AI provider at a local URL and use your Claude login instead of paying per Anthropic API token. Supports streaming and screenshot attachments.
- **`google-stt-server.py`** — OpenAI-compatible STT server on `127.0.0.1:8766` that calls Google Cloud Speech-to-Text REST. Drop-in replacement for the built-in Whisper option, far better accuracy on non-English audio.
- **`whisper-server.py`** — Fallback local STT (no network, no API key) using [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper). Same `127.0.0.1:8766` endpoint.
- **`summarize-meeting.py`** — Reads Memora's SQLite chat history, isolates the current meeting (session boundary = >30 min idle gap), runs it through `claude -p` with a structured prompt, writes a Markdown summary to `~/Documents/Pluely Meetings/`, and copies it to the clipboard.
- **`summarize-video.py`** — Fired automatically when you stop a recording. Extracts the recording's audio with ffmpeg, splits it into ≤55 s chunks, transcribes each via Google STT, then runs `claude -p` to write a same-named `.md` recap next to the `.webm`/`.wav`. Skips sound-check-length clips. (`summarize-video.cmd` is the launcher the binary invokes.)
- **One-click launchers (`.cmd`)** that bring up the whole stack and start Memora.

> The launchers expect the working copy to live at `%USERPROFILE%\pluely-proxy\`. The files in this `proxy/` folder are a clean template — copy them there before running. (The `pluely-proxy` path is an internal name kept stable so existing config/recordings keep working; it is not shown anywhere in the app.)

## Install

### 1. Place the working copy

```powershell
Copy-Item -Recurse -Path .\proxy\* -Destination "$env:USERPROFILE\pluely-proxy\"
cd "$env:USERPROFILE\pluely-proxy"
Copy-Item .env.example .env
```

### 2. Python venv + dependencies (whisper-venv)

```powershell
py -3.11 -m venv whisper-venv
.\whisper-venv\Scripts\python.exe -m pip install --upgrade pip
.\whisper-venv\Scripts\python.exe -m pip install fastapi uvicorn python-multipart requests faster-whisper
```

> `faster-whisper` is only needed if you want the local Whisper fallback (`whisper-server.py`). For Google-only setups you can skip it.

### 3. Node tools for writing Memora's LevelDB

The `level-tools/` scripts configure Memora's custom AI / STT providers by writing directly to its Chromium LevelDB, skipping the UI entirely.

```powershell
cd level-tools
npm install
cd ..
```

### 4. Claude Code CLI (only if you want `proxy.py`)

```powershell
npm install -g @anthropic-ai/claude-code
claude   # one-time interactive login
```

### 5. Google STT credentials (only if you want `google-stt-server.py`)

1. Pick or create a GCP project: <https://console.cloud.google.com/>
2. Enable **Cloud Speech-to-Text API** for that project.
3. Create an **API key** under **Credentials**, then **Restrict key** → API restrictions → **Cloud Speech-to-Text API**.
4. Paste the key into `.env` as `GOOGLE_STT_API_KEY=...` and set the language codes you care about.

Pricing as of 2026: free tier covers the first 60 minutes/month per project. Standard recognition is $0.024/min. See <https://cloud.google.com/speech-to-text/pricing>.

### 6. Configure Memora's providers

Run these once. They write the Chromium LocalStorage keys Memora reads on startup. Memora should be **closed** while these run.

```powershell
node level-tools/install-provider.mjs           # AI: custom-claude-code-proxy → 127.0.0.1:8765
node level-tools/install-speech-provider.mjs    # STT: custom-local-whisper → 127.0.0.1:8766
node level-tools/install-dev-prompt.mjs         # System prompt: "Dev standup co-pilot"
```

The STT key in Memora's storage is called `custom-local-whisper` for historical reasons — it actually points at whichever server is listening on 8766, so both `google-stt-server.py` and `whisper-server.py` are interchangeable.

## Use

| Shortcut on Desktop | What it runs |
| --- | --- |
| `Memora (Claude).lnk` | `start-pluely-claude.cmd` — selects the Claude proxy AI provider, starts `proxy.py` (8765) and `google-stt-server.py` (8766) if not already up, launches Memora. |
| `Memora (Ollama).lnk` | `start-pluely-ollama.cmd` — selects the Ollama AI provider, starts `google-stt-server.py` (8766), launches Memora. (No proxy needed — Memora talks to Ollama directly on 11434.) |
| `Закончить митинг.lnk` | `end-meeting.cmd` — runs `summarize-meeting.py --open`. |

To create the shortcuts manually:

```powershell
$desktop = [Environment]::GetFolderPath('Desktop')
$wsh = New-Object -ComObject WScript.Shell
foreach ($pair in @(
    @{ name = 'Memora (Claude).lnk';      target = "$env:USERPROFILE\pluely-proxy\start-pluely-claude.cmd" },
    @{ name = 'Memora (Ollama).lnk';      target = "$env:USERPROFILE\pluely-proxy\start-pluely-ollama.cmd" },
    @{ name = 'Закончить митинг.lnk';     target = "$env:USERPROFILE\pluely-proxy\end-meeting.cmd" }
)) {
    $sc = $wsh.CreateShortcut((Join-Path $desktop $pair.name))
    $sc.TargetPath = $pair.target
    $sc.WorkingDirectory = "$env:USERPROFILE\pluely-proxy"
    $sc.Save()
}
```

## Switch STT backend (Google ↔ Whisper)

Both servers listen on port 8766 and expose the same `/v1/audio/transcriptions` endpoint. To switch, edit `start-pluely-claude.cmd` / `start-pluely-ollama.cmd` and change `start-google-stt.cmd` to `start-whisper.cmd` (or vice versa). Restart.

## Switch AI brain (Claude ↔ Ollama)

```powershell
node level-tools/select-provider.mjs claude    # or ollama
```

The Ollama target model is hard-coded in `level-tools/select-provider.mjs` (default `qwen2.5:7b-instruct`). Edit there to change.

## Ports

| Port | Service |
| --- | --- |
| 8765 | `proxy.py` — Claude Code CLI proxy |
| 8766 | `google-stt-server.py` or `whisper-server.py` |
| 11434 | Ollama (system service) |

## Files

| File | Purpose |
| --- | --- |
| `proxy.py` | Claude Code CLI HTTP proxy |
| `google-stt-server.py` | Google STT REST server |
| `whisper-server.py` | Local Whisper fallback STT server |
| `summarize-meeting.py` | End-of-meeting Markdown summary generator |
| `summarize-video.py` | Transcribe a stopped recording → same-named `.md` recap |
| `summarize-video.cmd` | Launcher Memora invokes on recording stop |
| `start-pluely-claude.cmd` | Full-stack launcher (Claude provider) |
| `start-pluely-ollama.cmd` | Full-stack launcher (Ollama provider) |
| `start-google-stt.cmd` | Standalone STT launcher (Google) |
| `start-whisper.cmd` | Standalone STT launcher (local Whisper) |
| `end-meeting.cmd` | Calls `summarize-meeting.py --open` |
| `inspect-db.py` | Debug: print `pluely.db` schema and row counts |
| `verify-prompt.py` | Debug: list `system_prompts` rows in `pluely.db` |
| `level-tools/install-provider.mjs` | Install custom Claude proxy AI provider into Memora's LevelDB |
| `level-tools/install-speech-provider.mjs` | Install custom STT provider into Memora's LevelDB |
| `level-tools/install-dev-prompt.mjs` | Install "Dev standup co-pilot" system prompt |
| `level-tools/select-provider.mjs` | Switch active AI provider (`claude` ↔ `ollama`) |
| `level-tools/dump-keys.mjs` | Debug: enumerate Memora's LevelDB keys/values |
| `.env.example` | Template — copy to `.env` and fill in your values |

> **Internal names:** the working-copy folder (`pluely-proxy`), the SQLite file (`pluely.db`), the launcher filenames, and the app's LevelDB path are intentionally left on their original identifiers so existing data and configuration keep working across the rebrand. None of them are user-visible in Memora.

## Files NOT in this repo (gitignored)

- `.env` — your real Google API key
- `whisper-venv/` — Python venv (~500 MB)
- `level-tools/node_modules/`
- `*.log` — runtime logs
- `leveldb-backup-*/` — snapshots of Memora's LevelDB before destructive writes
