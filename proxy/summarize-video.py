#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summarize a recorded Pluely screen recording (.webm) into a markdown file.

Triggered automatically by the fork's `finish_screen_recording` (recorder.rs)
right after a screen recording is stopped + remuxed. Unlike summarize-meeting.py
(which reads the live STT transcript from pluely.db), this transcribes the audio
*from the recorded video itself* via Google Cloud STT — so it works even when the
live "listen & suggest" pipeline was off during the recording.

Pipeline:
  1. ffmpeg extracts the audio and splits it into <=55s mono 16 kHz WAV chunks
     (Google v1 sync speech:recognize maxes out around 60s / 10 MB per request).
  2. Each chunk is base64'd and sent to Google speech:recognize directly (API key
     + language config read from .env, exactly like google-stt-server.py). No
     dependency on the 8766 server being up.
  3. The joined transcript is sent to `claude -p` for a structured RU summary.
  4. The summary is written to "<video-stem>.md" NEXT TO the video, and copied
     to the clipboard.

Recorded audio is the mic + system audio MIXED into one track — there is no
speaker separation, so the prompt treats it as one undifferentiated transcript.
"""
import argparse, base64, os, subprocess, sys, shutil, datetime, tempfile, glob
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

# --- config (mirrors google-stt-server.py) ----------------------------------

def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

load_env(Path(__file__).parent / ".env")

API_KEY = os.environ.get("GOOGLE_STT_API_KEY", "").strip()
PRIMARY_LANG = os.environ.get("GOOGLE_STT_PRIMARY_LANGUAGE", "ru-RU").strip()
ALT_LANGS = [s.strip() for s in os.environ.get("GOOGLE_STT_ALT_LANGUAGES", "uk-UA,en-US").split(",") if s.strip()]
STT_MODEL = os.environ.get("GOOGLE_STT_MODEL", "latest_long").strip()
RECOGNIZE_URL = "https://speech.googleapis.com/v1/speech:recognize"

CHUNK_SECS = 55          # < Google v1 sync limit (~60s)
SAMPLE_RATE = 16000      # LINEAR16 mono — Google's canonical input
MIN_DURATION_SECS = 20   # skip tiny test recordings — don't spawn claude for them
MIN_TRANSCRIPT_CHARS = 40  # if STT yields almost nothing, don't write a stub .md

PROMPT_HEADER = """Ты — ассистент, который пишет краткий протокол ТЕХНИЧЕСКОГО созвона команды разработки. Ниже — расшифровка ЗАПИСИ звонка через STT (один смешанный аудиотрек: мой микрофон + звук системы вместе, БЕЗ разделения на говорящих — разбирайся по смыслу). Возможны опечатки и спутанные имена сервисов/тикетов.

Сделай структурированный маркдаун на языке преобладающей речи (RU/EN/DE).

## Что обсудили
- 3–8 буллетов с темами обсуждения. Если упомянуты конкретные сервисы / репы / тикеты / PR-ы — называй их прямо.

## Технические решения
- архитектурные/инженерные решения с коротким "почему" (или "Нет явных решений")
- если решение спорное и были возражения — отметь

## Action items
- "- [ ] <кто>: <что> — <дедлайн|приоритет>" (если ответственный/срок не явный — пиши "?").

## Блокеры и риски
- что мешает или может мешать (или "Нет")

## Открытые технические вопросы
- что не решили / надо вынести в отдельную сессию (или "Нет")

## Ссылки/референсы
- PR #N, тикет PROJ-123, ссылка на доку, имя сервиса в проде — всё что упоминалось как артефакт. Если ничего — пропусти секцию.

ПРАВИЛА:
- Игнорируй технический шум: фразы "раз-два-три проверка связи", тестирование звука.
- Не выдумывай имена сервисов/тикетов которых не было в расшифровке.
- Будь краток. Только маркдаун, без преамбулы.

