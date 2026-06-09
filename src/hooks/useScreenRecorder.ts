import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

// Patch 14 — screen recording (video + system audio + mic) into a .webm in
// ~/Documents/Pluely Recordings/<timestamp>.webm.
//
// Capture happens entirely in the WebView2 frontend:
//   - getDisplayMedia({ video, audio }) — Chromium's native picker lets the
//     user choose WHICH screen/window to record (multi-monitor handled for us)
//     and grabs the system audio of the shared surface.
//   - getUserMedia({ audio }) — the microphone.
//   - both audio tracks are mixed into one via Web Audio, then combined with
//     the video track and fed to a single MediaRecorder.
// MediaRecorder emits .webm chunks on a timeslice; each chunk is streamed to
// Rust as raw bytes (see recorder.rs::write_screen_recording_chunk), so memory
// stays flat regardless of recording length.

function buildTimestamp(): string {
  const d = new Date();
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(
    d.getHours()
  )}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function pickMimeType(): string {
  const candidates = [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  for (const c of candidates) {
    if (
      typeof MediaRecorder !== "undefined" &&
      MediaRecorder.isTypeSupported(c)
    ) {
      return c;
    }
  }
  return "video/webm";
}

export function useScreenRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [elapsedSecs, setElapsedSecs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamsRef = useRef<MediaStream[]>([]);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const intervalRef = useRef<number | null>(null);
  // Serialize chunk writes so the final chunk (queued right before stop) is
  // fully flushed to Rust before we call finish_screen_recording.
  const writeChainRef = useRef<Promise<void>>(Promise.resolve());

  const cleanupMedia = useCallback(() => {
    streamsRef.current.forEach((s) => s.getTracks().forEach((t) => t.stop()));
    streamsRef.current = [];
    if (audioCtxRef.current) {
      void audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    recorderRef.current = null;
  }, []);

  const start = useCallback(async () => {
    setError(null);
    writeChainRef.current = Promise.resolve();
    try {
      // 1. Screen + system audio. Native picker handles the screen choice.
      //
      // WebView2 renders the getDisplayMedia picker CLIPPED to the host
      // window's bounds, and Memora's window is a 54px-tall bar — so the
      // picker tiles would be invisible. Grow the window to fill the monitor
      // for the duration of the picker, suppress the auto-resize, then restore.
      (globalThis as any).__pluelyScreenPicking = true;
      let displayStream: MediaStream;
      try {
        await invoke("set_screen_pick_overlay", { enable: true });
        // Let the OS-level window resize actually land before the picker is
        // created (set_size is async on Windows); otherwise the picker can be
        // sized to the old 54px bounds and clip again.
        await new Promise((r) => setTimeout(r, 200));
        // NOTE: the picker's "Share system audio" checkbox CANNOT be pre-checked
        // from JS — it's a deliberate Chromium privacy control that always
        // defaults to OFF (systemAudio:"include" only *offers* it, which is
        // already the default). The user must tick it manually when sharing the
        // entire screen. (Patch 18 attempt reverted 2026-06-08 — see memory.)
        displayStream = await navigator.mediaDevices.getDisplayMedia({
          video: { frameRate: 30 },
          audio: true,
        });
      } finally {
        (globalThis as any).__pluelyScreenPicking = false;
        try {
          await invoke("set_screen_pick_overlay", { enable: false });
        } catch (e) {
          console.error("Failed to restore window after picker:", e);
        }
      }
      streamsRef.current.push(displayStream);

      const videoTrack = displayStream.getVideoTracks()[0];
      if (!videoTrack) {
        throw new Error("No video track from getDisplayMedia");
      }
      // If the user stops sharing via the browser's own "Stop sharing" UI,
      // tear the recording down cleanly.
      videoTrack.addEventListener("ended", () => {
        recorderRef.current?.stop();
      });

      // 2. Microphone (best-effort — keep recording even if it's denied).
      let micStream: MediaStream | null = null;
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamsRef.current.push(micStream);
      } catch (e) {
        console.warn(
          "Screen recorder: mic unavailable, recording system audio only:",
          e
        );
      }

      // 3. Mix system audio + mic into one track via Web Audio.
      const sysAudioTracks = displayStream.getAudioTracks();
      const micAudioTracks = micStream?.getAudioTracks() ?? [];

      let combined: MediaStream;
      if (sysAudioTracks.length === 0 && micAudioTracks.length === 0) {
        combined = new MediaStream([videoTrack]);
      } else if (
        (sysAudioTracks.length > 0 ? 1 : 0) +
          (micAudioTracks.length > 0 ? 1 : 0) ===
        1
      ) {
        // Only one audio source — no mixing needed, use it directly.
        const only = sysAudioTracks[0] ?? micAudioTracks[0];
        combined = new MediaStream([videoTrack, only]);
      } else {
        const audioCtx = new AudioContext();
        audioCtxRef.current = audioCtx;
        const dest = audioCtx.createMediaStreamDestination();
        if (sysAudioTracks[0]) {
          audioCtx
            .createMediaStreamSource(new MediaStream([sysAudioTracks[0]]))
            .connect(dest);
        }
        if (micAudioTracks[0]) {
          audioCtx
            .createMediaStreamSource(new MediaStream([micAudioTracks[0]]))
            .connect(dest);
        }
        combined = new MediaStream([videoTrack, ...dest.stream.getAudioTracks()]);
      }

      // 4. MediaRecorder → stream chunks to Rust.
      const mimeType = pickMimeType();
      const rec = new MediaRecorder(combined, {
        mimeType,
        videoBitsPerSecond: 5_000_000,
      });
      recorderRef.current = rec;

      await invoke("start_screen_recording", { timestamp: buildTimestamp() });

      rec.ondataavailable = (ev) => {
        if (!ev.data || ev.data.size === 0) return;
        writeChainRef.current = writeChainRef.current
          .then(async () => {
            const buf = await ev.data.arrayBuffer();
            // Raw Uint8Array payload → Tauri delivers it as InvokeBody::Raw.
            await invoke("write_screen_recording_chunk", new Uint8Array(buf));
          })
          .catch((e) => {
            console.error("Screen recorder: chunk write failed:", e);
          });
      };

      rec.onstop = async () => {
        try {
          await writeChainRef.current;
          await invoke<string>("finish_screen_recording");
        } catch (e) {
          console.error("Screen recorder: finish failed:", e);
        } finally {
          cleanupMedia();
          setIsRecording(false);
        }
      };

      rec.start(1000); // 1s timeslice
      setIsRecording(true);
      setElapsedSecs(0);
    } catch (e) {
      // getDisplayMedia throws NotAllowedError if the user cancels the picker —
      // treat that as a silent no-op, surface anything else.
      const msg = String(e);
      if (!/NotAllowedError|Permission denied|cancell?ed/i.test(msg)) {
        console.error("Failed to start screen recording:", e);
        setError(msg);
      }
      cleanupMedia();
      setIsRecording(false);
    }
  }, [cleanupMedia]);

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") {
      rec.stop(); // onstop drains writes + calls finish + cleanup
    } else {
      cleanupMedia();
    }
    setIsRecording(false);
  }, [cleanupMedia]);

  const toggle = useCallback(() => {
    if (isRecording) {
      stop();
    } else {
      void start();
    }
  }, [isRecording, start, stop]);

  // Wall-clock timer while recording.
  useEffect(() => {
    if (!isRecording) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }
    intervalRef.current = window.setInterval(() => {
      setElapsedSecs((s) => s + 1);
    }, 1000);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRecording]);

  return { isRecording, elapsedSecs, error, toggle, start, stop };
}
