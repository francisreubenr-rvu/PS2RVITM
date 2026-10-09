// Checks the walkthrough narration audio: every clip exists, and speech recognition (Groq Whisper) hears roughly the
// script. It cannot judge voice quality or Kannada/Hindi pronunciation: a native speaker still has to listen
// (docs/native-review.md). Similarity is the share of character pairs the transcript and the script have in common.
//   node scripts/check-tour-audio.mjs [--lang kn] [--min 0.55]
import { readFile, access } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { NARRATION } from '../src/components/tour/narration.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const min = Number(opt('--min', '0.55'));
const only = opt('--lang', null);

const env = { ...process.env };
try {
  for (const line of (await readFile(join(root, '..', '.env'), 'utf8')).split('\n')) {
    const t = line.trim();
    if (t && !t.startsWith('#') && t.includes('=')) {
      const k = t.slice(0, t.indexOf('=')).trim();
      if (!(k in env)) env[k] = t.slice(t.indexOf('=') + 1).trim().replace(/^["']|["']$/g, '');
    }
  }
} catch { /* rely on the process environment */ }
if (!env.GROQ_API_KEY) { console.error('GROQ_API_KEY is not set.'); process.exit(1); }

const norm = (s) => s.toLowerCase().normalize('NFC').replace(/[\p{P}\p{S}\s‌‍]+/gu, '');
const pairs = (s) => { const m = new Map(); for (let i = 0; i < s.length - 1; i += 1) { const p = s.slice(i, i + 2); m.set(p, (m.get(p) || 0) + 1); } return m; };
const dice = (a, b) => {
  const x = pairs(norm(a)); const y = pairs(norm(b));
  let hit = 0; let nx = 0; let ny = 0;
  for (const [p, c] of x) { nx += c; hit += Math.min(c, y.get(p) || 0); }
  for (const c of y.values()) ny += c;
  return nx + ny ? (2 * hit) / (nx + ny) : 0;
};

const rows = [];
for (const [lang, steps] of Object.entries(NARRATION)) {
  if (only && lang !== only) continue;
  for (const [step, text] of Object.entries(steps)) {
    const file = join(root, 'public', 'tour', 'audio', lang, `${step}.mp3`);
    try { await access(file); } catch { rows.push({ clip: `${lang}/${step}`, similarity: 0, note: 'MISSING FILE' }); continue; }
    const form = new FormData();
    form.append('file', new Blob([await readFile(file)], { type: 'audio/mpeg' }), `${step}.mp3`);
    form.append('model', 'whisper-large-v3');
    form.append('language', lang);
    form.append('temperature', '0');
    // Whisper on Groq allows only a few requests a minute: go one at a time and wait out a 429 using its retry-after.
    let r;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      r = await fetch('https://api.groq.com/openai/v1/audio/transcriptions', { method: 'POST', headers: { Authorization: `Bearer ${env.GROQ_API_KEY}` }, body: form });
      if (r.status !== 429) break;
      const wait = Math.min(60, Number(r.headers.get('retry-after')) || 8 * (attempt + 1));
      await new Promise((ok) => setTimeout(ok, wait * 1000));
    }
    await new Promise((ok) => setTimeout(ok, 3200));
    if (!r.ok) { rows.push({ clip: `${lang}/${step}`, similarity: 0, note: `Groq ${r.status}` }); continue; }
    const heard = ((await r.json()).text || '').trim();
    rows.push({ clip: `${lang}/${step}`, similarity: Number(dice(text, heard).toFixed(2)), heard: heard.slice(0, 70) });
  }
}
const weak = rows.filter((r) => r.similarity < min);
const byLang = {};
for (const r of rows) { const l = r.clip.split('/')[0]; (byLang[l] ||= []).push(r.similarity); }
for (const [l, v] of Object.entries(byLang)) console.log(`${l}: ${v.length} clips, mean similarity ${(v.reduce((a, b) => a + b, 0) / v.length).toFixed(2)}, lowest ${Math.min(...v).toFixed(2)}`);
console.log(weak.length ? `BELOW ${min}:\n${weak.map((w) => `  ${w.clip}  ${w.similarity}  ${w.note || w.heard}`).join('\n')}` : `all ${rows.length} clips at or above ${min}`);
