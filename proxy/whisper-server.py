#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local faster-whisper STT server, OpenAI-compatible /v1/audio/transcriptions endpoint.

Pluely sends multipart/form-data:
  file = <audio bytes>
  model = <model name>            (ignored — we use the one loaded at startup)
  language, prompt, response_format, temperature  (optional)

We return: {"text": "..."} on response_format=json (default), or plain text otherwise.
"""
import argparse, io, os, sys, tempfile, time
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn
from faster_whisper import WhisperModel

DEFAULT_PORT  = 8766
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "small")
DEFAULT_DEV   = os.environ.get("WHISPER_DEVICE", "cpu")
DEFAULT_CT    = os.environ.get("WHISPER_COMPUTE", "int8")

app = FastAPI(title="Pluely Local Whisper", version="1.0")
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

MODEL: Optional[WhisperModel] = None
MODEL_NAME = DEFAULT_MODEL

@app.get("/health")
def health():
    return {"status": "ok", "backend": "faster-whisper", "model": MODEL_NAME}

@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "faster-whisper"}]}

@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    language: str = Form(default=""),
    prompt: str = Form(default=""),
    response_format: str = Form(default="json"),
    temperature: float = Form(default=0.0),
):
    if MODEL is None:
        raise HTTPException(503, "Model not loaded")
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio")
    # faster-whisper accepts a file path or BinaryIO. Write to tmp because ffmpeg sniffs the container.
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(prefix="pluely_stt_", suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        t0 = time.time()
        kwargs = {"beam_size": 1, "temperature": temperature, "vad_filter": True}
        if language: kwargs["language"] = language
        if prompt:   kwargs["initial_prompt"] = prompt
        segments, info = MODEL.transcribe(tmp_path, **kwargs)
        text = "".join(seg.text for seg in segments).strip()
        dt = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] {len(audio_bytes)} bytes, lang={info.language} ({info.language_probability:.2f}), {dt:.2f}s -> {text[:80]}{'...' if len(text)>80 else ''}", flush=True)
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass
    if response_format in ("text", "vtt", "srt"):
        return PlainTextResponse(text)
    return JSONResponse({"text": text})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model",   default=DEFAULT_MODEL, help="tiny|base|small|medium|large-v3 (default: small)")
    ap.add_argument("--device",  default=DEFAULT_DEV,   help="cpu|cuda (default: cpu)")
    ap.add_argument("--compute", default=DEFAULT_CT,    help="int8|int8_float16|float16|float32 (default: int8)")
    ap.add_argument("--port",    type=int, default=DEFAULT_PORT)
    ap.add_argument("--host",    default="127.0.0.1")
    a = ap.parse_args()
    global MODEL, MODEL_NAME
    MODEL_NAME = a.model
    print(f"Loading faster-whisper model={a.model} device={a.device} compute={a.compute} ...", flush=True)
    t0 = time.time()
    MODEL = WhisperModel(a.model, device=a.device, compute_type=a.compute)
    print(f"Loaded in {time.time()-t0:.1f}s. Listening on http://{a.host}:{a.port}", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")

if __name__ == "__main__":
    main()