---
РАСШИФРОВКА ЗАПИСИ:
"""


def find_ffmpeg(name: str = "ffmpeg") -> str:
    """Resolve ffmpeg/ffprobe like recorder.rs::find_ffmpeg: winget Links shim,
    then the versioned winget package dir, then bare name off PATH."""
    exe = f"{name}.exe"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Microsoft" / "WinGet"
        shim = base / "Links" / exe
        if shim.exists():
            return str(shim)
        for cand in glob.glob(str(base / "Packages" / "Gyan.FFmpeg*" / "*" / "bin" / exe)):
            return cand
    found = shutil.which(name)
    return found or name


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.run(args, capture_output=True, creationflags=creationflags)


def probe_duration(video: Path) -> float:
    """Return duration in seconds (0.0 if unknown)."""
    ffprobe = find_ffmpeg("ffprobe")
    r = run_ffmpeg([ffprobe, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(video)])
    try:
        return float((r.stdout or b"").decode("utf-8", "replace").strip())
    except (ValueError, AttributeError):
        return 0.0


def split_audio(video: Path, workdir: Path) -> list[Path]:
    """Extract audio → mono 16 kHz WAV chunks of CHUNK_SECS each."""
    ffmpeg = find_ffmpeg("ffmpeg")
    pattern = str(workdir / "chunk_%04d.wav")
    r = run_ffmpeg([
        ffmpeg, "-y", "-i", str(video),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
        "-f", "segment", "-segment_time", str(CHUNK_SECS), pattern,
    ])
    if r.returncode != 0:
        sys.exit(f"ffmpeg audio split failed (rc={r.returncode}): "
                 f"{(r.stderr or b'').decode('utf-8', 'replace')[:500]}")
    return sorted(workdir.glob("chunk_*.wav"))


def transcribe_chunk(wav: Path) -> str:
    audio_bytes = wav.read_bytes()
    config = {
        "encoding": "LINEAR16",
        "sampleRateHertz": SAMPLE_RATE,
        "languageCode": PRIMARY_LANG,
        "model": STT_MODEL,
        "enableAutomaticPunctuation": True,
    }
    alts = [l for l in ALT_LANGS if l.lower() != PRIMARY_LANG.lower()][:3]
    if alts:
        config["alternativeLanguageCodes"] = alts
    body = {"config": config, "audio": {"content": base64.b64encode(audio_bytes).decode("ascii")}}
    r = requests.post(RECOGNIZE_URL, params={"key": API_KEY}, json=body, timeout=120)
    if r.status_code != 200:
        print(f"⚠️  Google STT {r.status_code} на {wav.name}: {r.text[:300]}", file=sys.stderr)
        return ""
    parts = []
    for result in r.json().get("results", []):
        alternatives = result.get("alternatives") or []
        if alternatives:
            parts.append(alternatives[0].get("transcript", ""))
    return " ".join(p.strip() for p in parts if p).strip()


def transcribe(video: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="pluely-stt-") as td:
        workdir = Path(td)
        chunks = split_audio(video, workdir)
        if not chunks:
            return ""
        print(f"Расшифровка: {len(chunks)} кусков по ~{CHUNK_SECS}с…", flush=True)
        texts = []
        for i, wav in enumerate(chunks, 1):
            t = transcribe_chunk(wav)
            texts.append(t)
            print(f"  [{i}/{len(chunks)}] {len(t)} симв", flush=True)
        return " ".join(t for t in texts if t).strip()


def call_claude(full_prompt: str) -> str:
    claude = shutil.which("claude.cmd") or shutil.which("claude.exe") or shutil.which("claude")
    if not claude:
        sys.exit("claude CLI не найден в PATH.")
    r = subprocess.run([claude, "-p", "--output-format", "text"],
                       input=full_prompt, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300, shell=False)
    if r.returncode != 0:
        sys.exit(f"claude rc={r.returncode}: {(r.stderr or '').strip()[:500]}")
    return (r.stdout or "").strip()


def copy_to_clipboard(text: str):
    try:
        p = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-16-le"))
    except Exception as e:
        print(f"⚠️  Не смог скопировать в буфер: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Транскрибировать запись .webm и сохранить .md саммари рядом.")
    ap.add_argument("video", help="Путь к записанному .webm")
    ap.add_argument("--open", action="store_true", help="Открыть итоговый .md после сохранения.")
    ap.add_argument("--force", action="store_true", help="Не пропускать короткие записи.")
    a = ap.parse_args()

    video = Path(a.video)
    if not video.exists():
        sys.exit(f"Видео не найдено: {video}")
    if not API_KEY:
        sys.exit("GOOGLE_STT_API_KEY не задан в pluely-proxy/.env")

    dur = probe_duration(video)
    print(f"Видео: {video.name} ({dur:.0f}с)", flush=True)
    if not a.force and 0 < dur < MIN_DURATION_SECS:
        print(f"Запись короче {MIN_DURATION_SECS}с — пропускаю саммари (--force чтобы всё равно сделать).")
        return

    transcript = transcribe(video)
    if len(transcript) < MIN_TRANSCRIPT_CHARS and not a.force:
        print(f"Расшифровка слишком короткая ({len(transcript)} симв) — .md не создаю.")
        return

    print(f"Отправляю в Claude ({len(transcript):,} симв)…", flush=True)
    summary = call_claude(PROMPT_HEADER + transcript)

    out = video.with_suffix(".md")
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (f"# Запись — {video.stem}\n\n"
              f"_видео: [{video.name}]({video.name}) · длительность: {dur:.0f}с · саммари: {when}_\n\n")
    out.write_text(
        header + summary
        + "\n\n---\n\n<details><summary>Полная расшифровка</summary>\n\n```\n"
        + transcript + "\n```\n</details>\n",
        encoding="utf-8",
    )
    copy_to_clipboard(summary)
    print(f"✅ Сохранено: {out}")
    print("✅ Скопировано в буфер обмена.")
    if a.open:
        os.startfile(str(out))


if __name__ == "__main__":
    main()
