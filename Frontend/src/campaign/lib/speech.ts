import { useCallback, useState } from "react";
import { useAgnez } from "../../voice/agnez";
export { useVoiceInput as useRecognizer } from "./voice";

// Read-aloud surfaces share the configured Agnez agent without a browser voice fallback.
export function useSpeaker(lang: string) {
  const agnez = useAgnez();
  const [muted, setMuted] = useState(() => {
    try { return localStorage.getItem("cv-muted") === "1"; } catch { return false; }
  });
  const speak = useCallback(async (text: string, force = false) => {
    if (!text.trim() || (muted && !force)) return;
    if (await agnez.start({ lang, firstMessage: "" })) {
      await agnez.say(text);
    }
  }, [agnez.start, agnez.say, lang, muted]);
  const cancel = useCallback(() => { void agnez.stop(); }, [agnez.stop]);
  const toggleMute = () => setMuted((value) => {
    const next = !value;
    try { localStorage.setItem("cv-muted", next ? "1" : "0"); } catch { /* storage unavailable */ }
    if (next) cancel();
    return next;
  });
  return { available: Boolean(agnez.availability?.available), hasVoice: Boolean(agnez.availability?.available), muted, speak, cancel, toggleMute };
}
