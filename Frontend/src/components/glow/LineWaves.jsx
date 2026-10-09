import { useEffect, useRef } from 'react';
import { Mesh, Program, Renderer, Triangle } from 'ogl';
import { WAVES_FRAGMENT, WAVES_VERTEX } from './shaders';

// The field of flowing lines behind the Talk orb, ported from the reference build (https://growit-studio.vercel.app/).
// Three colours are mixed along the lines and cycle slowly. Fill a dark, positioned parent with it; it draws on transparent
// so the parent's gradient shows through. Respects reduced motion by drawing one still frame.
const rgb = (hex) => {
  const t = hex.replace('#', '');
  return [parseInt(t.slice(0, 2), 16) / 255, parseInt(t.slice(2, 4), 16) / 255, parseInt(t.slice(4, 6), 16) / 255];
};

export default function LineWaves({
  speed = 0.3,
  innerLineCount = 32,
  outerLineCount = 36,
  warpIntensity = 1,
  rotation = -45,
  edgeFadeWidth = 0,
  colorCycleSpeed = 1,
  brightness = 0.2,
  color1 = '#ffffff',
  color2 = '#ffffff',
  color3 = '#ffffff',
  enableMouseInteraction = true,
  mouseInfluence = 2,
  lightMode = false,
}) {
  const box = useRef(null);

  useEffect(() => {
    const host = box.current;
    if (!host) return undefined;
    const renderer = new Renderer({ alpha: true, premultipliedAlpha: false, dpr: Math.min(window.devicePixelRatio || 1, 1.5) });
    const gl = renderer.gl;
    gl.clearColor(0, 0, 0, 0);
    let program;
    let raf = 0;
    let current = [0.5, 0.5];
    let target = [0.5, 0.5];

    const onMove = (e) => {
      const r = gl.canvas.getBoundingClientRect();
      target = [(e.clientX - r.left) / r.width, 1 - (e.clientY - r.top) / r.height];
    };
    const onLeave = () => { target = [0.5, 0.5]; };
    const resize = () => {
      renderer.setSize(host.offsetWidth, host.offsetHeight);
      if (program) program.uniforms.uResolution.value = [gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height];
    };
    window.addEventListener('resize', resize);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(host);
    resize();

    program = new Program(gl, {
      vertex: WAVES_VERTEX,
      fragment: WAVES_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uResolution: { value: [gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height] },
        uSpeed: { value: speed },
        uInnerLines: { value: innerLineCount },
        uOuterLines: { value: outerLineCount },
        uWarpIntensity: { value: warpIntensity },
        uRotation: { value: (rotation * Math.PI) / 180 },
        uEdgeFadeWidth: { value: edgeFadeWidth },
        uColorCycleSpeed: { value: colorCycleSpeed },
        uBrightness: { value: brightness },
        uColor1: { value: rgb(color1) },
        uColor2: { value: rgb(color2) },
        uColor3: { value: rgb(color3) },
        uMouse: { value: new Float32Array([0.5, 0.5]) },
        uMouseInfluence: { value: mouseInfluence },
        uEnableMouse: { value: enableMouseInteraction },
        uLightMode: { value: lightMode ? 1 : 0 },
      },
    });
    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });
    host.appendChild(gl.canvas);
    if (enableMouseInteraction) {
      gl.canvas.addEventListener('mousemove', onMove);
      gl.canvas.addEventListener('mouseleave', onLeave);
    }

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const frame = (t) => {
      if (!reduced) raf = requestAnimationFrame(frame);
      program.uniforms.uTime.value = reduced ? 6 : t * 0.001;
      if (enableMouseInteraction) {
        current[0] += 0.05 * (target[0] - current[0]);
        current[1] += 0.05 * (target[1] - current[1]);
        program.uniforms.uMouse.value[0] = current[0];
        program.uniforms.uMouse.value[1] = current[1];
      } else {
        program.uniforms.uMouse.value[0] = 0.5;
        program.uniforms.uMouse.value[1] = 0.5;
      }
      renderer.render({ scene: mesh });
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      observer?.disconnect();
      if (enableMouseInteraction) {
        gl.canvas.removeEventListener('mousemove', onMove);
        gl.canvas.removeEventListener('mouseleave', onLeave);
      }
      if (host.contains(gl.canvas)) host.removeChild(gl.canvas);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, [speed, innerLineCount, outerLineCount, warpIntensity, rotation, edgeFadeWidth, colorCycleSpeed, brightness, color1, color2, color3, enableMouseInteraction, mouseInfluence, lightMode]);

  return <div ref={box} className="line-waves-container" />;
}
