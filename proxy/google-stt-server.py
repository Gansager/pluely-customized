#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google Cloud Speech-to-Text server, OpenAI-compatible /v1/audio/transcriptions endpoint.

Pluely sends multipart/form-data:
  file = <audio bytes>      (typically audio/webm; codecs=opus from MediaRecorder)
  model = <ignored>
  language = <optional>     (overrides .env primary)
  prompt, response_format, temperature  (optional)

Internally calls Google STT v1 REST API speech:recognize with an API key.
Returns: {"text": "..."} on response_format=json (default), or plain text otherwise.
"""
import argparse, base64, os, struct, sys, time
from pathlib import Path
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn


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

DEFAULT_PORT = 8766
API_KEY = os.environ.get("GOOGLE_STT_API_KEY", "").strip()
PRIMARY_LANG = os.environ.get("GOOGLE_STT_PRIMARY_LANGUAGE", "ru-RU").strip()
ALT_LANGS = [s.strip() for s in os.environ.get("GOOGLE_STT_ALT_LANGUAGES", "uk-UA,en-US").split(",") if s.strip()]
STT_MODEL = os.environ.get("GOOGLE_STT_MODEL", "latest_long").strip()
RECOGNIZE_URL = "https://speech.googleapis.com/v1/speech:recognize"
HTTP_TIMEOUT = 30  # seconds

app = FastAPI(title="Pluely Google STT", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_log(request, call_next):
    t0 = time.time()
    cl = request.headers.get("content-length", "?")
    print(f"[{time.strftime('%H:%M:%S')}] -> {request.method} {request.url.path} (CL={cl})", flush=True)
    try:
        resp = await call_next(request)
        print(f"[{time.strftime('%H:%M:%S')}] <- {resp.status_code} {request.url.path} in {time.time()-t0:.2f}s", flush=True)
        return resp
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] !! {request.url.path} after {time.time()-t0:.2f}s: {e}", flush=True)
        raise


def detect_encoding(audio: bytes, filename: str) -> tuple[str, Optional[int]]:
    """Return (google_encoding, sample_rate_hz_or_None)."""
    ext = os.path.splitext((filename or "").lower())[1]
    head = audio[:16]
    # WAV (RIFF....WAVE) — read sample rate from fmt chunk at offset 24
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        try:
            sr = struct.unpack("<I", audio[24:28])[0]
            return ("LINEAR16", sr)
        except Exception:
            return ("LINEAR16", 16000)
    # WEBM (EBML header 0x1A 0x45 0xDF 0xA3)
    if head[:4] == b"\x1aE\xdf\xa3":
        return ("WEBM_OPUS", None)
    # OGG
    if head[:4] == b"OggS":
        return ("OGG_OPUS", None)
    # FLAC
    if head[:4] == b"fLaC":
        return ("FLAC", None)
    # MP3 (ID3 tag or MPEG frame sync 0xFFFB/0xFFF3/0xFFF2)
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return ("MP3", None)
    # Fallback to filename extension, then WEBM_OPUS
    mapping = {".webm": "WEBM_OPUS", ".ogg": "OGG_OPUS", ".oga": "OGG_OPUS",
               ".flac": "FLAC", ".mp3": "MP3", ".wav": "LINEAR16"}
    return (mapping.get(ext, "WEBM_OPUS"), None)


@app.get("/health")
def health():
    return {"status": "ok", "backend": "google-cloud-stt",
            "model": STT_MODEL, "language": PRIMARY_LANG, "alt_languages": ALT_LANGS,
            "api_key_set": bool(API_KEY)}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": STT_MODEL, "object": "model", "owned_by": "google"}]}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    language: str = Form(default=""),
    prompt: str = Form(default=""),
    response_format: str = Form(default="json"),
    temperature: float = Form(default=0.0),
):
    if not API_KEY:
        raise HTTPException(503, "GOOGLE_STT_API_KEY not set in .env")
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio")

    encoding, sample_rate = detect_encoding(audio_bytes, file.filename or "")
    primary = (language or PRIMARY_LANG).strip()

    config: dict = {
        "encoding": encoding,
        "languageCode": primary,
        "model": STT_MODEL,
        "enableAutomaticPunctuation": True,
    }
    # Only include alternatives that differ from primary; max 3 per Google docs.
    alts = [l for l in ALT_LANGS if l.lower() != primary.lower()][:3]
    if alts:
        config["alternativeLanguageCodes"] = alts
    if sample_rate:
        config["sampleRateHertz"] = sample_rate
    if prompt:
        # Use as a single phrase hint (boost=10 default). Cheap precision win on names/jargon.
        config["speechContexts"] = [{"phrases": [prompt[:500]], "boost": 10.0}]

    body = {
        "config": config,
        "audio": {"content": base64.b64encode(audio_bytes).decode("ascii")},
    }

    t0 = time.time()
    try:
        r = requests.post(RECOGNIZE_URL, params={"key": API_KEY}, json=body, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(502, f"Google STT request failed: {e}")
    dt = time.time() - t0

    if r.status_code != 200:
        # Surface Google's error verbatim — easier debugging than a wrapped message.
        msg = r.text[:500]
        print(f"[{time.strftime('%H:%M:%S')}] Google STT {r.status_code}: {msg}", flush=True)
        raise HTTPException(r.status_code, f"Google STT error: {msg}")

    data = r.json()
    parts: list[str] = []
    detected_lang = ""
    for result in data.get("results", []):
        alternatives = result.get("alternatives") or []
        if alternatives:
            parts.append(alternatives[0].get("transcript", ""))
        detected_lang = result.get("languageCode", detected_lang)
    text = " ".join(p.strip() for p in parts if p).strip()

    print(f"[{time.strftime('%H:%M:%S')}] {len(audio_bytes)} bytes, enc={encoding}"
          f"{f' sr={sample_rate}' if sample_rate else ''}, lang={detected_lang or primary}, "
          f"{dt:.2f}s -> {text[:80]}{'...' if len(text)>80 else ''}", flush=True)

    if response_format in ("text", "vtt", "srt"):
        return PlainTextResponse(text)
    return JSONResponse({"text": text})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if not API_KEY:
        print("WARNING: GOOGLE_STT_API_KEY is not set. Put it in pluely-proxy/.env", flush=True)
    print(f"Google STT server: model={STT_MODEL} lang={PRIMARY_LANG} alts={ALT_LANGS}", flush=True)
    print(f"Listening on http://{a.host}:{a.port}", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
