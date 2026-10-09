import { useCallback, useEffect, useRef, useState } from "react";
import { api, voiceToken } from "./api";

// One microphone hook for every screen outside Talk, and it is Agnez (the ElevenLabs agent) that hears you. A dictation opens a
// short-lived call, takes the first thing you say as text, and closes. The agent is told to stay silent and her volume is zero,
// so only the words come back. The key and the agent id stay on the server: the page gets a short-lived token from /voice/token.
// The transcript is only text to correct; it never writes locked facts. Talk keeps its own continuous call (src/voice/agnez.jsx).

const OVERRIDE_LANGS = new Set(["en", "hi", "ta"]);
const MAX_SECONDS = 45;
const BRIEF = "This is a dictation into a text box. Do not speak and do not answer. Only listen.";

type Session = { endSession: () => Promise<void>; setVolume: (o: { volume: number }) => void; sendContextualUpdate: (t: string) => void };

export function useVoiceInput(lang: string, onFinal: (text: string) => void) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const conv = useRef<Session | null>(null);
  const timer = useRef(0);
  const cbRef = useRef(onFinal);
  cbRef.current = onFinal;

  useEffect(() => {
    let live = true;
    api<{ available: boolean }>("/voice/status").then((r) => live && setAvailable(Boolean(r?.available))).catch(() => live && setAvailable(false));
    return () => { live = false; };
  }, []);

  const stop = useCallback(() => {
    window.clearTimeout(timer.current);
    const c = conv.current;
    conv.current = null;
    setListening(false);
    setConnecting(false);
    setInterim("");
    // endSession may return nothing rather than a promise: never call .catch on it directly.
    void Promise.resolve().then(() => c?.endSession?.()).catch(() => undefined);
  }, []);

  useEffect(() => stop, [stop]);

  const start = useCallback(async () => {
    if (conv.current || connecting) return;
    setError("");
    setInterim("");
    setConnecting(true);
    try {
      const { conversation_token: token } = await voiceToken();
      if (!token) throw new Error("not configured");
      const { Conversation } = await import("@elevenlabs/client");
      const opts: Record<string, unknown> = {
        overrides: { agent: { prompt: { prompt: BRIEF }, firstMessage: '' } },
        conversationToken: token,
        connectionType: "webrtc",
        onMessage: ({ message, source }: { message?: string; source?: string }) => {
          const text = String(message || "").trim();
          if (!text || source !== "user") return;
          stop();
          cbRef.current(text);
        },
        onDisconnect: () => { if (conv.current) stop(); },
        onError: (m: unknown) => setError(String((m as Error)?.message || m || "Agnez hit a problem. Type instead.")),
      };
      let session: Session;
      try {
        session = (await Conversation.startSession(OVERRIDE_LANGS.has(lang) ? { ...opts, overrides: { agent: { language: lang, prompt: { prompt: BRIEF }, firstMessage: '' } } } : opts)) as unknown as Session;
      } catch (error) {
        throw error;
      }
      conv.current = session;
      try { session.setVolume({ volume: 0 }); session.sendContextualUpdate(BRIEF); } catch { /* not fatal */ }
      setConnecting(false);
      setListening(true);
      setInterim("Listening to Agnez");
      timer.current = window.setTimeout(stop, MAX_SECONDS * 1000);
    } catch (e) {
      setConnecting(false);
      const m = `${(e as Error)?.name || ""} ${(e as Error)?.message || ""}`;
      setError(/permission|denied|notallowed/i.test(m) ? "Microphone access is blocked. Allow it in the browser, or type instead."
        : /not configured|503|unavailable/i.test(m) ? "Agnez is not set up on this server. Type instead." : "Could not reach Agnez. Type instead.");
    }
  }, [lang, connecting, stop]);

  return {
    supported: available !== false,
    engine: "agnez" as const,
    listening,
    transcribing: connecting,
    interim: connecting ? "Connecting to Agnez" : interim,
    error,
    start,
    stop,
    clearError: () => setError(""),
    note: "",
  };
}
