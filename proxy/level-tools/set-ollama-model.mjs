import { ClassicLevel } from 'classic-level';
import path from 'path';

const model = process.argv[2];
if (!model) { console.error('usage: node set-ollama-model.mjs <model>'); process.exit(2); }

const dbPath = path.join(process.env.LOCALAPPDATA,
  'com.srikanthnani.pluely', 'EBWebView', 'Default', 'Local Storage', 'leveldb');
const db = new ClassicLevel(dbPath, { keyEncoding: 'binary', valueEncoding: 'binary' });
try { await db.open(); }
catch (e) { console.error('LevelDB busy (Pluely running?):', e.message); process.exit(1); }

const dec = new TextDecoder('utf-8', { fatal: false });
const enc = s => { const b = Buffer.from(s, 'utf-8'); const o = Buffer.alloc(b.length + 1); o[0] = 0x01; b.copy(o, 1); return o; };

let key = null;
for await (const k of db.keys()) {
  if (dec.decode(k).includes('curl_selected_ai_provider')) { key = Buffer.from(k); break; }
}
if (!key) { console.error('curl_selected_ai_provider not found'); await db.close(); process.exit(1); }

const sel = { provider: 'ollama', variables: { api_key: 'ollama', model } };
await db.put(key, enc(JSON.stringify(sel)));
await db.close();
console.log('OK: selected ollama model ->', model);
