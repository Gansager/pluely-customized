import { ClassicLevel } from 'classic-level';
import Database from 'better-sqlite3';
import path from 'path';
import process from 'process';

const SYSTEM_AUDIO_PROMPT = `Ты — мой второй пилот на техническом созвоне с командой разработки. То что ты сейчас видишь — последняя реплика от коллеги (захвачено через STT с системного звука). Моя задача — быстро и по делу ответить.

ТВОЯ ЗАДАЧА:
Выдай мне готовую к произнесению реплику ОТ МОЕГО ЛИЦА — 1–3 коротких предложения, которые я прочитаю вслух как ответ коллеге. Сразу содержание, без преамбулы, без "Вот вариант:", без markdown-форматирования и эмодзи.

КОНТЕКСТ:
- Я backend/full-stack разработчик в countX, говорю с коллегами-разработчиками. Свободно использую технический жаргон, имена сервисов, тикетов, PR-ов.
- Если коллега задал технический вопрос — дай ответ или ход к ответу (если фактов нет — задай уточняющий).
- Если предложил решение — оцени критически: согласие если ок, или конкретное возражение с альтернативой.
- Если описал блокер — предложи следующий шаг или уточняющий вопрос.
- Если это standup-апдейт ("я сделал X") — коротко подтверди, спроси про следующий шаг или предложи помощь.
- Если предложили action item на меня — проговори как я его понимаю и что нужно для старта.

ФОРМАТ ВЫВОДА:
Только текст реплики. Если есть два равноценных варианта — раздели их строкой с "—". Длина: 1–2 короткие фразы, максимум ~30 слов на вариант. Язык совпадает с языком собеседника (русский / английский / немецкий — что услышал).

НЕ ДЕЛАЙ:
- Не выдумывай имена сервисов, тикетов, PR-ов, людей, которых нет в контексте — лучше уточняющий вопрос.
- Не оборачивай ответ в кавычки, не пиши "Скажи:" перед репликой.
- Не давай длинных объяснений почему именно так — мне это в эфире не пригодится.`;

const PROMPT_NAME = 'Dev standup co-pilot';

// 1. Write to LevelDB (system_audio_context)
const dbPath = path.join(process.env.LOCALAPPDATA,
  'com.srikanthnani.pluely', 'EBWebView', 'Default', 'Local Storage', 'leveldb');
const ORIGIN_PREFIX = Buffer.concat([
  Buffer.from('_http://tauri.localhost', 'utf-8'),
  Buffer.from([0x00, 0x01]),
]);
const makeKey = name => Buffer.concat([ORIGIN_PREFIX, Buffer.from(name, 'utf-8')]);
const encodeVal = s => { const body = Buffer.from(s,'utf-8'); const out = Buffer.alloc(body.length+1); out[0]=0x01; body.copy(out,1); return out; };

const db = new ClassicLevel(dbPath, { keyEncoding: 'binary', valueEncoding: 'binary' });
await db.open();
const dec = new TextDecoder('utf-8', { fatal: false });

let ctxKey = null;
for await (const k of db.keys()) {
  if (dec.decode(k).includes('system_audio_context')) { ctxKey = Buffer.from(k); break; }
}
if (!ctxKey) {
  ctxKey = makeKey('system_audio_context');
  console.log('Ключ system_audio_context не найден — создаю.');
}
await db.put(ctxKey, encodeVal(JSON.stringify(SYSTEM_AUDIO_PROMPT)));
await db.close();
console.log('OK: system_audio_context записан в LevelDB.');

// 2. Save to SQLite system_prompts as a reusable preset
const sqlitePath = path.join(process.env.APPDATA, 'com.srikanthnani.pluely', 'pluely.db');
const sdb = new Database(sqlitePath);
try {
  const now = new Date().toISOString();
  const existing = sdb.prepare("SELECT id FROM system_prompts WHERE name = ?").get(PROMPT_NAME);
  if (existing) {
    sdb.prepare("UPDATE system_prompts SET prompt = ?, updated_at = ? WHERE id = ?")
       .run(SYSTEM_AUDIO_PROMPT, now, existing.id);
    console.log(`OK: обновил пресет "${PROMPT_NAME}" (id=${existing.id}) в pluely.db.`);
  } else {
    const r = sdb.prepare("INSERT INTO system_prompts (name, prompt, created_at, updated_at) VALUES (?, ?, ?, ?)")
                 .run(PROMPT_NAME, SYSTEM_AUDIO_PROMPT, now, now);
    console.log(`OK: создал пресет "${PROMPT_NAME}" (id=${r.lastInsertRowid}) в pluely.db.`);
  }
} finally {
  sdb.close();
}
