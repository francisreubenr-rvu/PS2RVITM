import { useEffect, useRef } from 'react';
import { Mesh, Program, Renderer, Triangle, Vec3 } from 'ogl';
import { ORB_FRAGMENT, ORB_VERTEX } from './shaders';

// The glowing ring behind the Talk mic. Ported from the reference build (https://growit-studio.vercel.app/): a noise-shaped
// ring tinted by `hue` that turns and ripples harder the louder the voice is.
//   getLevel   () => 0..1, the live audio level (the person's, or Agnez's). Without it the ring idles.
//   simulate   no level to read (the browser gives none for speech out): pulse the ring as if it were speaking.
// Respects reduced motion by drawing one still frame.
export default function GlowOrb({ className = '', hue = 0, getLevel = null, simulate = false, voiceSensitivity = 1.5, maxRotationSpeed = 1.2, maxHoverIntensity = 0.8 }) {
  const box = useRef(null);
  const live = useRef({});
  live.current = { hue, getLevel, simulate, voiceSensitivity, maxRotationSpeed, maxHoverIntensity };

  useEffect(() => {
    const host = box.current;
    if (!host) return undefined;
    let renderer;
    let gl;
    let raf = 0;
    try {
      renderer = new Renderer({ alpha: true, premultipliedAlpha: false, antialias: true, dpr: Math.min(window.devicePixelRatio || 1, 2) });
      gl = renderer.gl;
      gl.clearColor(0, 0, 0, 0);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      host.appendChild(gl.canvas);

      const program = new Program(gl, {
        vertex: ORB_VERTEX,
        fragment: ORB_FRAGMENT,
        uniforms: {
          iTime: { value: 0 },
          iResolution: { value: new Vec3(gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height) },
          hue: { value: hue },
          hover: { value: 0 },
          rot: { value: 0 },
          hoverIntensity: { value: 0 },
        },
      });
      const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

      const resize = () => {
        const w = host.clientWidth;
        const h = host.clientHeight;
        if (!w || !h) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        renderer.setSize(w * dpr, h * dpr);
        gl.canvas.style.width = `${w}px`;
        gl.canvas.style.height = `${h}px`;
        program.uniforms.iResolution.value.set(gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height);
      };
      window.addEventListener('resize', resize);
      resize();

      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      let last = 0;
      let rotation = 0;
      let level = 0; // the smoothed level: rises fast, falls slowly, so the ring breathes instead of flickering
      const frame = (now) => {
        if (!reduced) raf = requestAnimationFrame(frame);
        const dt = Math.min((now - last) * 0.001, 0.1);
        last = now;
        const p = live.current;
        let target = 0;
        if (p.getLevel) target = Math.min(p.getLevel() * p.voiceSensitivity * 1.6, 1);
        if (p.simulate) target = Math.max(target, 0.32 + 0.22 * Math.sin(now * 0.0071) * Math.sin(now * 0.0023 + 1) + 0.12 * Math.sin(now * 0.0137));
        level += (target - level) * Math.min(1, dt * (target > level ? 14 : 4));
        program.uniforms.iTime.value = now * 0.001;
        program.uniforms.hue.value = p.hue;
        rotation += dt * (0.3 + level * p.maxRotationSpeed * 2);
        program.uniforms.rot.value = rotation;
        program.uniforms.hover.value = Math.min(level * 2, 1);
        program.uniforms.hoverIntensity.value = Math.min(level * p.maxHoverIntensity * 0.8, p.maxHoverIntensity);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        renderer.render({ scene: mesh });
      };
      raf = requestAnimationFrame(frame);

      return () => {
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', resize);
        if (host.contains(gl.canvas)) host.removeChild(gl.canvas);
        gl.getExtension('WEBGL_lose_context')?.loseContext();
      };
    } catch {
      return undefined; // no WebGL: the ring is simply absent and the mic button still works
    }
  }, []);

  return <div ref={box} className={`relative h-full w-full ${className}`} />;
}
