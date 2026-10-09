// Generates the walkthrough narration audio with ElevenLabs, in Agnez's own voice.
//   node scripts/make-tour-audio.mjs --dry                 show what would be generated and what it costs; spends nothing
//   node scripts/make-tour-audio.mjs                       generate the clips that are missing or whose text changed
//   node scripts/make-tour-audio.mjs --force               regenerate every clip
//   node scripts/make-tour-audio.mjs --lang en --only welcome,mic    a subset
// Text comes from src/components/tour/narration.js. Audio goes to public/tour/audio/<lang>/<step>.mp3 with a manifest
// recording the text hash of each clip, so an unchanged line is never paid for twice. The API key is read from the repo's
// .env (never printed). Each clip is saved as soon as it is made, so a failure part-way can simply be re-run.
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { NARRATION } from '../src/components/tour/narration.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(root, 'public', 'tour', 'audio');
const MANIFEST = join(OUT, 'manifest.json');
const API = 'https://api.elevenlabs.io';
const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };

const readEnv = async () => {
  const env = { ...process.env };
  try {
    for (const line of (await readFile(join(root, '..', '.env'), 'utf8')).split('\n')) {
      const t = line.trim();
      if (!t || t.startsWith('#') || !t.includes('=')) continue;
      const k = t.slice(0, t.indexOf('=')).trim();
      const v = t.slice(t.indexOf('=') + 1).trim().replace(/^["']|["']$/g, '');
      if (k && !(k in env)) env[k] = v;
    }
  } catch { /* no .env: rely on the process environment */ }
  return env;
};

const exists = async (p) => { try { await access(p); return true; } catch { return false; } };
const sha = (s) => createHash('sha1').update(s).digest('hex').slice(0, 12);

const env = await readEnv();
const key = env.AGNEZ_ELEVENLABS_API_KEY || env.ELEVENLABS_API_KEY;
if (!key) { console.error('No ElevenLabs key found (AGNEZ_ELEVENLABS_API_KEY or ELEVENLABS_API_KEY in the repo .env).'); process.exit(1); }
const call = async (path, init = {}) => fetch(`${API}${path}`, { ...init, headers: { 'xi-api-key': key, ...(init.headers || {}) } });

// Agnez's voice and speech model come from the live agent, unless overridden.
const agentId = env.AGNEZ_AGENT_ID || env.ELEVENLABS_AGENT_ID;
let voiceId = env.ELEVENLABS_VOICE_ID || null;
let model = opt('--model') || env.TOUR_TTS_MODEL || null;
if ((!voiceId || !model) && agentId) {
  const r = await call(`/v1/convai/agents/${agentId}`);
  if (r.ok) {
    const tts = (await r.json()).conversation_config?.tts || {};
    voiceId = voiceId || tts.voice_id || null;
    model = model || tts.model_id || null;
  }
}
if (!voiceId) { console.error('Could not find a voice id (set ELEVENLABS_VOICE_ID or an agent id).'); process.exit(1); }

// The agent's speech model must also be a text-to-speech model; otherwise use Eleven v3, which covers Kannada and Hindi.
const models = await (await call('/v1/models')).json().catch(() => []);
const usable = (id) => Array.isArray(models) && models.some((m) => m.model_id === id && m.can_do_text_to_speech);
if (!model || !usable(model)) { console.log(`Model ${model || '(none)'} is not a text-to-speech model here; using eleven_v3.`); model = 'eleven_v3'; }

const langs = (opt('--lang') || Object.keys(NARRATION).join(',')).split(',');
const only = opt('--only') ? opt('--only').split(',') : null;
const manifest = (await exists(MANIFEST)) ? JSON.parse(await readFile(MANIFEST, 'utf8')) : { clips: {} };
const todo = [];
for (const lang of langs) {
  for (const [step, text] of Object.entries(NARRATION[lang] || {})) {
    if (only && !only.includes(step)) continue;
    const file = join(OUT, lang, `${step}.mp3`);
    const hash = sha(`${voiceId}|${model}|${text}`);
    const current = manifest.clips[`${lang}/${step}`];
    if (!flag('--force') && current?.sha === hash && (await exists(file))) continue;
    todo.push({ lang, step, text, file, hash });
  }
}

const sub = await (await call('/v1/user/subscription')).json().catch(() => ({}));
const left = (sub.character_limit ?? 0) - (sub.character_count ?? 0);
const chars = todo.reduce((n, c) => n + [...c.text].length, 0);
console.log(`voice ${voiceId} | model ${model} | plan ${sub.tier ?? '?'} | allowance left ${left} characters`);
console.log(`${todo.length} clip(s) to make, ${chars} characters${todo.length ? ` (${Math.round((chars / Math.max(left, 1)) * 100)}% of what is left)` : ''}`);
for (const c of todo) console.log(`  ${c.lang}/${c.step}  ${[...c.text].length} chars`);
if (flag('--dry') || !todo.length) process.exit(0);
if (chars > left) { console.error(`Not enough allowance left (${left}) for ${chars} characters. Use --lang or --only to do part of it.`); process.exit(1); }

let made = 0;
for (const c of todo) {
  const r = await call(`/v1/text-to-speech/${voiceId}?output_format=mp3_44100_64`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text: c.text, model_id: model }),
  });
  if (!r.ok) {
    console.error(`FAILED ${c.lang}/${c.step}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
    console.error(`${made} clip(s) were saved before this; run the script again to continue.`);
    process.exit(1);
  }
  const buf = Buffer.from(await r.arrayBuffer());
  await mkdir(dirname(c.file), { recursive: true });
  await writeFile(c.file, buf);
  manifest.clips[`${c.lang}/${c.step}`] = { sha: c.hash, chars: [...c.text].length, bytes: buf.length };
  manifest.voice_id = voiceId;
  manifest.model = model;
  await writeFile(MANIFEST, JSON.stringify(manifest, null, 1));
  made += 1;
  console.log(`made ${c.lang}/${c.step}  ${buf.length} bytes`);
}
console.log(`done: ${made} clip(s).`);
