import { useCallback, useEffect, useRef, useState } from 'react';
import { answerQuestion, applyChange, finishInterview, getBoard, getSession, proposeChange, startInterview, editAnswer } from '../../campaign/lib/api';
import { channelLabel, langName, prettyText } from '../../campaign/lib/format';
import { go, useCurrent } from '../../campaign/lib/current';
import { navigate } from '../../lib/router';
import { looksLikeQuestion, understand } from './intent';
import { getStrings } from './strings';
import { useTalkVoice } from './voiceIO';

// One conversation for everything spoken in the app: starting a campaign, changing one, opening a screen. One live call with the
// ElevenLabs agent (Agnez) carries the voice: she asks every line and hears every answer, the microphone stays open, and the
// person can interrupt her at any point. GrowIt is the source of truth: it hands Agnez each line, records what the person says
// into the interview, and nothing is changed without a spoken or tapped yes. A typed fallback always works.

const INTENT_KEY = 'talk-intent'; // set by buttons elsewhere ("Tell me what to change") before they open Talk
const LOCALISED = ['en', 'hi', 'kn']; // the interview asks in these; other languages are asked in English

const readBool = (key, fallback) => { try { const v = localStorage.getItem(key); return v === null ? fallback : v === '1'; } catch { return fallback; } };
const writeBool = (key, v) => { try { localStorage.setItem(key, v ? '1' : '0'); } catch { /* storage blocked: holds for this visit */ } };
const readLang = () => { try { return localStorage.getItem('talk-lang') || 'en'; } catch { return 'en'; } };

let nextId = 1;
const msg = (role, text, extra = {}) => ({ id: nextId++, role, text, ...extra });
const hasDetail = (text) => /\d/.test(text) || text.trim().split(/\s+/).length >= 4;

