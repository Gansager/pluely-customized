#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified STT proxy — OpenAI-compatible /v1/audio/transcriptions on one port.

Keeps the SAME multipart contract the frontend already uses (it does NOT need
any change):
  POST /v1/audio/transcriptions   multipart/form-data
    file=<audio bytes>            (16 kHz mono WAV from the app's VAD)
    model, language, prompt, response_format, temperature   (optional)
  -> {"text": "..."}

Provider is chosen by env (no rebuild, just restart):
  STT_PROVIDER = groq | whisper | google      (default: groq)
  STT_FALLBACK = whisper | google | none       (default: whisper)

Resilience (root cause of the old timeouts):
  - Non-blocking: every backend runs in a ThreadPoolExecutor, the asyncio event
    loop is never blocked (the old servers did blocking requests.post /
    MODEL.transcribe inside `async def`, serialising everything under load).
  - Admission control with DROP-OLDEST: under a chunk avalanche the oldest
    waiting chunk is dropped (returns empty fast) so the freshest audio wins and
    the client never piles up retries.
  - Fast fail-over: Groq 429 / connect-timeout -> immediate local whisper (no
    retry on Groq); Groq 5xx -> one backoff retry then fallback.
  - Model warmup at startup so the first real chunk doesn't eat cold-start.
  - Per-chunk logging (size, provider, latency, queue depth, fallback reason)
    and /stats with p50/p95.

No hardcoded secrets — GROQ_API_KEY / GOOGLE_STT_API_KEY come from env / .env.
"""
import argparse, array, asyncio, base64, io, math, os, statistics, struct, sys, time, wave, collections
from concurrent.futures import ThreadPoolExecutor
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


# --------------------------------------------------------------------------- env
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


def _int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


DEFAULT_PORT = 8766
PROVIDER = os.environ.get("STT_PROVIDER", "groq").strip().lower() or "groq"
FALLBACK = os.environ.get("STT_FALLBACK", "whisper").strip().lower() or "whisper"
LANGUAGE = os.environ.get("STT_LANGUAGE", "").strip()  # "" / "auto" => let model detect

# Groq (OpenAI-compatible)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "whisper-large-v3-turbo").strip()
GROQ_URL = os.environ.get("GROQ_URL", "https://api.groq.com/openai/v1/audio/transcriptions").strip()
GROQ_CONNECT_TIMEOUT = _float("GROQ_CONNECT_TIMEOUT", 2.0)
GROQ_READ_TIMEOUT = _float("GROQ_READ_TIMEOUT", 15.0)

# Local whisper (faster-whisper). MODEL_SIZE is an alias for WHISPER_MODEL.
WHISPER_MODEL = (os.environ.get("MODEL_SIZE") or os.environ.get("WHISPER_MODEL") or "small").strip()
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu").strip()
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8").strip()

# Google v1 (kept for back-compat; not default)
GOOGLE_API_KEY = os.environ.get("GOOGLE_STT_API_KEY", "").strip()
GOOGLE_PRIMARY = os.environ.get("GOOGLE_STT_PRIMARY_LANGUAGE", "ru-RU").strip()
GOOGLE_ALTS = [s.strip() for s in os.environ.get("GOOGLE_STT_ALT_LANGUAGES", "uk-UA,en-US").split(",") if s.strip()]
GOOGLE_MODEL = os.environ.get("GOOGLE_STT_MODEL", "latest_long").strip()
GOOGLE_URL = "https://speech.googleapis.com/v1/speech:recognize"

# Resilience knobs
MAX_AUDIO_BYTES = int(_float("STT_MAX_AUDIO_MB", 25.0) * 1024 * 1024)
MIN_AUDIO_BYTES = _int("STT_MIN_AUDIO_BYTES", 1200)     # skip near-empty chunks
MIN_RMS = _float("STT_MIN_RMS", 0.004)                  # skip near-silent chunks (VAD noise)
# default concurrency: cloud groq can fan out; local CPU whisper must not
_default_conc = 4 if PROVIDER == "groq" else 1
MAX_CONCURRENCY = max(1, _int("STT_MAX_CONCURRENCY", _default_conc))
MAX_QUEUE = max(1, _int("STT_MAX_QUEUE", 6))
WARMUP = os.environ.get("STT_WARMUP", "1").strip() not in ("0", "false", "no", "")

EXECUTOR = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="stt")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------- audio helpers
def wav_rms(audio: bytes) -> Optional[float]:
    """RMS (0..1) of a PCM16 mono WAV, or None if not parseable."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            frames = w.readframes(w.getnframes())
        if not frames:
            return 0.0
        samples = array.array("h")
        samples.frombytes(frames[: len(frames) // 2 * 2])
        if not samples:
            return 0.0
        acc = 0
        for s in samples:
            acc += s * s
        return math.sqrt(acc / len(samples)) / 32768.0
    except Exception:
        return None


class SilentChunk(Exception):
    pass


class TooLarge(Exception):
    pass


def guard_audio(audio: bytes) -> None:
    if len(audio) > MAX_AUDIO_BYTES:
        raise TooLarge(f"{len(audio)} bytes > {MAX_AUDIO_BYTES}")
    if len(audio) < MIN_AUDIO_BYTES:
        raise SilentChunk(f"{len(audio)} bytes < min {MIN_AUDIO_BYTES}")
    rms = wav_rms(audio)
    if rms is not None and rms < MIN_RMS:
        raise SilentChunk(f"rms {rms:.4f} < {MIN_RMS}")


# --------------------------------------------------------------------- backends
class Transient(Exception):
    """Recoverable backend failure -> fall back to local."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _groq_once(audio: bytes, language: str, prompt: str, response_format: str) -> str:
    files = {"file": ("audio.wav", audio, "audio/wav")}
    data = {"model": GROQ_MODEL, "response_format": response_format or "json", "temperature": "0"}
    if language and language.lower() != "auto":
        data["language"] = language
    if prompt:
        data["prompt"] = prompt[:500]
    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files=files, data=data,
            timeout=(GROQ_CONNECT_TIMEOUT, GROQ_READ_TIMEOUT),
        )
    except (requests.ConnectionError, requests.Timeout) as e:
        raise Transient(f"groq net/timeout: {type(e).__name__}")
    if r.status_code == 429:
        raise Transient("groq 429 rate-limit")
    if r.status_code >= 500:
        raise Transient(f"groq {r.status_code}")
    if r.status_code != 200:
        # 4xx other than 429 (bad request etc.) — not worth a local retry on the
        # same audio loop, but degrade gracefully rather than error the user.
        raise Transient(f"groq {r.status_code}: {r.text[:200]}")
    try:
        return (r.json().get("text") or "").strip()
    except Exception:
        return (r.text or "").strip()


def groq_transcribe(audio: bytes, language: str, prompt: str, response_format: str) -> str:
    """Groq with the brief's classification: 429/timeout -> Transient (caller
    falls back immediately); 5xx -> one backoff retry, then Transient."""
    try:
        return _groq_once(audio, language, prompt, response_format)
    except Transient as e:
        if e.reason.startswith("groq 5"):
            time.sleep(0.4)
            log(f"groq 5xx retry after backoff ({e.reason})")
            return _groq_once(audio, language, prompt, response_format)  # may raise Transient again
        raise


_WHISPER_MODEL = None
_WHISPER_ERR: Optional[str] = None


def load_whisper() -> None:
    global _WHISPER_MODEL, _WHISPER_ERR
    if _WHISPER_MODEL is not None or _WHISPER_ERR is not None:
        return
    try:
        from faster_whisper import WhisperModel
        t0 = time.time()
        log(f"loading faster-whisper model={WHISPER_MODEL} device={WHISPER_DEVICE} compute={WHISPER_COMPUTE} ...")
        _WHISPER_MODEL = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
        log(f"whisper loaded in {time.time()-t0:.1f}s")
    except Exception as e:
        _WHISPER_ERR = f"{type(e).__name__}: {e}"
        log(f"WARNING: local whisper unavailable ({_WHISPER_ERR}) — fallback disabled")


def whisper_transcribe(audio: bytes, language: str, prompt: str) -> str:
    if _WHISPER_MODEL is None:
        load_whisper()
    if _WHISPER_MODEL is None:
        raise RuntimeError(f"whisper not loaded: {_WHISPER_ERR}")
    import tempfile
    with tempfile.NamedTemporaryFile(prefix="memora_stt_", suffix=".wav", delete=False) as tmp:
        tmp.write(audio)
        tmp_path = tmp.name
    try:
        kwargs = {"beam_size": 1, "vad_filter": True}
        if language and language.lower() != "auto":
            kwargs["language"] = language
        if prompt:
            kwargs["initial_prompt"] = prompt
        segments, _info = _WHISPER_MODEL.transcribe(tmp_path, **kwargs)
        return "".join(seg.text for seg in segments).strip()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def google_transcribe(audio: bytes, language: str, prompt: str) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_STT_API_KEY not set")
    # detect encoding/sample-rate (the app sends WAV/LINEAR16)
    head = audio[:16]
    enc, sr = "WEBM_OPUS", None
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        enc = "LINEAR16"
        try:
            sr = struct.unpack("<I", audio[24:28])[0]
        except Exception:
            sr = 16000
    primary = (language or GOOGLE_PRIMARY).strip() or GOOGLE_PRIMARY
    cfg = {"encoding": enc, "languageCode": primary, "model": GOOGLE_MODEL, "enableAutomaticPunctuation": True}
    alts = [l for l in GOOGLE_ALTS if l.lower() != primary.lower()][:3]
    if alts:
        cfg["alternativeLanguageCodes"] = alts
    if sr:
        cfg["sampleRateHertz"] = sr
    if prompt:
        cfg["speechContexts"] = [{"phrases": [prompt[:500]], "boost": 10.0}]
    body = {"config": cfg, "audio": {"content": base64.b64encode(audio).decode("ascii")}}
    try:
        r = requests.post(GOOGLE_URL, params={"key": GOOGLE_API_KEY}, json=body, timeout=15)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise Transient(f"google net/timeout: {type(e).__name__}")
    if r.status_code == 429:
        raise Transient("google 429")
    if r.status_code >= 500:
        raise Transient(f"google {r.status_code}")
    if r.status_code != 200:
        raise Transient(f"google {r.status_code}: {r.text[:200]}")
    parts = []
    for res in r.json().get("results", []):
        alt = (res.get("alternatives") or [])
        if alt:
            parts.append(alt[0].get("transcript", ""))
    return " ".join(p.strip() for p in parts if p).strip()


def run_primary(name: str, audio: bytes, language: str, prompt: str, response_format: str) -> str:
    if name == "groq":
        return groq_transcribe(audio, language, prompt, response_format)
    if name == "whisper":
        return whisper_transcribe(audio, language, prompt)
    if name == "google":
        return google_transcribe(audio, language, prompt)
    raise RuntimeError(f"unknown provider {name}")


# ------------------------------------------------------ admission (drop-oldest)
class Admission:
    """Bounds concurrent inference and drops the OLDEST still-waiting request
    when the queue overflows, so a live avalanche keeps the freshest chunks."""
    def __init__(self, concurrency: int, max_queue: int):
        self.sem = asyncio.Semaphore(concurrency)
        self.max_queue = max_queue
        self.waiters: "collections.OrderedDict[int, asyncio.Future]" = collections.OrderedDict()
        self.dropped = 0
        self._seq = 0

    def depth(self) -> int:
        return len(self.waiters)

    async def acquire(self) -> bool:
        """True -> caller may run (must release()). False -> dropped."""
        self._seq += 1
        seq = self._seq
        drop_fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self.waiters[seq] = drop_fut
        # evict oldest waiters beyond capacity
        while len(self.waiters) > self.max_queue:
            old_seq, old_fut = next(iter(self.waiters.items()))
            self.waiters.pop(old_seq, None)
            if not old_fut.done():
                old_fut.set_result(False)
                self.dropped += 1
        acq = asyncio.ensure_future(self.sem.acquire())
        try:
            done, _pending = await asyncio.wait({acq, drop_fut}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.waiters.pop(seq, None)
        if acq in done:
            return True  # got the slot (ignore a racing drop signal)
        # dropped before acquiring
        acq.cancel()
        try:
            await acq
            self.sem.release()  # cancel raced and it actually acquired -> give it back
        except asyncio.CancelledError:
            pass
        return False

    def release(self) -> None:
        self.sem.release()


ADMISSION: Optional[Admission] = None

# ---------------------------------------------------------------- instrumentation
_LAT = collections.deque(maxlen=300)   # (provider, latency_s)
_COUNTS = collections.Counter()        # events: ok_groq, fb_whisper, drop, silent, ...


def record(provider: str, latency: float) -> None:
    _LAT.append((provider, latency))
    _COUNTS[f"ok_{provider}"] += 1


def pctl(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 3)


# ----------------------------------------------------------------------- FastAPI
app = FastAPI(title="Memora STT", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {
        "status": "ok", "provider": PROVIDER, "fallback": FALLBACK,
        "groq_model": GROQ_MODEL, "groq_key_set": bool(GROQ_API_KEY),
        "whisper_model": WHISPER_MODEL, "whisper_loaded": _WHISPER_MODEL is not None,
        "google_key_set": bool(GOOGLE_API_KEY),
        "max_concurrency": MAX_CONCURRENCY, "max_queue": MAX_QUEUE,
    }


@app.get("/v1/models")
def list_models():
    mid = {"groq": GROQ_MODEL, "whisper": WHISPER_MODEL, "google": GOOGLE_MODEL}.get(PROVIDER, PROVIDER)
    return {"object": "list", "data": [{"id": mid, "object": "model", "owned_by": PROVIDER}]}


@app.get("/stats")
def stats():
    lat = [l for _, l in _LAT]
    by_prov = {}
    for prov in set(p for p, _ in _LAT):
        pl = [l for p, l in _LAT if p == prov]
        by_prov[prov] = {"n": len(pl), "p50": pctl(pl, 50), "p95": pctl(pl, 95)}
    return {
        "samples": len(_LAT),
        "p50": pctl(lat, 50), "p95": pctl(lat, 95),
        "by_provider": by_prov,
        "events": dict(_COUNTS),
        "dropped": ADMISSION.dropped if ADMISSION else 0,
        "queue_depth": ADMISSION.depth() if ADMISSION else 0,
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    language: str = Form(default=""),
    prompt: str = Form(default=""),
    response_format: str = Form(default="json"),
    temperature: float = Form(default=0.0),
):
    audio = await file.read()
    lang = (language or LANGUAGE).strip()

    # edge cases: empty/silent/oversized -> never error the user, just empty text
    try:
        guard_audio(audio)
    except SilentChunk as e:
        _COUNTS["silent"] += 1
        log(f"skip silent/empty chunk ({e})")
        return JSONResponse({"text": ""})
    except TooLarge as e:
        _COUNTS["too_large"] += 1
        log(f"DROP oversized chunk ({e})")
        return JSONResponse({"text": ""})

    # admission control (drop-oldest under avalanche)
    assert ADMISSION is not None
    qd = ADMISSION.depth()
    if not await ADMISSION.acquire():
        _COUNTS["drop"] += 1
        log(f"DROP chunk (queue overflow, depth={qd}, total_dropped={ADMISSION.dropped})")
        return JSONResponse({"text": ""})

    loop = asyncio.get_event_loop()
    t0 = time.time()
    try:
        # primary provider
        try:
            text = await loop.run_in_executor(
                EXECUTOR, run_primary, PROVIDER, audio, lang, prompt, response_format
            )
            dt = time.time() - t0
            record(PROVIDER, dt)
            log(f"{len(audio)}B {PROVIDER} {dt:.2f}s qd={qd} -> {text[:60]}{'...' if len(text)>60 else ''}")
        except Transient as e:
            _COUNTS[f"fallback_from_{PROVIDER}"] += 1
            log(f"FALLBACK {PROVIDER}->{FALLBACK}: {e.reason} ({time.time()-t0:.2f}s)")
            if FALLBACK == "none":
                return JSONResponse({"text": ""})
            tf = time.time()
            text = await loop.run_in_executor(
                EXECUTOR, run_primary, FALLBACK, audio, lang, prompt, response_format
            )
            dt = time.time() - tf
            record(FALLBACK, dt)
            log(f"{len(audio)}B {FALLBACK}(fb) {dt:.2f}s -> {text[:60]}{'...' if len(text)>60 else ''}")
    except Exception as e:
        _COUNTS["error"] += 1
        log(f"ERROR transcribe: {type(e).__name__}: {e}")
        # graceful: empty text rather than a 5xx the client would time-out / retry on
        return JSONResponse({"text": ""})
    finally:
        ADMISSION.release()

    if response_format in ("text", "vtt", "srt"):
        return PlainTextResponse(text)
    return JSONResponse({"text": text})


def warmup():
    """Avoid cold-start on the first real chunk."""
    if not WARMUP:
        return
    # local whisper is the safety net for every provider except google-only —
    # load it in the background so a fallback isn't a multi-second cold start.
    if PROVIDER == "whisper" or FALLBACK == "whisper":
        try:
            load_whisper()
            if _WHISPER_MODEL is not None:
                silence = _silence_wav(0.3)
                t0 = time.time()
                list(_WHISPER_MODEL.transcribe(io.BytesIO(silence), beam_size=1)[0])
                log(f"whisper warmup done in {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"whisper warmup skipped: {e}")


def _silence_wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def preflight():
    """Fail/warn at STARTUP (not on the first chunk) about misconfig."""
    global PROVIDER
    if PROVIDER not in ("groq", "whisper", "google"):
        sys.exit(f"FATAL: STT_PROVIDER='{PROVIDER}' invalid (groq|whisper|google)")
    if PROVIDER == "groq" and not GROQ_API_KEY:
        if FALLBACK == "whisper":
            log("ERROR: STT_PROVIDER=groq but GROQ_API_KEY is missing — "
                "degrading to local whisper. Set GROQ_API_KEY in proxy/.env to use Groq.")
            PROVIDER = "whisper"
        else:
            sys.exit("FATAL: STT_PROVIDER=groq but GROQ_API_KEY is not set (proxy/.env).")
    if PROVIDER == "google" and not GOOGLE_API_KEY:
        sys.exit("FATAL: STT_PROVIDER=google but GOOGLE_STT_API_KEY is not set.")


def main():
    global ADMISSION
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    preflight()
    log(f"STT provider={PROVIDER} fallback={FALLBACK} lang={LANGUAGE or 'auto'} "
        f"concurrency={MAX_CONCURRENCY} max_queue={MAX_QUEUE}")

    @app.on_event("startup")
    async def _init():
        global ADMISSION
        ADMISSION = Admission(MAX_CONCURRENCY, MAX_QUEUE)
        await asyncio.get_event_loop().run_in_executor(EXECUTOR, warmup)

    log(f"Listening on http://{a.host}:{a.port}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
