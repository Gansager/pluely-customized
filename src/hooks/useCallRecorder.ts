import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface RecordingStatus {
  is_recording: boolean;
  elapsed_secs: number;
  output_path: string | null;
}

function buildTimestamp(): string {
  const d = new Date();
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(
    d.getHours()
  )}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

export function useCallRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [elapsedSecs, setElapsedSecs] = useState(0);
  const [outputPath, setOutputPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  const start = useCallback(async () => {
    setError(null);
    try {
      const path = await invoke<string>("start_call_recording", {
        timestamp: buildTimestamp(),
      });
      setOutputPath(path);
      setIsRecording(true);
      setElapsedSecs(0);
    } catch (e) {
      console.error("Failed to start recording:", e);
      setError(String(e));
    }
  }, []);

  const stop = useCallback(async () => {
    try {
      await invoke<string>("stop_call_recording");
    } catch (e) {
      console.error("Failed to stop recording:", e);
      setError(String(e));
    } finally {
      setIsRecording(false);
    }
  }, []);

  const toggle = useCallback(() => {
    if (isRecording) {
      void stop();
    } else {
      void start();
    }
  }, [isRecording, start, stop]);

  // Tick a wall-clock timer once per second while recording.
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

  // On mount, re-sync with Rust state in case the UI was reloaded mid-recording.
  useEffect(() => {
    invoke<RecordingStatus>("get_recording_status")
      .then((s) => {
        setIsRecording(s.is_recording);
        setElapsedSecs(s.elapsed_secs);
        setOutputPath(s.output_path);
      })
      .catch(() => {
        /* command not yet registered or other transient — ignore */
      });
  }, []);

  return { isRecording, elapsedSecs, outputPath, error, toggle, start, stop };
}
