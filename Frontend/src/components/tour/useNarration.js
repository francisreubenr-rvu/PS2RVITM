import { useCallback, useEffect, useRef, useState } from 'react';

// Plays the pre-made walkthrough narration: ElevenLabs speech in Agnez's voice, generated once into public/tour/audio
// (see scripts/make-tour-audio.mjs). They are plain static files, so nothing is sent to ElevenLabs while the tour runs.
// One clip at a time: a new step, a skip or a close stops the old one.

export const clipUrl = (lang, step) => `/tour/audio/${lang}/${step}.mp3`;

export function useNarration() {
  const [playing, setPlaying] = useState(false);
  const audio = useRef(null);
  const run = useRef(0); // each play() or stop() starts a new run, so a late "ended" from an old clip is ignored

  const stop = useCallback(() => {
    run.current += 1;
    const a = audio.current;
    audio.current = null;
    if (a) {
      a.onended = null;
      a.onerror = null;
      a.pause();
    }
    setPlaying(false);
  }, []);

  // Plays the clips in order. A clip that is missing is skipped. If the browser blocks autoplay, nothing plays and the
  // speaker button (which is a click) starts it.
  const play = useCallback((urls) => {
    stop();
    const id = run.current;
    let i = 0;
    const next = () => {
      if (id !== run.current) return;
      if (i >= urls.length) {
        setPlaying(false);
        return;
      }
      const a = new Audio(urls[i]);
      i += 1;
      audio.current = a;
      a.onended = next;
      a.onerror = next;
      a.play().then(() => id === run.current && setPlaying(true)).catch(() => id === run.current && setPlaying(false));
    };
    next();
  }, [stop]);

  useEffect(() => stop, [stop]); // leaving the tour stops the voice

  return { playing, play, stop };
}
