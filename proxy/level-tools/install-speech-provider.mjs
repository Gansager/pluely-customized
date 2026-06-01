import { ClassicLevel } from 'classic-level';
import path from 'path';

const dbPath = path.join(process.env.LOCALAPPDATA,
  'com.srikanthnani.pluely', 'EBWebView', 'Default', 'Local Storage', 'leveldb');

const WHISPER_URL = 'http://127.0.0.1:8766/v1/audio/transcriptions';
const PROVIDER_ID = 'custom-local-whisper';
const ORIGIN_PREFIX = Buffer.concat([
  Buffer.from('_http://tauri.localhost', 'utf-8'),
  Buffer.from([0x00, 0x01]),
]);

const curlCmd = `curl -X POST "${WHISPER_URL}" \\
  -F "file=@{{AUDIO}}" \\
  -F "model=small" \\
  -F "response_format=json"`;

const newProvider = {
  id: PROVIDER_ID,
  curl: curlCmd,
  responseContentPath: 'text',
  streaming: false,
  isCustom: true,
};

const selected = { provider: PROVIDER_ID, variables: {} };

const db = new ClassicLevel(dbPath, { keyEncoding: 'binary', valueEncoding: 'binary' });
await db.open();
const dec = new TextDecoder('utf-8', { fatal: false });
const decodeVal = b => b.length && b[0]===0x01 ? dec.decode(b.subarray(1)) : dec.decode(b);
const encodeVal = s => { const body = Buffer.from(s,'utf-8'); const out = Buffer.alloc(body.length+1); out[0]=0x01; body.copy(out,1); return out; };
const makeKey = name => Buffer.concat([ORIGIN_PREFIX, Buffer.from(name, 'utf-8')]);

let providersKey=null, providersVal=null, selectedKey=null;
for await (const [k,v] of db.iterator()) {
  const ks = dec.decode(k);
  if (ks.includes('curl_custom_speech_providers'))   { providersKey = Buffer.from(k); providersVal = decodeVal(v); }
  else if (ks.includes('curl_selected_stt_provider')) { selectedKey  = Buffer.from(k); }
}

if (!providersKey) {
  providersKey = makeKey('curl_custom_speech_providers');
  providersVal = '[]';
  console.log('Ключ curl_custom_speech_providers не найден — создаю.');
}
if (!selectedKey) {
  selectedKey = makeKey('curl_selected_stt_provider');
  console.log('Ключ curl_selected_stt_provider не найден — создаю.');
}

let arr; try { arr = JSON.parse(providersVal || '[]'); if (!Array.isArray(arr)) arr=[]; } catch { arr=[]; }
const merged = arr.filter(p => p && p.id !== PROVIDER_ID).concat([newProvider]);
await db.put(providersKey, encodeVal(JSON.stringify(merged)));
await db.put(selectedKey,  encodeVal(JSON.stringify(selected)));
await db.close();
console.log('OK: speech-провайдер установлен, всего кастомных:', merged.length);
