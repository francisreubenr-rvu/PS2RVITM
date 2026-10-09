import { useState } from 'react';
import { Mic, MicOff, Pause, Play, PhoneOff, ChevronDown } from 'lucide-react';
import ThinkingOrb from '../../orb/ThinkingOrb';
import { useTalkContext } from './TalkContext';
import { navigate } from '../../lib/router';

// Agnez, present on every screen. One tap starts the call; once it is live she stays with the person as they change pages, so
// "open customers" or "show me the plan" can be said anywhere. The dock shows whose turn it is, her last line, and the three
// controls: mute the microphone, pause the call, end it. On the Talk screen itself the larger panel takes over, so this hides.
const AgnezDock = ({ hideIdle = false }) => {
  const t = useTalkContext();
  const a = t.agnez;
  const [open, setOpen] = useState(true);
  const live = a.status === 'live' && !t.ended;
  const connecting = a.status === 'connecting';
  const speaking = live && a.mode === 'speaking' && !a.paused;
  const state = !live ? (connecting ? 'Opening the call' : 'Talk to Agnez') : a.paused ? 'Paused' : a.muted ? 'Muted' : speaking ? 'Speaking' : 'Listening';
  const lastAi = [...t.messages].reverse().find((m) => m.role === 'ai');
  const lastYou = [...t.messages].reverse().find((m) => m.role === 'user');
  const orbState = a.paused || a.muted ? 'shaping' : speaking ? 'composing' : 'listening';
  const ring = speaking ? 'dock-ring dock-ring-speak' : live && !a.paused ? 'dock-ring dock-ring-listen' : 'dock-ring';
  const btn = 'grid size-10 place-items-center rounded-full text-white transition-colors focus-visible:outline-2 focus-visible:outline-white/80';

  if (!live && !connecting) {
    if (hideIdle) return null; // Home has its own big start button
    return (
      <button type="button" onClick={t.orb} className="fixed bottom-24 right-3 z-50 flex items-center gap-2 rounded-full bg-accent py-2 pl-2 pr-4 font-semibold text-on-accent shadow-xl transition-transform hover:scale-[1.04] lg:bottom-5 lg:right-5" aria-label="Talk to Agnez">
        <span className="grid size-10 place-items-center rounded-full bg-black/15"><Mic size={20} /></span>
        <span className="text-sm">Talk to Agnez</span>
      </button>
    );
  }

  return (
    <aside className="fixed bottom-24 right-3 z-50 w-[min(20rem,calc(100vw-1.5rem))] overflow-hidden rounded-3xl bg-[#14141a] text-white shadow-2xl ring-1 ring-white/12 lg:bottom-5 lg:right-5" aria-label="Agnez">
      <div className="flex items-center gap-3 p-3">
        <button type="button" onClick={() => setOpen((v) => !v)} className={`${ring} relative grid size-14 shrink-0 place-items-center rounded-full bg-black`} aria-label={open ? 'Hide Agnez' : 'Show Agnez'}>
          <span className="grid size-full place-items-center [&_canvas]:!size-12"><ThinkingOrb key={orbState} state={orbState} size={64} theme="dark" /></span>
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{state}</p>
          <p className="truncate text-xs text-white/55">{a.paused ? 'On hold. Resume to keep going.' : a.muted ? 'Your microphone is off.' : speaking ? 'Talk over her to interrupt.' : 'Just talk. Say "open customers" to go there.'}</p>
        </div>
        <button type="button" onClick={() => setOpen((v) => !v)} className="grid size-8 place-items-center rounded-full text-white/60 hover:bg-white/10" aria-label={open ? 'Collapse' : 'Expand'} aria-expanded={open}>
          <ChevronDown size={16} className={open ? '' : 'rotate-180'} />
        </button>
      </div>
      {open && (
        <div className="grid gap-3 px-3 pb-3">
          {(lastAi || lastYou) && (
            <div className="grid gap-1.5 rounded-2xl bg-white/6 p-3 text-xs leading-relaxed" aria-live="polite">
              {lastAi && <p className="line-clamp-3 text-white/90"><span className="mr-1 font-semibold text-accent">Agnez</span>{lastAi.text}</p>}
              {lastYou && <p className="line-clamp-2 text-white/55"><span className="mr-1 font-semibold">You</span>{lastYou.text}</p>}
            </div>
          )}
          <div className="grid grid-cols-3 gap-2">
            <button type="button" onClick={() => a.setMute(!a.muted)} disabled={!live || a.paused} aria-pressed={a.muted} className={`${btn} h-11 w-full gap-1.5 text-xs font-semibold ${a.muted ? 'bg-white text-[#14141a]' : 'bg-white/12 hover:bg-white/20'} grid-flow-col disabled:opacity-40`}>
              {a.muted ? <MicOff size={16} /> : <Mic size={16} />} {a.muted ? 'Unmute' : 'Mute'}
            </button>
            <button type="button" onClick={() => (a.paused ? a.resume() : a.pause())} disabled={!live} aria-pressed={a.paused} className={`${btn} h-11 w-full gap-1.5 text-xs font-semibold ${a.paused ? 'bg-accent text-on-accent' : 'bg-white/12 hover:bg-white/20'} grid-flow-col disabled:opacity-40`}>
              {a.paused ? <Play size={16} /> : <Pause size={16} />} {a.paused ? 'Resume' : 'Pause'}
            </button>
            <button type="button" onClick={t.endCall} className={`${btn} h-11 w-full grid-flow-col gap-1.5 bg-bad text-xs font-semibold hover:brightness-110`}>
              <PhoneOff size={16} /> End
            </button>
          </div>
          <button type="button" onClick={() => navigate('voice')} className="text-center text-xs font-medium text-white/55 hover:text-white">Open the full conversation</button>
        </div>
      )}
    </aside>
  );
};

export default AgnezDock;