export function useTalk({ sessionId, user }) {
  const cur = useCurrent();
  const [lang, setLangState] = useState(readLang);
  const [handsFree, setHandsFreeState] = useState(true); // Talk is always hands-free: the call stays open and the microphone stays live
  const [voiceOn, setVoiceOnState] = useState(() => readBool('talk-voice', true));
  const [started, setStarted] = useState(false);
  const [paused, setPaused] = useState(false);
  const [ended, setEnded] = useState(false); // the person ended the call: lines stay on screen but are not spoken until they reconnect
  const [messages, setMessages] = useState([]);
  const [session, setSession] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [assets, setAssets] = useState([]);
  const [mode, setMode] = useState('home'); // home | interview | change | confirm
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [lastHeard, setLastHeard] = useState('');

  // The conversation outlives renders, so everything async reads the latest values from here.
  const live = useRef({});
  live.current = { lang, handsFree, voiceOn, mode, session, proposal, cur, started, ended };
  const asked = useRef('');
  const owned = useRef(''); // the session this conversation started itself, so the address change does not re-open it
  const onHeardRef = useRef(null); // the current onHeard, so the voice call always calls the latest
  const replyRef = useRef(null); // set while a free-form question is waiting for Agnez's spoken answer, so it is shown too
  const agnez = useTalkVoice({
    onFinal: (text) => onHeardRef.current?.(text, 'voice'),
    onAgent: (text) => { const show = replyRef.current; if (show) { replyRef.current = null; show(text); } },
  });

  const push = useCallback((m) => setMessages((all) => [...all, m]), []);
  const effLang = () => (live.current.session?.lang || live.current.lang);

  // Make sure the voice call is open before a line is handed to Agnez. Safe to call repeatedly.
  const ensureLive = useCallback(async () => {
    if (agnez.status === 'live') return true;
    if (agnez.status === 'connecting') return true;
    return agnez.start(live.current.lang);
  }, [agnez]);

  // Say a line: show it, hand it to Agnez to speak. The microphone is already open, so there is nothing to start listening for:
  // the person can answer, or interrupt Agnez, the moment she begins.
  const say = useCallback(async (text, { extra } = {}) => {
    push(msg('ai', text, extra));
    if (!live.current.voiceOn || live.current.ended) return true;
    await ensureLive();
    await agnez.say(text);
    return true;
  }, [push, agnez, ensureLive]);

  const strings = () => getStrings(live.current.lang);
  const sayT = useCallback((key, ...args) => {
    const { t, lang: l } = getStrings(live.current.lang);
    const v = t[key];
    return say(typeof v === 'function' ? v(...args) : v, { spoken: l });
  }, [say]);

  // ---------------- interview
  const ask = useCallback(async (s, resumed = false) => {
    const q = s.question;
    setSession(s);
    if (!q || s.status === 'complete') {
      setMode('interview');
      asked.current = 'done';
      await say(getStrings(s.lang).t.allAnswered, { spoken: getStrings(s.lang).lang, extra: { kind: 'done' } });
      return;
    }
    setMode('interview');
    const key = `${q.id}|${s.clarify?.reason ?? ''}`;
    if (asked.current === key && !resumed) return;
    asked.current = key;
    const { t } = getStrings(s.lang);
    const options = q.options?.length ? q.options.map((o) => o.label) : [];
    let text = `${s.clarify ? `${s.clarify.reason} ` : ''}${q.prompt}`;
    if (options.length) text += ` ${t.optionsRead(options.join(', '))}`;
    await say(text, { spoken: LOCALISED.includes(s.lang) ? s.lang : 'en', extra: { kind: 'question' } });
  }, [say]);

  const startNew = useCallback(async () => {
    setBusy(true);
    try {
      const l = live.current.lang;
      await say(getStrings(l).t.newStart, { spoken: getStrings(l).lang, listen: false });
      const s = await startInterview(l);
      owned.current = s.id;
      window.history.replaceState(null, '', `#/voice/${encodeURIComponent(s.id)}`); // a refresh resumes this session; no remount, so the conversation stays on screen
      asked.current = '';
      await ask(await getSession(s.id));
    } catch (e) {
      await say(getStrings(live.current.lang).t.error(e.message), { spoken: 'en', listen: false });
    } finally {
      setBusy(false);
    }
  }, [say, ask]);

  const sendAnswer = useCallback(async (body, echo) => {
    const s = live.current.session;
    if (!s || busy) return;
    if (echo) push(msg('user', echo, { source: body.source }));
    setBusy(true);
    try {
      await ask(await answerQuestion(s.id, body));
    } catch (e) {
      await say(getStrings(s.lang).t.error(e.message), { spoken: 'en', listen: false });
    } finally {
      setBusy(false);
    }
  }, [ask, say, push, busy]);

  const editHeard = useCallback(async (aid, body) => {
    const s = live.current.session;
    if (!s) return;
    setBusy(true);
    try { setSession(await editAnswer(s.id, aid, body)); } catch (e) { push(msg('system', e.message)); } finally { setBusy(false); }
  }, [push]);

  const buildPlan = useCallback(async () => {
    const s = live.current.session;
    if (!s) return;
    setBusy(true);
    await say(getStrings(s.lang).t.building, { spoken: getStrings(s.lang).lang, listen: false });
    try {
      const { campaign_id } = await finishInterview(s.id);
      go({ name: 'plan', id: campaign_id });
    } catch (e) {
      await say(getStrings(s.lang).t.error(e.message), { spoken: 'en', listen: false });
      setBusy(false);
    }
  }, [say]);

  // ---------------- changes
  const loadAssets = useCallback(async () => {
    const id = live.current.cur?.id;
    if (!id) return [];
    try { const b = await getBoard(id); setAssets(b.assets); return b.assets; } catch { return []; }
  }, []);

  const beginChange = useCallback(async () => {
    if (!live.current.cur?.id) { await sayT('noCampaign'); return; }
    setMode('change');
    await loadAssets();
    await sayT('changeIntro');
  }, [sayT, loadAssets]);

  const proposeFor = useCallback(async (text, { chatFallback = false } = {}) => {
    const id = live.current.cur?.id;
    if (!id) { await sayT('noCampaign'); setMode('home'); return; }
    setBusy(true);
    try {
      const [p, list] = await Promise.all([proposeChange(id, text.trim()), loadAssets()]);
      const { t, lang: l } = getStrings(live.current.lang);
      setProposal(p);
      if (!p.grounded) {
        setMode('change');
        await say(t.notGrounded, { spoken: l, extra: { kind: 'proposal' } });
        return;
      }
      setMode('confirm');
      const byId = new Map(list.map((a) => [a.id, a]));
      const names = p.affected_asset_ids.slice(0, 3).map((aid) => (byId.get(aid) ? `${channelLabel(byId.get(aid).channel)} ${langName(byId.get(aid).lang)}` : '')).filter(Boolean).join(', ');
      await say(t.proposal(prettyText(p.summary), p.affected_asset_ids.length, names), { spoken: l, extra: { kind: 'proposal' } });
    } catch (e) {
      if (e.code === 'not_understood' && chatFallback) { setBusy(false); setMode(live.current.proposal ? 'confirm' : 'home'); return chatRef.current(text); }
      setMode('change');
      await say(e.code === 'not_understood' ? getStrings(live.current.lang).t.notUnderstood : getStrings(live.current.lang).t.error(e.message), { spoken: getStrings(live.current.lang).lang });
    } finally {
      setBusy(false);
    }
  }, [say, sayT, loadAssets]);

  // Anything that is not a plain command: Agnez answers it, in the one voice on this screen. Her spoken reply is written here
  // too, so nothing is only heard. No second chat model is used.
  const chatRef = useRef(null);
  const chatReply = useCallback(async () => {
    const ok = await ensureLive();
    if (!ok || agnez.status === 'error') { const { t } = getStrings(live.current.lang); return say(t.unknown, { extra: { kind: 'unknown' } }); }
    replyRef.current = (reply) => push(msg('ai', reply, { provider: 'agnez' }));
  }, [ensureLive, agnez.status, say, push]);
  chatRef.current = chatReply;

  const applyNow = useCallback(async () => {
    const p = live.current.proposal;
    const id = live.current.cur?.id;
    if (!p || !id || !p.grounded) return;
    setBusy(true);
    try {
      await applyChange(id, p.proposal_id);
      setProposal(null);
      setMode('home');
      await sayT('applied', p.affected_asset_ids.length);
    } catch (e) {
      const { t, lang: l } = getStrings(live.current.lang);
      await say(e.code === 'already_applied' ? 'That change was already applied.' : t.error(e.message), { spoken: e.code === 'already_applied' ? 'en' : l });
      setProposal(null);
      setMode('home');
    } finally {
      setBusy(false);
    }
  }, [say, sayT]);

  const discard = useCallback(async () => {
    setProposal(null);
    setMode('home');
    await sayT('discarded');
  }, [sayT]);

  // ---------------- what was heard (voice or typed)
  const onHeard = useCallback(async (text, source = 'voice') => {
    setPaused(false);
    setLastHeard(text);
    const { mode: m, session: s } = live.current;
    push(msg('user', text, { source }));

    if (m === 'change') {
      const word = understand(text, 'confirm').intent;
      if (word === 'no') { setMode('home'); await sayT('discarded'); return; }
      await proposeFor(text, { chatFallback: true });
      return;
    }
    const u = understand(text, m === 'confirm' ? 'confirm' : m === 'interview' ? 'interview' : 'home');
    switch (u.intent) {
      case 'yes': return applyNow();
      case 'no': return discard();
      case 'repeat': {
        const lastAi = [...live.current.history].reverse().find((x) => x.role === 'ai');
        if (lastAi) await say(lastAi.text, { spoken: effLang(), extra: { replay: true } });
        return;
      }
      case 'help': return sayT('help');
      case 'new_campaign': return startNew();
      case 'navigate': {
        navigate(u.slug); // straight away: the screen changing is the confirmation, and waiting for a voice would make it feel slow
        return;
      }
      case 'change': {
        if (hasDetail(u.text)) return proposeFor(u.text, { chatFallback: true });
        return beginChange();
      }
      case 'finish': return s ? buildPlan() : sayT('unknown');
      case 'skip': {
        if (s?.question && !s.question.required) return sendAnswer({ choices: ['skip'], source: 'tap' });
        return sayT('skipNotAllowed');
      }
      case 'answer': return s ? (looksLikeQuestion(text) ? chatReply(text) : sendAnswer({ text, source })) : undefined;
      case 'empty': return undefined;
      default:
        if (m === 'confirm') return sayT('confirmHint');
        return chatReply(text); // not a command: let the chat brain answer it
    }
  }, [push, agnez, say, sayT, startNew, proposeFor, applyNow, discard, beginChange, buildPlan, sendAnswer, chatReply]);

  // kept for "repeat that"
  live.current.history = messages;
  onHeardRef.current = onHeard;

  // The visible microphone, made honest: the call's own live/listening/speaking state, nothing invented.
  const liveNow = agnez.status === 'live';
  const mic = {
    supported: agnez.availability ? agnez.availability.available === true : true,
    listening: liveNow && agnez.mode === 'listening',
    speaking: liveNow && agnez.mode === 'speaking',
    transcribing: agnez.status === 'connecting',
    error: agnez.error,
    note: '',
    engine: 'agnez',
    start: () => agnez.start(live.current.lang),
    stop: () => agnez.interrupt(),
  };
  const voice = { speaking: liveNow && agnez.mode === 'speaking', preparing: agnez.status === 'connecting', engine: 'agnez', stop: () => agnez.interrupt() };

  // Hands-free: the call stays open, so there is no per-question tap. If it drops or the microphone is blocked, say so
  // plainly and leave the typed fallback; do not loop silently.
  useEffect(() => {
    if (!agnez.error || !live.current.started) return;
    if (/blocked|No microphone|Could not open/i.test(agnez.error)) setPaused(true);
  }, [agnez.error]);

  // ---------------- starting and stopping
  const begin = useCallback(async () => {
    setStarted(true);
    live.current.started = true;
    await ensureLive(); // open the one voice call; if the browser blocks the microphone, say() still shows the line on screen
    const { t } = getStrings(live.current.lang);
    const first = user?.name?.split(' ')[0];
    await say(t.greet(first));
  }, [say, ensureLive, user]);

  // Arriving with a session in the address (from Home, or a refresh): pick the conversation up where it was.
  useEffect(() => {
    if (!sessionId || owned.current === sessionId) return undefined;
    let liveFlag = true;
    getSession(sessionId).then(async (s) => {
      if (!liveFlag) return;
      setStarted(true);
      live.current.started = true;
      live.current.session = s;
      setLangState(s.lang);
      await ask(s, true);
    }).catch((e) => liveFlag && push(msg('system', e.message)));
    return () => { liveFlag = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Arriving from a button that already knows what it wants, or simply arriving with hands-free on: start without a tap. The
  // first visit still needs one tap for the browser's microphone permission; after that, coming to Talk is enough.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (sessionId || autoStarted.current) return;
    autoStarted.current = true;
    let want = null;
    try { want = sessionStorage.getItem(INTENT_KEY); sessionStorage.removeItem(INTENT_KEY); } catch { /* storage blocked */ }
    if (want) {
      setStarted(true);
      live.current.started = true;
      if (want === 'change') beginChange();
      else begin();
    } else if (live.current.handsFree) {
      begin();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Teardown of the voice call is owned by useAgnez (StrictMode-safe), so there is nothing to end here.

  const orb = useCallback(async () => {
    if (!live.current.started) { setEnded(false); live.current.ended = false; await begin(); return; }
    if (live.current.ended || agnez.status === 'error' || agnez.status === 'idle') { setEnded(false); live.current.ended = false; await agnez.start(live.current.lang); return; } // the call was ended or dropped: reopen it
    if (agnez.mode === 'speaking') { agnez.interrupt(); return; } // take the floor from Agnez
    setPaused(false);
    agnez.interrupt(); // best effort: make sure the floor is the person's
  }, [begin, agnez]);

  // Hang up: close the call and drop every line still waiting to be spoken. Nothing reopens it until the person taps reconnect.
  const endCall = useCallback(async () => {
    setEnded(true);
    live.current.ended = true;
    replyRef.current = null;
    await agnez.end();
  }, [agnez]);

  const setLang = (l) => { setLangState(l); try { localStorage.setItem('talk-lang', l); } catch { /* ignore */ } };
  const setHandsFree = (v) => setHandsFreeState(v);
  const setVoiceOn = (v) => { setVoiceOnState(v); writeBool('talk-voice', v); agnez.setVolume(v ? 1 : 0); };

  const phase = voice.speaking || voice.preparing ? 'speaking' : mic.listening ? 'listening' : mic.transcribing || busy || thinking ? 'thinking' : 'idle';

  return {
    lang, setLang, handsFree, setHandsFree, voiceOn, setVoiceOn, started, paused, ended, endCall, messages, session, proposal, assets, mode, busy, phase, lastHeard,
    mic, voice, agnez, orb, onHeard, sendAnswer, editHeard, buildPlan, applyNow, discard, beginChange, startNew,
    replay: (text) => say(text, { extra: { kind: 'replay' } }),
    strings, hasCampaign: Boolean(cur.id),
  };
}

// Used by buttons elsewhere: open Talk already set to do one thing.
export const openTalk = (intent) => {
  try { sessionStorage.setItem(INTENT_KEY, intent); } catch { /* storage blocked: Talk opens on its normal start */ }
  navigate('voice');
};
