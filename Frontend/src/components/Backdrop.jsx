import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { PixelImageTrail } from '@/components/ui/pixel-image-trail';

// The moving gradient was removed from Settings, so its three.js shader is no longer chosen; it stays for reference.
const ShaderBackdrop = lazy(() => import('./ShaderBackdrop.jsx'));

const current = () => document.documentElement.dataset.backdrop || 'trail';

// The trail component reacts to a pointer over its own box. The app's glass panels sit on top of the backdrop and
// would swallow those events, so the window's pointer movement is handed to the backdrop box instead.
function useForwardPointer(ref, active) {
  useEffect(() => {
    if (!active) return undefined;
    const wrapper = ref.current;
    // The listeners sit on the component's own box, the wrapper's only child. Events travel up, not down, so send them there.
    const box = wrapper?.firstElementChild;
    if (!box) return undefined;
    const send = (type, event) =>
      box.dispatchEvent(new PointerEvent(type, { clientX: event.clientX, clientY: event.clientY, pointerType: event.pointerType }));
    const onMove = (event) => send('pointermove', event);
    const onLeave = (event) => send('pointerleave', event);
    window.addEventListener('pointermove', onMove, { passive: true });
    document.documentElement.addEventListener('pointerleave', onLeave);
    return () => {
      window.removeEventListener('pointermove', onMove);
      document.documentElement.removeEventListener('pointerleave', onLeave);
    };
  }, [ref, active]);
}

export default function Backdrop() {
  const [mode, setMode] = useState(current);
  const trailRef = useRef(null);
  useEffect(() => {
    const watch = new MutationObserver(() => setMode(current()));
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ['data-backdrop'] });
    return () => watch.disconnect();
  }, []);
  const shader = mode === 'animated';
  const trail = mode === 'trail';
  useForwardPointer(trailRef, trail);
  return (
    <div className={`app-backdrop${shader ? ' has-shader' : ''}`} aria-hidden="true">
      {shader ? <Suspense fallback={null}><ShaderBackdrop /></Suspense> : null}
      {trail ? (
        <div ref={trailRef} className="backdrop-trail">
          <PixelImageTrail src="/backdrop/lake.jpg" alt="" className="size-full" pixelSize={40} fadeDuration={1100} />
        </div>
      ) : null}
    </div>
  );
}
