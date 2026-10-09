import { useEffect, useRef } from 'react';
import { Mesh, Program, Renderer, Triangle } from 'ogl';

// The app's background: slow, glassy ribbons on black whose edges split into thin spectral colour, like light through a prism.
// One fragment shader. A drifting warped field is cut by several close iso-lines; each colour channel is cut a hair apart
// (chromatic dispersion), which is what gives the orange, green and blue rims. Large parts of the field are masked to black so
// the shapes float. No pointer interaction. It pauses while the tab is hidden, holds one still frame for reduced motion, and
// removes itself if WebGL is missing so the CSS gradient underneath shows instead.
const MAX_DPR = 1.25;

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
  for (int i = 0; i < 4; i++) { v += a * noise(p); p = p * 2.02 + 9.0; a *= 0.5; }
  return v;
}

float fbm2(vec2 p) { return 0.65 * noise(p) + 0.35 * noise(p * 2.03 + 7.0); }

// Thin-film colour: a full rainbow phase, like light through oil or glass.
vec3 film(float phase) {
  vec3 c = 0.5 + 0.5 * cos(6.28318 * (phase + vec3(0.02, 0.20, 0.54))); // leans amber, teal and blue, as in the references
  return pow(c, vec3(1.35));
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float aspect = uRes.x / uRes.y;
  vec2 p = (uv - 0.5) * vec2(aspect, 1.0) * 2.0;
  float t = uTime * 0.04;

  // One smooth coordinate that sweeps across the screen and bends slowly. Its integer steps are ribbons that run together,
  // the way the bands in glass do.
  vec2 q = vec2(fbm2(p * 0.34 + vec2(t * 0.8, 1.3)), fbm2(p * 0.34 + vec2(6.1, -t * 0.7)));
  float s = dot(p, vec2(0.80, 0.55)) + 2.1 * (q.x - 0.5) + 1.5 * (q.y - 0.5);
  float band = s * 2.1 + t * 0.6;
  float id = floor(band);
  float fr = fract(band);

  // Which ribbons exist, and where on the screen they live: clusters with black between them.
  float exists = smoothstep(0.12, 0.40, hash(vec2(id, 3.7)));
  float where = smoothstep(0.30, 0.55, fbm2(p * 0.30 + vec2(2.0, -t * 0.5)));
  float live = exists * where;

  float u = (fr - 0.5) / 0.40;
  float au = abs(u);
  float inside = 1.0 - smoothstep(0.84, 1.0, au);
  float z = sqrt(max(0.0, 1.0 - min(1.0, u * u)));
  float rim = pow(1.0 - z, 2.2);
  float phase = u * 0.50 + s * 0.55 + hash(vec2(id, 9.1)) * 0.6 + t * 0.7;
  vec3 body = film(phase);
  float line = exp(-pow((au - 0.93) / 0.07, 2.0));
  vec3 edge = film(phase + 0.18) * line * 1.6;
  vec3 col = (body * (0.22 + 1.7 * rim) * inside + edge * 1.3) * live * 1.25;

  // A faint ember-to-ink wash so the black is not flat.
  float haze = where * (1.0 - live * 0.8);
  col += mix(vec3(0.15, 0.035, 0.01), vec3(0.025, 0.02, 0.14), smoothstep(0.2, 0.9, fbm2(p * 0.5 + 4.0))) * haze * 0.5;

  col *= 1.0 - 0.5 * pow(length(uv - 0.5) * 1.25, 2.0);
  col = col / (1.0 + col * 0.45);
  col += (hash(gl_FragCoord.xy + uTime) - 0.5) / 255.0;
  gl_FragColor = vec4(col, 1.0);
}
`;

export default function Prism() {
  const box = useRef(null);

  useEffect(() => {
    const host = box.current;
    if (!host) return undefined;
    let renderer;
    try {
      renderer = new Renderer({ alpha: false, antialias: false, webgl: 2, dpr: Math.min(window.devicePixelRatio || 1, MAX_DPR) });
    } catch {
      return undefined; // no WebGL: the CSS gradient underneath stays
    }
    const gl = renderer.gl;
    host.appendChild(gl.canvas);
    gl.canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';

    const program = new Program(gl, { vertex: VERT, fragment: FRAG, uniforms: { uTime: { value: 0 }, uRes: { value: [1, 1] } } });
    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

    const resize = () => {
      renderer.setSize(host.clientWidth || window.innerWidth, host.clientHeight || window.innerHeight);
      program.uniforms.uRes.value = [gl.canvas.width, gl.canvas.height];
    };
    window.addEventListener('resize', resize);
    resize();

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;
    const frame = (now) => {
      program.uniforms.uTime.value = reduced ? 40 : now * 0.001;
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

  return <div ref={box} className="prism-backdrop" />;
}
