import { invoke } from "@tauri-apps/api/core";
import { Button } from "@/components";
import { useScreenRecorder } from "@/hooks";
import { MonitorIcon, CircleIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// Patch 14 — screen recording button. Lives right after the dictaphone
// (CallRecorderButton) in the main Card. Click toggles recording; the native
// Chromium picker asks which screen/window to capture when there's more than
// one. Middle-click opens the recordings folder (same as the dictaphone).
export const ScreenRecorderButton = () => {
  const { isRecording, elapsedSecs, toggle } = useScreenRecorder();

  const mm = Math.floor(elapsedSecs / 60)
    .toString()
    .padStart(2, "0");
  const ss = (elapsedSecs % 60).toString().padStart(2, "0");

  const title = isRecording
    ? `Stop screen recording (${mm}:${ss})  ·  middle-click opens recordings folder`
    : "Record screen (with audio)  ·  middle-click opens recordings folder";

  const openFolder = async () => {
    try {
      await invoke("open_recordings_folder");
    } catch (e) {
      console.error("Failed to open recordings folder:", e);
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button === 1) {
      e.preventDefault();
    }
  };

  const handleAuxClick = (e: React.MouseEvent) => {
    if (e.button === 1) {
      e.preventDefault();
      void openFolder();
    }
  };

  return (
    <Button
      size="icon"
      title={title}
      onClick={toggle}
      onMouseDown={handleMouseDown}
      onAuxClick={handleAuxClick}
      className={cn(isRecording && "bg-red-50 hover:bg-red-100")}
    >
      {isRecording ? (
        <CircleIcon className="text-red-500 fill-red-500 animate-pulse h-4 w-4" />
      ) : (
        <MonitorIcon className="h-4 w-4" />
      )}
    </Button>
  );
};
