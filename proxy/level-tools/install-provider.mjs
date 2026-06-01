import { ClassicLevel } from 'classic-level';
import path from 'path';

const dbPath = path.join(process.env.LOCALAPPDATA,
  'com.srikanthnani.pluely', 'EBWebView', 'Default', 'Local Storage', 'leveldb');

const PROXY_URL = 'http://127.0.0.1:8765/v1/chat/completions';
const PROVIDER_ID = 'custom-claude-code-proxy';
const ORIGIN_PREFIX = Buffer.concat([
  Buffer.from('_http://tauri.localhost', 'utf-8'),
  Buffer.from([0x00, 0x01]),
]);

const curlCmd = `curl -X POST "${PROXY_URL}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-code",
    "messages": [
      {"role": "user", "content": "{{TEXT}}"}
    ]
  }'`;

const newProvider = { curl: curlCmd, streaming: false,
  responseContentPath: 'choices[0].message.content',
  id: PROVIDER_ID, isCustom: true };

const selected = { provider: PROVIDER_ID,
  variables: { api_key: 'any', model: 'claude-code' } };

const db = new ClassicLevel(dbPath, { keyEncoding: 'binary', valueEncoding: 'binary' });
await db.open();
const dec = new TextDecoder('utf-8', { fatal: false });
const decodeVal = b => b.length && b[0]===0x01 ? dec.decode(b.subarray(1)) : dec.decode(b);
const encodeVal = s => { const body = Buffer.from(s,'utf-8'); const out = Buffer.alloc(body.length+1); out[0]=0x01; body.copy(out,1); return out; };
const makeKey = name => Buffer.concat([ORIGIN_PREFIX, Buffer.from(name, 'utf-8')]);

let providersKey=null, providersVal=null, selectedKey=null;
for await (const [k,v] of db.iterator()) {
  const ks = dec.decode(k);
  if (ks.includes('curl_custom_ai_providers'))      { providersKey = Buffer.from(k); providersVal = decodeVal(v); }
  else if (ks.includes('curl_selected_ai_provider')) { selectedKey  = Buffer.from(k); }
}

if (!providersKey) {
  providersKey = makeKey('curl_custom_ai_providers');
  providersVal = '[]';
  console.log('Ключ curl_custom_ai_providers не найден — создаю.');
}
if (!selectedKey) {
  selectedKey = makeKey('curl_selected_ai_provider');
  console.log('Ключ curl_selected_ai_provider не найден — создаю.');
}

let arr; try { arr = JSON.parse(providersVal || '[]'); if (!Array.isArray(arr)) arr=[]; } catch { arr=[]; }
const merged = arr.filter(p => p && p.id !== PROVIDER_ID).concat([newProvider]);
await db.put(providersKey, encodeVal(JSON.stringify(merged)));
await db.put(selectedKey,  encodeVal(JSON.stringify(selected)));
await db.close();
console.log('OK: провайдер установлен, всего кастомных:', merged.length);
