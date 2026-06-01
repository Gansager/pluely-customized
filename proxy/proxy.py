#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pluely -> Claude Code Brain Proxy (Windows-friendly)

Supports both non-streaming and OpenAI-compatible streaming (SSE) responses.
When the client sends `stream: true`, the proxy runs `claude -p` with
`--output-format stream-json --include-partial-messages` and forwards the
text deltas as OpenAI SSE chunks, so Pluely shows tokens as they arrive.
"""

import argparse, base64, hashlib, json, os, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_PORT = 8765
MAX_FILE_CHARS = 3000
MAX_FILES = 20
MAX_CONTEXT_CHARS = 80000

# Pluely sends screenshots as Anthropic-style {type:"image", source:{type:"base64", ...}}
# content blocks inside chat.completions requests. Claude Code CLI doesn't accept
# images via stdin, but it CAN read PNG files via its Read tool. So we save each
# image to a temp file and append a hint to the prompt telling claude to Read it.
TEMP_IMAGE_DIR = Path(tempfile.gettempdir()) / "pluely-images"
TEMP_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

def _save_image_block(block):
    """Save one image content block to TEMP_IMAGE_DIR as PNG/JPG. Returns abs path or None."""
    if not isinstance(block, dict):
        return None
    src = block.get("source") or {}
    if src.get("type") != "base64":
        return None
    data = src.get("data") or ""
    media_type = (src.get("media_type") or "image/png").lower()
    ext = ".png" if "png" in media_type else (".jpg" if "jpeg" in media_type or "jpg" in media_type else ".bin")
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None
    digest = hashlib.sha1(raw).hexdigest()[:10]
    path = TEMP_IMAGE_DIR / f"pluely_{int(time.time())}_{digest}{ext}"
    try:
        path.write_bytes(raw)
    except Exception:
        return None
    return str(path).replace("\\", "/")

def _content_to_text_and_images(content):
    """Accepts string or list of Anthropic-style blocks. Returns (text, [image_paths])."""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content), []
    text_parts = []
    image_paths = []
    for block in content:
        if not isinstance(block, dict):
            text_parts.append(str(block))
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text") or "")
        elif btype == "image":
            p = _save_image_block(block)
            if p:
                image_paths.append(p)
    return "\n".join(t for t in text_parts if t), image_paths

CODE_EXTENSIONS = {".py",".js",".ts",".tsx",".jsx",".go",".rs",".java",".cpp",".c",".h",".cs",
                   ".rb",".php",".swift",".kt",".md",".txt",".yaml",".yml",".toml",".json",
                   ".env.example",".sh",".bash",".sql"}
IGNORE_DIRS = {"node_modules",".git","__pycache__",".venv","venv","dist","build",".next",
               ".nuxt","coverage",".pytest_cache","target","vendor"}

def find_claude():
    for name in ("claude.cmd","claude.exe","claude"):
        p = shutil.which(name)
        if p: return p
    return None
CLAUDE_BIN = find_claude()

def read_claude_md(p: Path):
    for n in ["CLAUDE.md","claude.md",".claude.md"]:
        f = p / n
        if f.exists(): return f.read_text(encoding="utf-8", errors="ignore")
    return None

def collect_files(p: Path):
    files, total = [], 0
    for root, dirs, names in os.walk(p):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        for n in sorted(names):
            if len(files) >= MAX_FILES: break
            ext = Path(n).suffix.lower()
            if ext not in CODE_EXTENSIONS: continue
            full = Path(root) / n
            rel = str(full.relative_to(p))
            try:
                c = full.read_text(encoding="utf-8", errors="ignore")
                if len(c) > MAX_FILE_CHARS: c = c[:MAX_FILE_CHARS] + "\n... [обрезано]"
                total += len(c)
                if total > MAX_CONTEXT_CHARS: break
                files.append((rel, c))
            except Exception: continue
    return files

def build_context(project: Optional[str]):
    if not project: return ""
    p = Path(project).expanduser().resolve()
    if not p.exists(): return f"[Проект не найден: {project}]\n\n"
    parts = ["=== КОНТЕКСТ ПРОЕКТА ===", f"Проект: {p.name} ({p})", ""]
    md = read_claude_md(p)
    if md:
        parts += ["--- CLAUDE.md ---", md[:8000], ""]
    files = collect_files(p)
    if files:
        parts.append(f"--- ФАЙЛЫ ПРОЕКТА ({len(files)}) ---")
        for rel, c in files:
            parts += [f"\n// {rel}", c]
    parts += ["\n=== КОНЕЦ КОНТЕКСТА ===\n",
              "Ты — ИИ-ассистент разработчика на техническом митинге. Отвечай коротко и по делу.\n\n"]
    return "\n".join(parts)


def _build_claude_cmd(project, model, streaming, has_images=False):
    """Return (cmd, cwd) for the claude subprocess."""
    cwd = None
    if streaming:
        cmd = [CLAUDE_BIN, "-p", "--output-format", "stream-json",
               "--include-partial-messages", "--verbose", "--model", model]
    else:
        cmd = [CLAUDE_BIN, "-p", "--output-format", "text", "--model", model]
    if project:
        p = Path(project).expanduser().resolve()
        if p.exists():
            cwd = str(p)
            cmd.append("--dangerously-skip-permissions")
    # When the user attached images we need claude to be able to Read files
    # outside the project (the temp dir) without a permission prompt — Pluely
    # has no way to answer that prompt interactively. Add the flag if missing.
    if has_images and "--dangerously-skip-permissions" not in cmd:
        cmd.append("--dangerously-skip-permissions")
    return cmd, cwd


def ask_claude(prompt, ctx, project, model="haiku", has_images=False):
    """Non-streaming path — single text response."""
    if not CLAUDE_BIN:
        return "❌ claude не найден. Установи: npm install -g @anthropic-ai/claude-code"
    cmd, cwd = _build_claude_cmd(project, model, streaming=False, has_images=has_images)
    full = ctx + prompt
    try:
        r = subprocess.run(cmd, input=full, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120, cwd=cwd, shell=False)
        if r.returncode != 0:
            return f"❌ claude rc={r.returncode}: {(r.stderr or '').strip()[:500]}"
        return (r.stdout or "").strip() or "(пустой ответ)"
    except subprocess.TimeoutExpired:
        return "⏱ Таймаут 120с."
    except Exception as e:
        return f"❌ Ошибка: {e}"


def stream_claude(prompt, ctx, project, model="haiku", has_images=False):
    """Streaming path — yields OpenAI-compatible SSE chunks for `stream: true` clients.

    Spawns `claude -p --output-format stream-json --include-partial-messages` and
    converts text_delta events into `data: {...}\\n\\n` chunks. Skips
    thinking/signature/tool deltas so only user-visible text reaches Pluely.
    """
    request_id = f"proxy-{int(time.time())}"

    def sse_chunk(content=None, finish=None):
        delta = {"content": content} if content is not None else {}
        payload = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "claude-code",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    if not CLAUDE_BIN:
        yield sse_chunk("❌ claude не найден. npm install -g @anthropic-ai/claude-code")
        yield sse_chunk(finish="stop")
        yield "data: [DONE]\n\n"
        return

    cmd, cwd = _build_claude_cmd(project, model, streaming=True, has_images=has_images)
    full = ctx + prompt

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", cwd=cwd, shell=False, bufsize=1,
        )
    except Exception as e:
        yield sse_chunk(f"❌ Popen failed: {e}")
        yield sse_chunk(finish="stop")
        yield "data: [DONE]\n\n"
        return

    # Pipe deadlock fix: write the (potentially 90KB+) prompt in a separate
    # thread so the main thread can start draining stdout immediately. Without
    # this, claude blocks writing stream-json events to a full stdout pipe
    # while we block writing the prompt to a full stdin pipe.
    stdin_err = {}
    def _write_stdin():
        try:
            proc.stdin.write(full)
            proc.stdin.flush()
            proc.stdin.close()
        except Exception as ex:
            stdin_err["e"] = ex
    threading.Thread(target=_write_stdin, daemon=True).start()

    emitted_any = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Only forward visible text deltas; ignore thinking/signature/tool events.
            if ev.get("type") != "stream_event":
                continue
            inner = ev.get("event") or {}
            if inner.get("type") != "content_block_delta":
                continue
            d = inner.get("delta") or {}
            if d.get("type") != "text_delta":
                continue
            text = d.get("text") or ""
            if not text:
                continue
            emitted_any = True
            yield sse_chunk(text)
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    if not emitted_any:
        try:
            err = (proc.stderr.read() or "").strip() if proc.stderr else ""
        except Exception:
            err = ""
        yield sse_chunk(f"(пустой ответ; rc={proc.returncode}; stderr={err[:300]})")

    yield sse_chunk(finish="stop")
    yield "data: [DONE]\n\n"


class Handler(BaseHTTPRequestHandler):
    context_prefix = ""
    project_path = None
    model = "haiku"
    def log_message(self, fmt, *a): print(f"[{time.strftime('%H:%M:%S')}] {fmt % a}")
    def _json(self, code, data):
        b = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
    def do_GET(self):
        if self.path == "/health": self._json(200, {"status":"ok","backend":"claude-code"})
        elif self.path in ("/v1/models","/models"):
            self._json(200, {"object":"list","data":[{"id":"claude-code","object":"model","created":0,"owned_by":"claude-code"}]})
        else: self._json(404, {"error":"not found"})
    def do_POST(self):
        if self.path not in ("/v1/chat/completions","/chat/completions"):
            self._json(404, {"error":"not found"}); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
        except Exception as e:
            self._json(400, {"error": str(e)}); return
        msgs = [m for m in body.get("messages", []) if m.get("role") != "system"]
        if not msgs: self._json(400, {"error":"no messages"}); return
        hist = []
        for m in msgs[:-1]:
            txt, _ = _content_to_text_and_images(m.get("content", ""))
            hist.append(f"{'Пользователь' if m['role']=='user' else 'Ассистент'}: {txt}")
        last_text, last_images = _content_to_text_and_images(msgs[-1].get("content", ""))
        if last_images:
            # Tell claude to Read each PNG. Without this hint claude treats the
            # path as just text and won't open the image.
            paths_block = "\n".join(f"- {p}" for p in last_images)
            image_hint = (
                f"\n\n[К сообщению прикреплены скриншоты. Открой каждый файл через Read tool "
                f"и проанализируй содержимое, затем ответь на вопрос пользователя. "
                f"Не пиши о том, что используешь Read — сразу отвечай по сути.]\n"
                f"Файлы:\n{paths_block}"
            )
            last_text = (last_text or "Опиши, что на скриншоте.") + image_hint
        prompt = (f"История беседы:\n{chr(10).join(hist)}\n\nВопрос: {last_text}") if hist else last_text
        is_streaming = bool(body.get("stream", False))
        mode_tag = "stream" if is_streaming else "buffered"
        if last_images:
            print(f"  → [{mode_tag}] +{len(last_images)} screenshot(s) attached")
        print(f"  → [{mode_tag}] {prompt[:120]}{'...' if len(prompt)>120 else ''}")

        if is_streaming:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                for chunk in stream_claude(prompt, self.context_prefix, self.project_path, self.model, has_images=bool(last_images)):
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                print(f"  ← [stream] done")
            except (BrokenPipeError, ConnectionResetError):
                print(f"  ← [stream] client disconnected")
            return

        ans = ask_claude(prompt, self.context_prefix, self.project_path, self.model, has_images=bool(last_images))
        print(f"  ← {ans[:120]}{'...' if len(ans)>120 else ''}")
        self._json(200, {
            "id": f"proxy-{int(time.time())}", "object":"chat.completion",
            "created": int(time.time()), "model":"claude-code",
            "choices":[{"index":0,"message":{"role":"assistant","content":ans},"finish_reason":"stop"}],
        })

def _watch_parent(pid):
    """Exit this server when the parent (Pluely) process dies, however it dies."""
    if not pid:
        return
    def _w():
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if h:
                ctypes.windll.kernel32.WaitForSingleObject(h, 0xFFFFFFFF)
            os._exit(0)
        except Exception:
            pass
    threading.Thread(target=_w, daemon=True).start()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project","-p", default=None)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--model", default="haiku", help="claude model alias: haiku, sonnet, opus (default: haiku)")
    ap.add_argument("--parent-pid", type=int, default=0, help="exit when this PID (the app) dies")
    a = ap.parse_args()
    _watch_parent(a.parent_pid)
    if not CLAUDE_BIN:
        print("❌ claude не найден. npm install -g @anthropic-ai/claude-code"); sys.exit(1)
    print(f"✅ claude: {CLAUDE_BIN}")
    ctx = build_context(a.project)
    if a.project:
        p = Path(a.project).expanduser().resolve()
        if p.exists():
            print(f"✅ Проект: {p.name} | файлов: {len(collect_files(p))} | контекст: ~{len(ctx):,} симв.")
        else:
            print(f"⚠️  Папка проекта не существует: {p}")
    Handler.context_prefix = ctx
    Handler.project_path = a.project
    Handler.model = a.model
    srv = HTTPServer(("127.0.0.1", a.port), Handler)
    print(f"✅ model: {a.model}")
    print(f"✅ streaming: enabled (Pluely uses stream:true)")
    print(f"\n🚀 http://127.0.0.1:{a.port}  (Ctrl+C — стоп)\n")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\n👋 Остановлен")

if __name__ == "__main__":
    main()
