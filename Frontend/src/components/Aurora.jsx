import { useEffect, useRef } from 'react';
import { Mesh, Program, Renderer, Triangle } from 'ogl';

// The app's background: slow curtains of northern lights over a dark night sky, drawn by one fragment shader.
// It does not react to the cursor. It pauses while the tab is hidden, stands still for reduced motion, and removes itself if
// WebGL is missing so the CSS gradient underneath shows instead.
const MAX_DPR = 1.5;

const VERT = `
attribute vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }
`;

const FRAG = `
precision highp float;
uniform float uTime;
uniform vec2 uRes;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * noise(p); p = p * 2.03 + 11.0; a *= 0.5; }
  return v;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float aspect = uRes.x / uRes.y;
  vec2 p = vec2(uv.x * aspect, uv.y);

  float t = uTime;
  vec3 sky = mix(vec3(0.012, 0.020, 0.034), vec3(0.030, 0.055, 0.078), smoothstep(0.0, 1.0, uv.y));
  vec3 col = sky;

  // Stars, faint and few, hidden where the lights are strong.
  vec2 sp = floor(uv * vec2(uRes.x, uRes.y) / 3.0);
  float star = step(0.9985, hash(sp)) * (0.5 + 0.5 * sin(t * 2.0 + hash(sp + 3.0) * 6.28));
  col += vec3(0.7, 0.8, 0.9) * star * 0.5 * smoothstep(0.25, 0.7, uv.y);

  // Three curtains: each a slow undulating lower edge, a soft glow rising from it, and vertical rays inside.
  for (int i = 0; i < 3; i++) {
    float fi = float(i);
    float w = fbm(vec2(p.x * 0.85 + fi * 5.3, t * 0.045 + fi));
    float y0 = 0.30 + 0.13 * fi + 0.30 * (w - 0.5) + 0.035 * sin(p.x * 2.1 + t * 0.25 + fi * 1.7);
    float d = uv.y - y0;
    float env = exp(-max(d, 0.0) * (4.2 + fi)) * smoothstep(-0.07, 0.0, d);
    float rays = noise(vec2(p.x * (22.0 + fi * 6.0) + w * 8.0 + fi * 9.0, t * 0.12 + fi));
    rays = 0.35 + 0.95 * pow(rays, 1.6);
    vec3 low = mix(vec3(0.10, 0.95, 0.52), vec3(0.14, 0.82, 0.70), fi * 0.5);
    vec3 high = mix(vec3(0.18, 0.55, 0.95), vec3(0.78, 0.30, 0.55), fi * 0.45);
    vec3 c = mix(low, high, smoothstep(0.0, 0.55, d));
    col += c * env * rays * (0.52 - 0.11 * fi);
  }

  // Darken the edges a little, then dither so the dark gradient does not band.
  col *= 1.0 - 0.35 * pow(length(uv - 0.5) * 1.25, 2.0);
  col += (hash(gl_FragCoord.xy + t) - 0.5) / 255.0;
  gl_FragColor = vec4(col, 1.0);
}
`;

export default function Aurora() {
  const box = useRef(null);

  useEffect(() => {
    const host = box.current;
    if (!host) return undefined;
    let renderer;
    try {
      renderer = new Renderer({ alpha: false, antialias: false, dpr: Math.min(window.devicePixelRatio || 1, MAX_DPR) });
    } catch {
      return undefined; // no WebGL: the CSS gradient underneath stays
    }
    const gl = renderer.gl;
    host.appendChild(gl.canvas);
    gl.canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';

    const program = new Program(gl, {
      vertex: VERT,
      fragment: FRAG,
      uniforms: {
        uTime: { value: 0 },
        uRes: { value: [1, 1] },
      },
    });
    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

    const resize = () => {
      const w = host.clientWidth || window.innerWidth;
      const h = host.clientHeight || window.innerHeight;
      renderer.setSize(w, h);
      program.uniforms.uRes.value = [gl.canvas.width, gl.canvas.height];
    };
    window.addEventListener('resize', resize);
    resize();

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;
    const frame = (now) => {
      const t = now * 0.001;
      program.uniforms.uTime.value = reduced ? 8 : t;
      renderer.render({ scene: mesh });
      if (!reduced && !document.hidden) raf = requestAnimationFrame(frame);
    };
    const onVisible = () => { if (!document.hidden && !reduced) { cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); } };
    document.addEventListener('visibilitychange', onVisible);
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVisible);
      if (host.contains(gl.canvas)) host.removeChild(gl.canvas);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, []);

  return <div ref={box} className="aurora-backdrop" />;
}
