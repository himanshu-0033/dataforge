import type { InterfaceStatus } from './api';

// A single, bounded fragment pass. CSS provides the orb if WebGL is unavailable.
const vertex = `attribute vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }`;
const fragment = `precision highp float;
uniform vec2 resolution;
uniform float time;
uniform float energy;
uniform float low;
uniform float high;
uniform vec3 primary;
uniform vec3 secondary;
float hash(vec3 p) {
  p = fract(p * .3183099 + vec3(.1, .2, .3));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 p) {
  vec3 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
    mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
    mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
    mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float flow(vec3 p) {
  return .58 * noise(p) + .28 * noise(p * 2.03) + .14 * noise(p * 4.01);
}
void main() {
  vec2 uv = (gl_FragCoord.xy / resolution * 2.0 - 1.0) / .84;
  float radius = length(uv);
  float edge = 1.0 - smoothstep(.97, 1.015, radius);
  vec3 sphere = vec3(uv, sqrt(max(0.0, 1.0 - dot(uv, uv))));
  float t = time * .12;
  vec3 p = sphere * (1.35 + low * .2) + vec3(t * .35, -t * .5, t * .2);
  float warp = flow(p + flow(p * .9 + t * .25) * 1.2);
  float silk = sin((sphere.y * 1.25 + sphere.x * .35 + warp * 1.5) * 4.0 + t);
  float ribbon = smoothstep(-.45, .8, silk);
  float filament = pow(max(0.0, 1.0 - abs(silk)), 5.0);
  float light = .38 + .62 * max(0.0, dot(sphere, normalize(vec3(-.5, .7, 1.2))));
  vec3 color = mix(primary * .36, primary * .95, ribbon * light);
  color = mix(color, secondary, smoothstep(.42, .78, warp) * .65);
  color += mix(primary, secondary, .4) * filament * (.22 + high * .22);
  float rim = pow(radius, 6.0) * .25;
  color += primary * rim + energy * primary * .12;
  color *= .76 + sphere.z * .24;
  gl_FragColor = vec4(color, edge);
}`;

const palettes: Record<InterfaceStatus, [number[], number[]]> = {
  LISTENING: [[.30, .68, .60], [.70, .82, .65]],
  PROCESSING: [[.48, .44, .75], [.72, .63, .85]],
  SPEAKING: [[.35, .74, .80], [.89, .67, .39]],
  PAUSED: [[.25, .40, .41], [.46, .54, .52]],
};

export function createOrbRenderer(canvas: HTMLCanvasElement) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: false, depth: false, powerPreference: 'low-power' });
  if (!gl) return null;
  const shaders: WebGLShader[] = [];
  const program = gl.createProgram();
  const buffer = gl.createBuffer();
  const dispose = () => {
    shaders.forEach(shader => gl.deleteShader(shader));
    gl.deleteBuffer(buffer);
    gl.deleteProgram(program);
  };
  if (!program || !buffer) { dispose(); return null; }
  for (const [kind, source] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]] as const) {
    const shader = gl.createShader(kind);
    if (!shader) { dispose(); return null; }
    shaders.push(shader);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { dispose(); return null; }
    gl.attachShader(program, shader);
  }
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { dispose(); return null; }
  gl.useProgram(program);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'position');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  const uniforms = Object.fromEntries(['resolution', 'time', 'energy', 'low', 'high', 'primary', 'secondary'].map(name => [name, gl.getUniformLocation(program, name)]));
  return {
    draw(time: number, status: InterfaceStatus, energy: number, low: number, high: number) {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
      gl.uniform1f(uniforms.time, time);
      gl.uniform1f(uniforms.energy, energy);
      gl.uniform1f(uniforms.low, low);
      gl.uniform1f(uniforms.high, high);
      gl.uniform3fv(uniforms.primary, palettes[status][0]);
      gl.uniform3fv(uniforms.secondary, palettes[status][1]);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    },
    dispose,
  };
}
