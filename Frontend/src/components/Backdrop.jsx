import { lazy, Suspense, useEffect, useState } from 'react';
import Aurora from './Aurora';

// The moving gradient was removed from Settings, so its three.js shader is no longer chosen; it stays for reference.
const ShaderBackdrop = lazy(() => import('./ShaderBackdrop.jsx'));

const current = () => document.documentElement.dataset.backdrop || 'aurora';

export default function Backdrop() {
  const [mode, setMode] = useState(current);
  useEffect(() => {
    const watch = new MutationObserver(() => setMode(current()));
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ['data-backdrop'] });
    return () => watch.disconnect();
  }, []);
  const shader = mode === 'animated';
  const aurora = mode === 'aurora';
  return (
    <div className={`app-backdrop${shader ? ' has-shader' : ''}`} aria-hidden="true">
      {shader ? <Suspense fallback={null}><ShaderBackdrop /></Suspense> : null}
      {aurora ? <Aurora /> : null}
    </div>
  );
}
