import { useEffect } from "react";
import { useMicVAD } from "@ricky0123/vad-react";
import { useApp } from "@/contexts";
import { fetchSTT } from "@/lib";
import { floatArrayToWav } from "@/lib/utils";
import { shouldUsePluelyAPI } from "@/lib/functions/pluely.api";

interface Props {
  enabled: boolean;
  onTranscription: (text: string) => void;
}

// Patch 11: always-mounted mic VAD listener. Controlled by the headphones
// (system audio) button — when system capture is on, mic capture is on too.
// Routes [ME] transcriptions into useSystemAudio's conversation so mic and
// system audio share a single chat and a single AI flow.
const MicCaptureInternal = ({ enabled, onTranscription }: Props) => {
  const { selectedSttProvider, allSttProviders, selectedAudioDevices } =
    useApp();

  const micId = selectedAudioDevices.input.id;
  const audioConstraints: MediaTrackConstraints =
    micId && micId !== "default" ? { deviceId: { exact: micId } } : {};

  const vad = useMicVAD({
    userSpeakingThreshold: 0.6,
    startOnLoad: false,
    additionalAudioConstraints: audioConstraints,
    onSpeechEnd: async (audio) => {
      try {
        const audioBlob = floatArrayToWav(audio, 16000, "wav");
        const usePluelyAPI = await shouldUsePluelyAPI();
        if (!selectedSttProvider.provider && !usePluelyAPI) return;
        const providerConfig = allSttProviders.find(
          (p) => p.id === selectedSttProvider.provider
        );
        if (!providerConfig && !usePluelyAPI) return;
        const text = await fetchSTT({
          provider: usePluelyAPI ? undefined : providerConfig,
          selectedProvider: selectedSttProvider,
          audio: audioBlob,
        });
        if (text) onTranscription(text);
      } catch (e) {
        console.error("MicCapture STT failed:", e);
      }
    },
  });

  useEffect(() => {
    if (enabled && !vad.listening) {
      vad.start();
    } else if (!enabled && vad.listening) {
      vad.pause();
    }
  }, [enabled, vad.listening]);

  return null;
};

export const MicCapture = (props: Props) => {
  // Keying on mic device id so the VAD reinitializes if the user picks a
  // different microphone in settings.
  const { selectedAudioDevices } = useApp();
  return <MicCaptureInternal key={selectedAudioDevices.input.id} {...props} />;
};
