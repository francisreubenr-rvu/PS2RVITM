import { useCallback, useEffect, useRef } from 'react';
import { useAgnez } from '../../voice/agnez';

// The one voice on Talk is Agnez, over the shared live call in src/voice/agnez.jsx. She both asks and hears, so the microphone
// stays open the whole time and the person can speak over her at any point (barge-in). Nothing else speaks here: no browser
// recognition, no browser voice, no second chat model.
//
// GrowIt stays the source of truth. It hands Agnez each line to say, tagged "SAY:", and the person's own spoken words come back
// as text that the interview records (campaign/lib/api.ts). Anything the person says on their own, Agnez simply answers briefly.

// Talk supplies its campaign instructions and an empty first message through approved session overrides.
// The shared agent's default personal-story prompt, tools and configured voice stay unchanged.
const TALK_BRIEF = `For this call you are Agnez on GrowIt's Talk screen, the only voice there.
GrowIt hands you lines as text, each one starting with "SAY:". Speak the text after "SAY:" exactly, warmly, and in the language it is written in: do not add, shorten, translate or explain it.
When the person speaks on their own, it is their answer to GrowIt: reply with one short, neutral sentence at most (for example "Got it"), never advice and never your own question. If they clearly ask you a question, answer it briefly.
Never call a tool. Never invent questions. If the person speaks while you are speaking, stop at once and listen.`;

// The shared agent is configured with record_fact and revise_fact (the briefing screen's tools). Talk records answers itself through
// the interview, so these only acknowledge the call. Without them the agent reports "Client tool ... is not defined". One stable
// object: the call restarts if the tools passed to start() change.
const TALK_TOOLS = {
  record_fact: () => 'noted',
  revise_fact: () => 'noted',
};

export function useTalkVoice({ onFinal, onAgent } = {}) {
  const a = useAgnez();
  const finalRef = useRef(onFinal);
  const agentRef = useRef(onAgent);
  finalRef.current = onFinal;
  agentRef.current = onAgent;

  useEffect(() => {
    a.setHandlers({
      onUser: (text) => { if (/^SAY:/i.test(text) || !/[\p{L}\p{N}]/u.test(text)) return; finalRef.current?.(text); }, // our own hand-off lines can echo back, and a bare "..." is room noise: neither is an answer
      onAgent: (text) => agentRef.current?.(text),
    });
    a.prepare(); // the token is ready before the first line needs the call
    return () => { a.setHandlers(null); void a.stop(); };
  }, [a.setHandlers]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback((lang = 'en') => a.start({ lang, brief: TALK_BRIEF, clientTools: TALK_TOOLS }), [a.start]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    availability: a.availability, status: a.status, mode: a.mode, lines: a.lines, error: a.error,
    start, end: a.stop, say: a.say, context: a.sendContext, interrupt: a.interrupt, setVolume: a.setVolume,
  };
}
