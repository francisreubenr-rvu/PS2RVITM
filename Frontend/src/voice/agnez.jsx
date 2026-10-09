import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { ConversationProvider, useConversation } from '@elevenlabs/react';
import { api, voiceToken } from '../campaign/lib/api';

// Agnez is the one voice in GrowIt: the ElevenLabs agent, over a live WebRTC call. Every voice surface goes through useAgnez().
// The browser gets a short-lived conversation token from GET /voice/token; the agent id and the key stay on the server. When that
// route is off the server-signed websocket address from GET /talk/agent is used. The microphone is a live stream, so the person
// can talk over Agnez at any moment (barge-in).

// Languages the agent accepts as a spoken-language override. Other languages keep the agent's default and follow the text.
const OVERRIDE_LANGS = new Set(['en', 'hi', 'ta']);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const Ctx = createContext(null);

// A conversation token is fetched ahead of the tap and used once, so opening the call skips a server round trip. It expires
// quickly, so one older than this is discarded and a fresh one is fetched.
const TOKEN_TTL_MS = 45000;

function Inner({ children }) {
  const [availability, setAvailability] = useState(null); // null while checking, then { available, reason }
  const [status, setStatus] = useState('idle'); // idle | connecting | live | error
  const [mode, setMode] = useState('listening'); // listening | speaking
  const [lines, setLines] = useState([]); // live transcript: { who: 'you' | 'agent', text }
  const [error, setError] = useState('');
  const handlers = useRef({}); // { onUser(text), onAgent(text) }: set by whichever screen is driving the call
  const closing = useRef(false);
  const waiter = useRef(null); // resolves start() once the call is live or has failed
  const retry = useRef(null); // one retry without the language override
  const statusRef = useRef('idle');
  const modeRef = useRef('listening'); // the agent's own state, readable inside the speech queue
  const queue = useRef(Promise.resolve()); // lines handed to Agnez, spoken one at a time
  const generation = useRef(0); // bumped when the call ends, so lines still waiting in the queue are dropped
  const sessionConfig = useRef(null);
  const warm = useRef(null); // { at, promise } of a token fetched ahead of time
  const setS = (s) => { statusRef.current = s; setStatus(s); };

  const conv = useConversation({
    onConnect: () => { setS('live'); waiter.current?.(true); waiter.current = null; },
    onDisconnect: () => {
      if (closing.current) return;
      retry.current = null;
      if (statusRef.current === 'live' || statusRef.current === 'connecting') setS('idle');
      waiter.current?.(false); waiter.current = null;
    },
    onError: (m) => { setError(String(m?.message || m || 'The voice call hit a problem.')); },
    onMessage: ({ message, source, role }) => {
      const text = String(message || '').trim();
      if (!text) return;
      if ((source || role) === 'user') {
        setLines((l) => [...l.slice(-5), { who: 'you', text }]);
        handlers.current.onUser?.(text);
      } else {
        setLines((l) => [...l.slice(-5), { who: 'agent', text }]);
        handlers.current.onAgent?.(text);
      }
    },
    onModeChange: ({ mode: m }) => { modeRef.current = m; setMode(m); },
  });
  const c = useRef(conv);
  c.current = conv;

  useEffect(() => {
    let live = true;
    api('/voice/status').then((r) => live && setAvailability(r)).catch((e) => live && setAvailability({ available: false, reason: e.message }));
    return () => { live = false; };
  }, []);

  // Close the call when the provider goes away, but not during React's StrictMode double-mount.
  const endTimer = useRef(0);
  useEffect(() => {
    if (endTimer.current) { window.clearTimeout(endTimer.current); endTimer.current = 0; }
    return () => {
      endTimer.current = window.setTimeout(() => { closing.current = true; try { c.current.endSession(); } catch { /* already closed */ } }, 0);
    };
  }, []);

  // Fetch the conversation token before it is needed. Safe to call repeatedly; a fetch that fails is simply forgotten.
  const prepare = useCallback(() => {
    if (warm.current && Date.now() - warm.current.at < TOKEN_TTL_MS) return;
    const promise = voiceToken();
    warm.current = { at: Date.now(), promise };
    promise.catch(() => { if (warm.current?.promise === promise) warm.current = null; });
  }, []);
  const takeToken = () => {
    const w = warm.current;
    warm.current = null; // a token opens one call
    return w && Date.now() - w.at < TOKEN_TTL_MS ? w.promise : voiceToken();
  };

  // Open the call. Resolves true once live. Raises nothing: read status and error.
  const start = useCallback(async function startMode({ lang = 'en', clientTools, brief } = {}) {
    const sameMode = sessionConfig.current?.lang === lang && sessionConfig.current?.brief === (brief || '') && sessionConfig.current?.clientTools === clientTools;
    if (statusRef.current === 'connecting') {
      const ok = await new Promise((res) => { const prev = waiter.current; waiter.current = (ready) => { prev?.(ready); res(ready); }; });
      if (sameMode) return ok;
      return startMode({ lang, clientTools, brief });
    }
    if (statusRef.current === 'live') {
      if (sameMode) return true;
      closing.current = true;
      try { await c.current.endSession(); } catch { /* already closed: endSession returns nothing in @elevenlabs/react, so it has no .catch */ }
      setS('idle');
    }
    sessionConfig.current = { lang, brief: brief || '', clientTools };
    setError('');
    setLines([]);
    modeRef.current = 'listening';
    setMode('listening');
    setS('connecting');
    closing.current = false;
    try {
      let transport;
      try {
        const { conversation_token: token } = await takeToken();
        if (!token) throw new Error('no token');
        transport = { conversationToken: token, connectionType: 'webrtc' };
      } catch (error) {
        if (![404, 405].includes(error.status)) throw error;
        const { signed_url: signedUrl } = await api('/talk/agent');
        if (!signedUrl) throw new Error('The live voice is not available.');
        transport = { signedUrl, connectionType: 'websocket' };
      }
      const ready = new Promise((res) => { waiter.current = res; });
      const open = (withLang) => c.current.startSession({
        ...transport,
        ...(clientTools ? { clientTools } : {}),
        overrides: { agent: { ...(withLang ? { language: lang } : {}), ...(brief ? { prompt: { prompt: brief }, firstMessage: '' } : {}) } },
      });
      const wantLang = OVERRIDE_LANGS.has(lang);
      retry.current = null;
      await open(wantLang);
      const ok = await Promise.race([ready, sleep(20000).then(() => false)]);
      if (!ok) {
        waiter.current?.(false); waiter.current = null; closing.current = true;
        try { await c.current.endSession(); } catch { /* already closed: endSession returns nothing in @elevenlabs/react, so it has no .catch */ }
        setError((e) => e || 'The voice call did not open.'); setS('error'); return false;
      }
      if (brief) c.current.sendContextualUpdate(brief);
      return true;
    } catch (e) {
      const m = `${e?.name || ''} ${e?.message || ''}`;
      setError(/permission|denied|notallowed/i.test(m) ? 'The microphone is blocked. Allow it in the browser, or type instead.' : e?.message || 'Could not open the voice call.');
      waiter.current?.(false); waiter.current = null;
      closing.current = true;
      try { await c.current.endSession(); } catch { /* already closed: endSession returns nothing in @elevenlabs/react, so it has no .catch */ }
      setS('error');
      return false;
    }
  }, []);

  const stop = useCallback(async () => {
    closing.current = true;
    generation.current += 1; // drop every line still waiting to be spoken
    queue.current = Promise.resolve();
    sessionConfig.current = null;
    retry.current = null;
    waiter.current?.(false); waiter.current = null;
    try { await c.current.endSession(); } catch { /* already closed */ }
    if (statusRef.current !== 'error') setS('idle');
    modeRef.current = 'listening';
    setMode('listening');
  }, []);

  // Make Agnez say a line. Lines are spoken one at a time: each waits until she has finished the one before, so she is never cut
  // off by the next line arriving mid-sentence. Resolves true once the line is handed over (not when she finishes speaking).
  const say = useCallback((text) => {
    const line = String(text || '').trim();
    if (!line) return Promise.resolve(false);
    const g = generation.current;
    const stale = () => g !== generation.current || statusRef.current === 'idle' || statusRef.current === 'error';
    const until = async (done, ms) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        if (stale()) return false;
        if (done()) return true;
        await sleep(80);
      }
      return false;
    };
    let handed;
    const sent = new Promise((res) => { handed = res; });
    const run = async () => {
      await until(() => statusRef.current !== 'connecting', 8000);
      if (stale() || statusRef.current !== 'live') { handed(false); return; }
      await until(() => modeRef.current === 'listening', 60000); // she finishes what she is saying
      await sleep(250); // a short breath between lines
      if (stale() || statusRef.current !== 'live') { handed(false); return; }
      try { c.current.sendUserMessage(`SAY: ${line}`); handed(true); } catch { handed(false); return; }
      await until(() => modeRef.current === 'speaking', 6000); // she starts...
      await until(() => modeRef.current === 'listening', 90000); // ...and finishes before the next line goes out
    };
    queue.current = queue.current.then(run, run);
    return sent;
  }, []);

  // Quiet context for the agent: does not interrupt her.
  const sendContext = useCallback((text) => {
    const t = String(text || '').trim();
    if (!t || statusRef.current !== 'live') return false;
    try { c.current.sendContextualUpdate(t); return true; } catch { return false; }
  }, []);

  const interrupt = useCallback(() => { try { c.current.sendUserActivity(); } catch { /* not fatal */ } }, []);
  const setVolume = useCallback((volume) => { try { c.current.setVolume({ volume }); } catch { /* not fatal */ } }, []);
  const inputVolume = useCallback(() => { try { return c.current.getInputVolume() || 0; } catch { return 0; } }, []);
  const outputVolume = useCallback(() => { try { return c.current.getOutputVolume() || 0; } catch { return 0; } }, []);
  const setHandlers = useCallback((h) => { handlers.current = h || {}; }, []);

  const value = useMemo(() => ({
    availability, status, mode, isSpeaking: status === 'live' && mode === 'speaking', lines, error,
    start, stop, prepare, say, sendContext, interrupt, setVolume, inputVolume, outputVolume, setHandlers,
  }), [availability, status, mode, lines, error, start, stop, prepare, say, sendContext, interrupt, setVolume, inputVolume, outputVolume, setHandlers]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function AgnezProvider({ children }) {
  return <ConversationProvider><Inner>{children}</Inner></ConversationProvider>;
}

export function useAgnez() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAgnez must be used inside <AgnezProvider>');
  return v;
}
