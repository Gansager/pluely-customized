import { ClassicLevel } from 'classic-level';
import path from 'path';

const dbPath = path.join(process.env.LOCALAPPDATA,
  'com.srikanthnani.pluely', 'EBWebView', 'Default', 'Local Storage', 'leveldb');

const db = new ClassicLevel(dbPath, { keyEncoding: 'binary', valueEncoding: 'binary' });
await db.open();
const dec = new TextDecoder('utf-8', { fatal: false });

let n = 0;
for await (const [k, v] of db.iterator()) {
  const ks = dec.decode(k);
  const printableKs = ks.replace(/[\x00-\x1f]/g, c => `\\x${c.charCodeAt(0).toString(16).padStart(2,'0')}`);
  const valPreview = v.length > 200 ? dec.decode(v.subarray(0, 200)) + '...' : dec.decode(v);
  const printableVal = valPreview.replace(/[\x00-\x1f]/g, c => `\\x${c.charCodeAt(0).toString(16).padStart(2,'0')}`);
  console.log(`KEY[${n}] (len=${k.length}) bytes: ${printableKs}`);
  console.log(`VAL (len=${v.length}): ${printableVal}`);
  console.log('---');
  n++;
}
console.log(`Total: ${n} keys`);
await db.close();
