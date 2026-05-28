import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Button } from "@/components";
import { FileCheckIcon, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export const SummarizeMeetingButton = () => {
  const [isRunning, setIsRunning] = useState(false);

  const run = async () => {
    if (isRunning) return;
    setIsRunning(true);
    try {
      await invoke("summarize_meeting");
    } catch (e) {
      console.error("Failed to summarize meeting:", e);
    } finally {
      // Brief visual confirmation; the actual summary runs in its own console.
      setTimeout(() => setIsRunning(false), 1200);
    }
  };

  return (
    <Button
      size="icon"
      title="End meeting & summarize  ·  runs ~/pluely-proxy/end-meeting.cmd"
      onClick={run}
      disabled={isRunning}
      className={cn(isRunning && "bg-primary/10")}
    >
      {isRunning ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <FileCheckIcon className="h-4 w-4" />
      )}
    </Button>
  );
};
