import { useCallback, useEffect, useRef, useState } from 'react';
import { api, voiceToken } from '../../campaign/lib/api';
import { addFact, reviseFact } from './facts';

// A live voice briefing with the ElevenLabs agent (Agnez). The browser talks to ElevenLabs directly over a short-lived address the server
// signs, so the key never reaches the page. The agent asks one question at a time and calls tools as the person speaks:
//   record_fact / revise_fact   build and correct the live map (facts.js)
//   pause_briefing / resume_briefing   stop and restart the clock
//   complete_briefing           the agent has what it needs
// Nothing is kept until the owner presses Save on the finished map. The briefing is capped at ten minutes, the agent's own limit.

export const LIMIT_SECONDS = 600;

export function useBriefing() {
  const [availability, setAvailability] = useState(null); // null while checking, then { available, reason }
  const [status, setStatus] = useState('idle'); // idle | connecting | live | done | error
  const [mode, setMode] = useState('listening'); // listening | speaking
  const [paused, setPaused] = useState(false);
  const [facts, setFacts] = useState([]);
  const [lines, setLines] = useState([]);
  const [left, setLeft] = useState(LIMIT_SECONDS);
  const [error, setError] = useState('');
  const conv = useRef(null);
  const pausedRef = useRef(false);
  const closing = useRef(false);

  useEffect(() => {
    let live = true;
    api('/voice/status').then((r) => live && setAvailability(r)).catch((e) => live && setAvailability({ available: false, reason: e.message }));
    return () => { live = false; };
  }, []);

  const finish = useCallback(async (to = 'done') => {
    closing.current = true;
    const c = conv.current;
    conv.current = null;
    try { await c?.endSession(); } catch { /* already closed */ }
    setStatus((s) => (s === 'error' ? s : to));
  }, []);

  // The clock counts down while the briefing is live and not paused.
  useEffect(() => {
    if (status !== 'live') return undefined;
    const t = setInterval(() => {
      if (pausedRef.current) return;
      setLeft((n) => {
        if (n <= 1) { finish('done'); return 0; }
        return n - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [status, finish]);

  useEffect(() => () => {
    const c = conv.current;
    Promise.resolve().then(() => c?.endSession?.()).catch(() => undefined);
  }, []);

  const start = useCallback(async (lang = 'en') => {
    setError('');
    setFacts([]);
    setLines([]);
    setLeft(LIMIT_SECONDS);
    setPaused(false);
    pausedRef.current = false;
    closing.current = false;
    setStatus('connecting');
    try {
      // The live session opens over WebRTC from the conversation token GET /voice/token mints server-side
      // (@elevenlabs/client 1.27.0 accepts a conversationToken only for connectionType "webrtc"). When that route
      // is not configured, fall back to the server-signed signed_url from GET /talk/agent over a websocket. The key
      // and the agent id stay on the server either way.
      let transport;
      try {
        const { conversation_token: token } = await voiceToken();
        if (!token) throw new Error('no token');
        transport = { conversationToken: token, connectionType: 'webrtc' };
      } catch (error) {
        if (![404, 405].includes(error.status)) throw error;
        const { signed_url: signedUrl } = await api('/talk/agent');
        if (!signedUrl) throw new Error('The live agent is not available.');
        transport = { signedUrl, connectionType: 'websocket' };
      }
      const { Conversation } = await import('@elevenlabs/client'); // loaded only when a briefing starts
      const tools = {
        record_fact: (p) => { setFacts((f) => addFact(f, p)); return 'recorded'; },
        revise_fact: (p) => { setFacts((f) => reviseFact(f, p)); return 'revised'; },
        pause_briefing: () => { pausedRef.current = true; setPaused(true); return 'paused'; },
        resume_briefing: () => { pausedRef.current = false; setPaused(false); return 'resumed'; },
        complete_briefing: () => { setTimeout(() => finish('done'), 4500); return 'completed'; }, // let the agent finish its goodbye
      };
      const base = {
        ...transport,
        clientTools: tools,
        onConnect: () => setStatus('live'),
        onDisconnect: () => { if (!closing.current) setStatus((s) => (s === 'live' || s === 'connecting' ? 'done' : s)); },
        onError: (m) => { setError(String(m || 'The briefing hit a problem.')); },
        onMessage: ({ message, source }) => { if (message) setLines((l) => [...l.slice(-5), { who: source === 'user' ? 'you' : 'agent', text: message }]); },
        onModeChange: ({ mode: m }) => setMode(m),
      };
      try {
        conv.current = await Conversation.startSession(lang === 'en' ? base : { ...base, overrides: { agent: { language: lang } } });
      } catch (e) {
        if (lang === 'en') throw e;
        conv.current = await Conversation.startSession(base); // that language is not enabled on the agent: use its default
      }
      setStatus('live');
    } catch (e) {
      const denied = /permission|denied|NotAllowed/i.test(String(e?.name || e?.message));
      setError(denied ? 'The microphone is blocked. Allow it in the browser and try again.' : e?.message || 'Could not start the briefing.');
      setStatus('error');
    }
  }, [finish]);

  const reset = useCallback(() => { setStatus('idle'); setFacts([]); setLines([]); setError(''); setLeft(LIMIT_SECONDS); }, []);
  const remove = useCallback((id) => setFacts((f) => f.filter((x) => x.id !== id)), []);

  return { availability, status, mode, paused, facts, lines, left, error, start, end: () => finish('done'), reset, remove };
}
