import { ClassicLevel } from 'classic-level';
import path from 'path';

const arg = (process.argv[2] || '').toLowerCase();

// ВАЖНО: подставь сюда ТОЧНОЕ имя модели Ollama из `ollama list` на этой машине.
// На этой машине iGPU (AMD Radeon 680M) + Ryzen 7 7735HS + 32GB RAM — берём 7B.
const OLLAMA_MODEL = 'minicpm-v';

const PRESETS = {
  claude: { provider: 'custom-claude-code-proxy', variables: { api_key: 'any',    model: 'claude-code' } },
  ollama: { provider: 'ollama',                   variables: { api_key: 'ollama', model: OLLAMA_MODEL } },
};

if (!PRESETS[arg]) { console.error(`Usage: node select-provider.mjs <${Object.keys(PRESETS).join('|')}>`); process.exit(2); }

const dbPath = path.join(process.env.LOCALAPPDATA,
  'com.srikanthnani.pluely', 'EBWebView', 'Default', 'Local Storage', 'leveldb');
const db = new ClassicLevel(dbPath, { keyEncoding: 'binary', valueEncoding: 'binary' });
try { await db.open(); }
catch (e) { console.error('LevelDB занят (Pluely запущен?):', e.message); process.exit(1); }

const dec = new TextDecoder('utf-8', { fatal: false });
const encodeVal = s => { const body = Buffer.from(s,'utf-8'); const out = Buffer.alloc(body.length+1); out[0]=0x01; body.copy(out,1); return out; };

let selectedKey = null;
for await (const k of db.keys()) {
  if (dec.decode(k).includes('curl_selected_ai_provider')) { selectedKey = Buffer.from(k); break; }
}
if (!selectedKey) { console.error('Ключ curl_selected_ai_provider не найден'); await db.close(); process.exit(1); }
await db.put(selectedKey, encodeVal(JSON.stringify(PRESETS[arg])));
await db.close();
console.log(`OK: provider -> ${arg}`);
