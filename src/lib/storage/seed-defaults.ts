import { DIST, DistMode, STORAGE_KEYS } from "@/config";
import { safeLocalStorage } from "./helper";
import { invoke } from "@tauri-apps/api/core";

// One-time self-configuration for a fresh install. Mirrors what the external
// level-tools/*.mjs scripts used to write into Pluely's LevelDB, but baked into
// the app so a clean install is already pointed at the bundled proxy (8765) and
// local STT server (8766) — no manual setup.

const SEED_FLAG = "dist_providers_seeded";
const INSTALL_MODE_KEY = "dist_install_mode";

const CLAUDE_PROXY_AI_PROVIDER = {
  id: "custom-claude-code-proxy",
  curl: `curl -X POST "${DIST.AI_PROXY_URL}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-code",
    "messages": [
      {"role": "user", "content": "{{TEXT}}"}
    ]
  }'`,
  responseContentPath: "choices[0].message.content",
  streaming: false,
  isCustom: true,
};

const LOCAL_WHISPER_STT_PROVIDER = {
  id: "custom-local-whisper",
  curl: `curl -X POST "${DIST.STT_URL}" \\
  -F "file=@{{AUDIO}}" \\
  -F "model=small" \\
  -F "response_format=json"`,
  responseContentPath: "text",
  streaming: false,
  isCustom: true,
};

const selectedAiFor = (mode: DistMode) =>
  mode === "claude"
    ? {
        provider: "custom-claude-code-proxy",
        variables: { api_key: "any", model: "claude-code" },
      }
    : {
        provider: "ollama",
        variables: { api_key: "ollama", model: DIST.OLLAMA_MODEL },
      };

// Guarded writer — seeds providers for the given brain. Safe to call repeatedly.
export function seedProvidersWithMode(mode: DistMode): void {
  if (typeof window === "undefined") return;
  if (safeLocalStorage.getItem(SEED_FLAG)) return;

  if (!safeLocalStorage.getItem(STORAGE_KEYS.CUSTOM_AI_PROVIDERS)) {
    safeLocalStorage.setItem(
      STORAGE_KEYS.CUSTOM_AI_PROVIDERS,
      JSON.stringify([CLAUDE_PROXY_AI_PROVIDER])
    );
  }
  if (!safeLocalStorage.getItem(STORAGE_KEYS.SELECTED_AI_PROVIDER)) {
    safeLocalStorage.setItem(
      STORAGE_KEYS.SELECTED_AI_PROVIDER,
      JSON.stringify(selectedAiFor(mode))
    );
  }

  if (!safeLocalStorage.getItem(STORAGE_KEYS.CUSTOM_SPEECH_PROVIDERS)) {
    safeLocalStorage.setItem(
      STORAGE_KEYS.CUSTOM_SPEECH_PROVIDERS,
      JSON.stringify([LOCAL_WHISPER_STT_PROVIDER])
    );
  }
  if (!safeLocalStorage.getItem(STORAGE_KEYS.SELECTED_STT_PROVIDER)) {
    safeLocalStorage.setItem(
      STORAGE_KEYS.SELECTED_STT_PROVIDER,
      JSON.stringify({ provider: "custom-local-whisper", variables: {} })
    );
  }

  safeLocalStorage.setItem(SEED_FLAG, "1");
}

// Resolve the install brain, then seed. Mode precedence:
//   1. localStorage "dist_install_mode" (if a prior run cached it)
//   2. the native get_dist_install_mode command (reads installer's dist-mode.txt)
//   3. the compile-time default (DIST.DEFAULT_MODE)
// Await this before the first loadData() so providers exist when read.
export async function ensureDefaultsSeeded(): Promise<void> {
  if (typeof window === "undefined") return;
  if (safeLocalStorage.getItem(SEED_FLAG)) return;

  const isMode = (m: any): m is DistMode => m === "claude" || m === "ollama";

  let mode: DistMode | null = null;
  const cached = safeLocalStorage.getItem(INSTALL_MODE_KEY);
  if (isMode(cached)) {
    mode = cached;
  } else {
    try {
      const native = await invoke<string>("get_dist_install_mode");
      if (isMode(native)) {
        mode = native;
        safeLocalStorage.setItem(INSTALL_MODE_KEY, native);
      }
    } catch {
      // Non-Tauri / command unavailable — fall back to the default.
    }
  }

  seedProvidersWithMode(mode ?? DIST.DEFAULT_MODE);
}
