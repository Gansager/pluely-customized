import { invoke } from "@tauri-apps/api/core";
import { Button } from "@/components";
import { useCallRecorder } from "@/hooks";
import { CassetteTapeIcon, CircleIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export const CallRecorderButton = () => {
  const { isRecording, elapsedSecs, toggle } = useCallRecorder();

  const mm = Math.floor(elapsedSecs / 60).toString().padStart(2, "0");
  const ss = (elapsedSecs % 60).toString().padStart(2, "0");

  const title = isRecording
    ? `Stop recording (${mm}:${ss})  ·  middle-click opens recordings folder`
    : "Start recording  ·  middle-click opens recordings folder";

  const openFolder = async () => {
    try {
      await invoke("open_recordings_folder");
    } catch (e) {
      console.error("Failed to open recordings folder:", e);
    }
  };

  // Middle mouse button (button === 1). onAuxClick fires for any non-primary
  // button after a full press+release; preventDefault on mousedown stops the
  // browser's default autoscroll behavior on middle-click.
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
        <CassetteTapeIcon className="h-4 w-4" />
      )}
    </Button>
  );
};
