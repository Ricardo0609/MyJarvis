// Núcleo Lumen: el orbe 3D de JARVIS (Three.js r128 + resplandor).
//
// Se dibuja en un lienzo a pantalla completa, pero se coloca y escala siguiendo la caja del
// elemento "objetivo" (#orbe). Así, cuando el CSS mueve o encoge #orbe, el modelo 3D lo sigue
// cuadro por cuadro.
//
// API:
//   const lumen = crearLumen(lienzo, { objetivo, alTocar });
//   lumen.modo("idle" | "listen" | "speak" | "think")
//   lumen.nivel(0..1)   → intensidad real de la voz (opcional)
//   lumen.ok            → false si el navegador no tiene WebGL

export function crearLumen(canvas, { objetivo, alTocar } = {}) {
  const THREE = window.THREE;
  const nulo = { ok: false, modo() {}, nivel() {} };
  if (!THREE || !canvas || !objetivo) return nulo;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  } catch {
    return nulo;
  }

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const timeScale = reduceMotion ? 0.35 : 1;
  let pixelRatio = Math.min(window.devicePixelRatio || 1, 2);

  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(0x0a0306, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
  const DIST_CAMARA = 10;
  const root = new THREE.Group();
  scene.add(root);

  const COL = {
    primary: new THREE.Color("#ff3355"),
    glint: new THREE.Color("#ff9ab8"),
    white: new THREE.Color("#fff0f4"),
    magenta: new THREE.Color("#c86bff"),
    deep: new THREE.Color("#c41c45"),
  };

  // Uniformes compartidos por los shaders del orbe
  const U = {
    uTime: { value: 0 },
    uEnergy: { value: 0.35 },
    uFlash: { value: 0.25 },
    uPR: { value: pixelRatio },
    uColA: { value: COL.primary.clone() },
    uColB: { value: COL.glint.clone() },
  };
  const uPRFondo = { value: pixelRatio }; // el polvo de fondo no se encoge con el orbe

  const BREATHE = `
    uniform float uTime;
    uniform float uEnergy;
    vec3 breathe(vec3 p){
      float n = sin(p.x*2.3 + uTime*1.1) * sin(p.y*2.9 - uTime*0.8) * sin(p.z*2.6 + uTime*0.7);
      return p * (1.0 + n*0.05*(0.4 + uEnergy) + sin(uTime*1.6)*0.012*uEnergy);
    }
  `;

  function rand(seed) { // generador determinista para que el modelo sea siempre igual
    let s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }
  const rnd = rand(20261028);

  function glowTexture() {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d");
    const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, "rgba(255,255,255,1)");
    gr.addColorStop(0.18, "rgba(255,255,255,0.65)");
    gr.addColorStop(0.45, "rgba(255,255,255,0.14)");
    gr.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = gr;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }
  const GLOW = glowTexture();

  /* ---------- 1. Capa de nodos (esfera de Fibonacci) ---------- */
  const SHELL_R = 1.8;
  const SHELL_N = 2200;
  const shellPts = [];
  {
    const ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < SHELL_N; i++) {
      const y = 1 - ((i + 0.5) / SHELL_N) * 2;
      const r = Math.sqrt(1 - y * y);
      const th = ga * i;
      const rr = SHELL_R * (1 + (rnd() - 0.5) * 0.05);
      shellPts.push(new THREE.Vector3(Math.cos(th) * r * rr, y * rr, Math.sin(th) * r * rr));
    }
  }
  {
    const pos = new Float32Array(SHELL_N * 3);
    const ar = new Float32Array(SHELL_N);
    shellPts.forEach((p, i) => { pos.set([p.x, p.y, p.z], i * 3); ar[i] = rnd(); });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aRand", new THREE.BufferAttribute(ar, 1));
    const mat = new THREE.ShaderMaterial({
      uniforms: { uTime: U.uTime, uEnergy: U.uEnergy, uPR: U.uPR, uColA: U.uColA, uColB: U.uColB, uSize: { value: 3.9 } },
      vertexShader: BREATHE + `
        attribute float aRand;
        uniform float uPR; uniform float uSize;
        varying float vA; varying float vM;
        void main(){
          vec3 n = normalize(position);
          vec3 p = breathe(position);
          float scanY = sin(uTime*0.55);
          float scan = exp(-pow((n.y - scanY)*6.0, 2.0));
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vec3 nv = normalize(normalMatrix * n);
          float facing = 0.22 + 0.78*smoothstep(-0.5, 0.7, nv.z);
          float tw = 0.6 + 0.4*sin(uTime*2.3 + aRand*60.0);
          vA = facing * tw * (0.45 + 0.9*scan);
          vM = scan;
          gl_Position = projectionMatrix * mv;
          gl_PointSize = uSize * uPR * (0.7 + 0.6*aRand + 1.1*scan) * (9.5 / -mv.z);
        }`,
      fragmentShader: `
        uniform vec3 uColA; uniform vec3 uColB;
        varying float vA; varying float vM;
        void main(){
          float d = length(gl_PointCoord - 0.5);
          float a = smoothstep(0.5, 0.0, d); a *= a;
          gl_FragColor = vec4(mix(uColA, uColB, vM), a * vA);
        }`,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    root.add(new THREE.Points(geo, mat));
  }

  /* ---------- 2. Red de sinapsis con pulsos viajeros ---------- */
  {
    const sub = shellPts.filter((_, i) => i % 3 === 0);
    const seen = new Set();
    const segs = [];
    for (let i = 0; i < sub.length; i++) {
      const near = [];
      for (let j = 0; j < sub.length; j++) {
        if (i === j) continue;
        const d = sub[i].distanceToSquared(sub[j]);
        if (d < 0.16) near.push([d, j]);
      }
      near.sort((a, b) => a[0] - b[0]);
      for (let k = 0; k < Math.min(2, near.length); k++) {
        const j = near[k][1];
        const key = i < j ? i + "-" + j : j + "-" + i;
        if (seen.has(key)) continue;
        seen.add(key);
        segs.push([sub[i], sub[j]]);
      }
    }
    const pos = new Float32Array(segs.length * 6);
    const at = new Float32Array(segs.length * 2);
    const ar = new Float32Array(segs.length * 2);
    segs.forEach((s, i) => {
      pos.set([s[0].x, s[0].y, s[0].z, s[1].x, s[1].y, s[1].z], i * 6);
      at[i * 2] = 0; at[i * 2 + 1] = 1;
      const r = rnd(); ar[i * 2] = r; ar[i * 2 + 1] = r;
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aT", new THREE.BufferAttribute(at, 1));
    geo.setAttribute("aRand", new THREE.BufferAttribute(ar, 1));
    const mat = new THREE.ShaderMaterial({
      uniforms: { uTime: U.uTime, uEnergy: U.uEnergy, uFlash: U.uFlash, uColA: U.uColA, uColB: U.uColB },
      vertexShader: BREATHE + `
        attribute float aT; attribute float aRand;
        varying float vT; varying float vR; varying float vFace;
        void main(){
          vec3 p = breathe(position) * 1.002;
          vec3 nv = normalize(normalMatrix * normalize(position));
          vFace = 0.18 + 0.82*smoothstep(-0.4, 0.7, nv.z);
          vT = aT; vR = aRand;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }`,
      fragmentShader: `
        uniform float uTime; uniform float uFlash;
        uniform vec3 uColA; uniform vec3 uColB;
        varying float vT; varying float vR; varying float vFace;
        void main(){
          float isLive = step(1.0 - uFlash*0.55, fract(vR*13.7));
          float head = fract(uTime*(0.3 + vR*0.4) + vR*7.0);
          float pulse = smoothstep(0.2, 0.0, abs(vT - head)) * isLive;
          float fire = pow(0.5 + 0.5*sin(uTime*(0.6 + vR) + vR*90.0), 14.0);
          float a = vFace * (0.07 + 0.35*fire*uFlash + 0.95*pulse);
          gl_FragColor = vec4(mix(uColA, uColB, pulse), a);
        }`,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    root.add(new THREE.LineSegments(geo, mat));
  }

  /* ---------- 3. Núcleo central ---------- */
  const core = new THREE.Group();
  root.add(core);
  const icoMat = new THREE.LineBasicMaterial({ color: COL.primary, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false });
  const ico = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(0.62, 1)), icoMat);
  core.add(ico);
  const octaMat = new THREE.LineBasicMaterial({ color: COL.glint, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false });
  const octa = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.OctahedronGeometry(0.34, 0)), octaMat);
  core.add(octa);

  function simplePoints(count, rMin, rMax, size, color, alpha, maxSize, uPR) {
    const pos = new Float32Array(count * 3);
    const ar = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const v = new THREE.Vector3(rnd() * 2 - 1, rnd() * 2 - 1, rnd() * 2 - 1).normalize();
      v.multiplyScalar(rMin + (rMax - rMin) * Math.pow(rnd(), 0.6));
      pos.set([v.x, v.y, v.z], i * 3);
      ar[i] = rnd();
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aRand", new THREE.BufferAttribute(ar, 1));
    const mat = new THREE.ShaderMaterial({
      uniforms: { uTime: U.uTime, uPR, uSize: { value: size }, uMax: { value: maxSize }, uColor: { value: color }, uAlpha: { value: alpha } },
      vertexShader: `
        attribute float aRand;
        uniform float uTime; uniform float uPR; uniform float uSize; uniform float uMax;
        varying float vA;
        void main(){
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * mv;
          gl_PointSize = min(uSize * uPR * (0.5 + aRand) * (9.5 / -mv.z), uMax * uPR);
          vA = (0.45 + 0.55*sin(uTime*1.7 + aRand*50.0)) * smoothstep(0.5, 3.0, -mv.z);
        }`,
      fragmentShader: `
        uniform vec3 uColor; uniform float uAlpha;
        varying float vA;
        void main(){
          float d = length(gl_PointCoord - 0.5);
          float a = smoothstep(0.5, 0.0, d); a *= a;
          gl_FragColor = vec4(uColor, a * vA * uAlpha);
        }`,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    return new THREE.Points(geo, mat);
  }
  const swirl = simplePoints(520, 0.12, 0.58, 3.0, COL.white, 0.9, 6, U.uPR);
  core.add(swirl);

  const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: COL.white, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false }));
  coreGlow.scale.setScalar(1.25);
  core.add(coreGlow);
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: COL.primary, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, depthWrite: false }));
  halo.scale.setScalar(6.5);
  root.add(halo);

  /* ---------- 4. Anillos graduados tipo giroscopio ---------- */
  function lineMat(color, opacity) {
    return new THREE.LineBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });
  }
  function inArcs(deg, arcs) { return arcs.some((a) => deg >= a[0] && deg <= a[1]); }
  function graduatedRing(o) {
    const g = new THREE.Group();
    const arcPos = [];
    o.arcs.forEach(([a0, a1]) => {
      const steps = Math.max(8, Math.round((a1 - a0) / 2));
      for (let s = 0; s < steps; s++) {
        const t0 = THREE.MathUtils.degToRad(a0 + (a1 - a0) * s / steps);
        const t1 = THREE.MathUtils.degToRad(a0 + (a1 - a0) * (s + 1) / steps);
        arcPos.push(Math.cos(t0) * o.r, Math.sin(t0) * o.r, 0, Math.cos(t1) * o.r, Math.sin(t1) * o.r, 0);
      }
    });
    const ag = new THREE.BufferGeometry();
    ag.setAttribute("position", new THREE.Float32BufferAttribute(arcPos, 3));
    g.add(new THREE.LineSegments(ag, lineMat(o.color, o.opacity)));
    if (o.ticks) {
      const tp = [];
      for (let i = 0; i < o.ticks; i++) {
        const deg = i * 360 / o.ticks;
        if (!inArcs(deg, o.arcs)) continue;
        const major = i % o.majorEvery === 0;
        const len = (major ? o.majorLen : o.tickLen) * o.dir;
        const t = THREE.MathUtils.degToRad(deg);
        tp.push(Math.cos(t) * o.r, Math.sin(t) * o.r, 0, Math.cos(t) * (o.r + len), Math.sin(t) * (o.r + len), 0);
      }
      const tg = new THREE.BufferGeometry();
      tg.setAttribute("position", new THREE.Float32BufferAttribute(tp, 3));
      g.add(new THREE.LineSegments(tg, lineMat(o.color, o.opacity * 0.85)));
    }
    if (o.markers) {
      o.markers.forEach((deg) => {
        const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: COL.white, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
        const t = THREE.MathUtils.degToRad(deg);
        s.position.set(Math.cos(t) * o.r, Math.sin(t) * o.r, 0);
        s.scale.setScalar(0.22);
        g.add(s);
      });
    }
    const holder = new THREE.Group();
    holder.rotation.set(o.tilt[0], o.tilt[1], o.tilt[2]);
    holder.add(g);
    root.add(holder);
    return g;
  }
  const ringA = graduatedRing({ r: 2.18, arcs: [[0, 96], [112, 204], [218, 334]], ticks: 72, majorEvery: 6, tickLen: 0.06, majorLen: 0.15, dir: 1, color: COL.primary, opacity: 0.75, tilt: [1.22, 0.28, 0], markers: [96, 204] });
  const ringB = graduatedRing({ r: 2.42, arcs: [[18, 162], [198, 342]], ticks: 120, majorEvery: 10, tickLen: 0.05, majorLen: 0.12, dir: -1, color: COL.glint, opacity: 0.55, tilt: [-0.48, 0, 0.82], markers: [18, 198] });
  const dashes = [];
  for (let d = 0; d < 360; d += 7.5) dashes.push([d, d + 3.2]);
  const ringC = graduatedRing({ r: 2.66, arcs: dashes, ticks: 0, color: COL.deep, opacity: 0.7, tilt: [0.18, 1.1, 0.12], markers: [0, 120, 240] });

  /* ---------- 5. Meridiano de escaneo + plano de barrido ---------- */
  const scanner = new THREE.Group();
  root.add(scanner);
  {
    const pts = [], cols = [];
    const n = 90;
    for (let i = 0; i <= n; i++) {
      const t = -Math.PI / 2 + Math.PI * i / n;
      pts.push(Math.cos(t) * 1.97, Math.sin(t) * 1.97, 0);
      const f = Math.sin(Math.PI * i / n);
      cols.push(COL.glint.r * f, COL.glint.g * f, COL.glint.b * f);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
    const m = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false });
    scanner.add(new THREE.Line(g, m));
    const ghost = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthWrite: false }));
    ghost.rotation.y = 0.12;
    scanner.add(ghost);
  }
  const scanRing = (function () {
    const pts = [];
    for (let i = 0; i <= 128; i++) { const t = i / 128 * Math.PI * 2; pts.push(Math.cos(t), 0, Math.sin(t)); }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    const l = new THREE.Line(g, lineMat(COL.glint, 0.35));
    root.add(l);
    return l;
  })();

  /* ---------- 6. Espectro de voz ecuatorial ---------- */
  const BARS = 160, BAR_R = 1.99;
  const specPos = new Float32Array(BARS * 6);
  const specCol = new Float32Array(BARS * 6);
  const specGeo = new THREE.BufferGeometry();
  specGeo.setAttribute("position", new THREE.BufferAttribute(specPos, 3));
  specGeo.setAttribute("color", new THREE.BufferAttribute(specCol, 3));
  root.add(new THREE.LineSegments(specGeo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false })));

  /* ---------- 7. Satélites en órbita con estela ---------- */
  const TRAIL = 46;
  const sats = [
    { r: 2.95, speed: 0.55, phase: 0.0, tilt: [0.4, 0.0, 0.3] },
    { r: 3.12, speed: -0.42, phase: 2.1, tilt: [-0.9, 0.6, 0.0] },
    { r: 3.28, speed: 0.33, phase: 4.0, tilt: [1.4, -0.3, 0.5] },
    { r: 2.84, speed: 0.68, phase: 5.2, tilt: [-0.2, 1.2, -0.7] },
  ].map((s) => {
    s.q = new THREE.Quaternion().setFromEuler(new THREE.Euler(s.tilt[0], s.tilt[1], s.tilt[2]));
    const pos = new Float32Array(TRAIL * 3);
    const col = new Float32Array(TRAIL * 3);
    for (let j = 0; j < TRAIL; j++) {
      const f = Math.pow(1 - j / (TRAIL - 1), 1.6);
      col.set([COL.primary.r * f, COL.primary.g * f, COL.primary.b * f], j * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    s.trail = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    s.node = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: COL.white, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    s.node.scale.setScalar(0.26);
    root.add(s.trail, s.node);
    return s;
  });
  const tmpV = new THREE.Vector3();

  /* ---------- 8. Polvo de fondo con paralaje ---------- */
  const dust = simplePoints(700, 11, 22, 2.2, COL.glint, 0.55, 3, uPRFondo);
  scene.add(dust);

  /* ---------- Post-proceso: resplandor ---------- */
  let composer = null;
  try {
    if (THREE.EffectComposer && THREE.RenderPass && THREE.UnrealBloomPass) {
      composer = new THREE.EffectComposer(renderer);
      composer.addPass(new THREE.RenderPass(scene, camera));
      composer.addPass(new THREE.UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.9, 0.55, 0.08));
    }
  } catch {
    composer = null;
  }

  /* ---------- Estados (los controla la app) ---------- */
  const MODES = {
    idle:   { speed: 0.55, energy: 0.35, amp: 0.07, talk: 0.0, sweep: 0.0,  flash: 0.25, ring: 0.6, core: 0.9,  colB: COL.glint },
    listen: { speed: 0.85, energy: 0.6,  amp: 0.2,  talk: 0.4, sweep: 0.0,  flash: 0.45, ring: 0.9, core: 1.05, colB: COL.glint },
    speak:  { speed: 1.1,  energy: 1.0,  amp: 0.44, talk: 1.0, sweep: 0.0,  flash: 0.6,  ring: 1.2, core: 1.45, colB: COL.white },
    think:  { speed: 1.9,  energy: 0.75, amp: 0.1,  talk: 0.0, sweep: 0.32, flash: 1.0,  ring: 3.2, core: 1.15, colB: COL.magenta },
  };
  const cur = Object.assign({}, MODES.idle);
  let target = MODES.idle;
  let nivelVoz = 0;

  /* ---------- Giro con el dedo o el mouse (y toque = hablar) ---------- */
  const AX_Y = new THREE.Vector3(0, 1, 0), AX_X = new THREE.Vector3(1, 0, 0);
  const qA = new THREE.Quaternion(), qB = new THREE.Quaternion();
  const HOME = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.32, -0.55, 0, "YXZ"));
  root.quaternion.copy(HOME);
  function rotateBy(yaw, pitch) {
    qA.setFromAxisAngle(AX_Y, yaw);
    qB.setFromAxisAngle(AX_X, pitch);
    root.quaternion.premultiply(qA).premultiply(qB).normalize();
  }

  const autoRotate = !reduceMotion;
  let velX = 0, velY = 0, lastInteract = -1e9;
  let arrastrando = null; // { id, x, y, x0, y0, t0 }
  const now = () => performance.now();

  function dentroDelOrbe(x, y) {
    const r = objetivo.getBoundingClientRect();
    return Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2)) <= r.width / 2;
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (arrastrando) return;
    try { canvas.setPointerCapture(e.pointerId); } catch { /* sin captura */ }
    arrastrando = { id: e.pointerId, x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: now() };
    velX = velY = 0;
    lastInteract = now();
    canvas.classList.add("arrastrando");
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!arrastrando || arrastrando.id !== e.pointerId) return;
    const dx = (e.clientX - arrastrando.x) * 0.0065, dy = (e.clientY - arrastrando.y) * 0.0065;
    arrastrando.x = e.clientX; arrastrando.y = e.clientY;
    rotateBy(dx, dy);
    velX = velX * 0.4 + dx * 0.6;
    velY = velY * 0.4 + dy * 0.6;
    lastInteract = now();
  });
  function soltar(e) {
    if (!arrastrando || arrastrando.id !== e.pointerId) return;
    const movido = Math.hypot(e.clientX - arrastrando.x0, e.clientY - arrastrando.y0);
    const fueToque = e.type === "pointerup" && movido < 8 && now() - arrastrando.t0 < 450;
    arrastrando = null;
    canvas.classList.remove("arrastrando");
    if (fueToque && dentroDelOrbe(e.clientX, e.clientY)) alTocar?.();
  }
  canvas.addEventListener("pointerup", soltar);
  canvas.addEventListener("pointercancel", soltar);

  /* ---------- Tamaño y encuadre ---------- */
  const FIT_R = 3.65; // radio del modelo completo (con satélites) que debe caber en #orbe
  let ancho = 1, alto = 1;
  function resize() {
    ancho = window.innerWidth;
    alto = Math.max(1, window.innerHeight);
    pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(pixelRatio);
    renderer.setSize(ancho, alto, false);
    camera.aspect = ancho / alto;
    camera.position.set(0, 0, DIST_CAMARA);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    uPRFondo.value = pixelRatio;
    if (composer) { composer.setPixelRatio(pixelRatio); composer.setSize(ancho, alto); }
  }
  window.addEventListener("resize", resize);
  resize();

  // Coloca y escala el modelo para que llene exactamente la caja de #orbe.
  function encuadrar() {
    const r = objetivo.getBoundingClientRect();
    const radio = Math.max(6, r.width / 2);
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const pxPorUnidad = (alto / 2) / (DIST_CAMARA * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
    const escala = radio / (FIT_R * pxPorUnidad);
    root.scale.setScalar(escala);
    U.uPR.value = pixelRatio * escala;
    camera.setViewOffset(ancho, alto, ancho / 2 - cx, alto / 2 - cy, ancho, alto);
  }

  /* ---------- Bucle de animación ---------- */
  const qId = new THREE.Quaternion();
  let animT = 0, last = now();

  function frame() {
    const t = now();
    const dt = Math.min(0.05, (t - last) / 1000);
    last = t;

    const k = 1 - Math.exp(-dt * 3);
    ["speed", "energy", "amp", "talk", "sweep", "flash", "ring", "core"].forEach((p) => { cur[p] += (target[p] - cur[p]) * k; });
    U.uColB.value.lerp(target.colB, k);

    animT += dt * cur.speed * timeScale;
    U.uTime.value = animT;
    U.uEnergy.value = cur.energy;
    U.uFlash.value = cur.flash;

    // Envolvente tipo sílabas; si la app manda el nivel real de la voz, se mezcla
    let syl = Math.min(1, 0.2 + 0.85 * Math.abs(Math.sin(animT * 4.3) * Math.sin(animT * 1.9 + 0.6)) + 0.12 * Math.sin(animT * 9.7));
    if (nivelVoz > 0) syl = 0.4 * syl + 0.6 * nivelVoz;

    // Núcleo
    ico.rotation.x += dt * 0.35 * cur.speed * timeScale;
    ico.rotation.y += dt * 0.5 * cur.speed * timeScale;
    octa.rotation.y -= dt * 1.1 * cur.speed * timeScale;
    octa.rotation.z += dt * 0.6 * cur.speed * timeScale;
    swirl.rotation.y += dt * 1.4 * cur.speed * timeScale;
    const beat = 1 + 0.07 * Math.sin(animT * 2.6) * (0.5 + cur.energy);
    const voice = 1 + (syl - 0.5) * 0.35 * cur.talk;
    coreGlow.scale.setScalar(1.0 * cur.core * beat * voice);
    ico.scale.setScalar(beat);
    halo.material.opacity = 0.15 + 0.08 * cur.core;
    icoMat.color.copy(U.uColA.value).lerp(U.uColB.value, 0.25 * cur.sweep / 0.32);

    // Anillos
    ringA.rotation.z += dt * 0.25 * cur.ring * timeScale;
    ringB.rotation.z -= dt * 0.17 * cur.ring * timeScale;
    ringC.rotation.z += dt * 0.08 * cur.ring * timeScale;

    // Escáner
    scanner.rotation.y = animT * 0.7;
    const sy = Math.sin(animT * 0.55);
    scanRing.position.y = sy * SHELL_R;
    scanRing.scale.setScalar(Math.max(0.001, Math.sqrt(1 - sy * sy) * SHELL_R * 1.02));
    scanRing.material.color.copy(U.uColB.value);

    // Espectro de voz
    const sweepAng = animT * 2.2;
    const cA = U.uColA.value, cB = U.uColB.value;
    for (let i = 0; i < BARS; i++) {
      const a = i / BARS * Math.PI * 2;
      const shape = Math.abs(Math.sin(a * 5 + animT * 2.2) * Math.cos(a * 11 - animT * 3.7) + 0.45 * Math.sin(a * 23 + animT * 6.1));
      const breath = 0.6 + 0.4 * Math.sin(animT * 1.3);
      const env = (1 - cur.talk) * breath + cur.talk * syl;
      const d = Math.atan2(Math.sin(a - sweepAng), Math.cos(a - sweepAng));
      const sw = Math.exp(-d * d * 10) * cur.sweep;
      const h = 0.015 + cur.amp * Math.pow(shape, 1.3) * env + sw;
      const ca = Math.cos(a), sa = Math.sin(a);
      specPos[i * 6] = ca * BAR_R; specPos[i * 6 + 1] = 0; specPos[i * 6 + 2] = sa * BAR_R;
      specPos[i * 6 + 3] = ca * (BAR_R + h); specPos[i * 6 + 4] = 0; specPos[i * 6 + 5] = sa * (BAR_R + h);
      specCol[i * 6] = cA.r * 0.35; specCol[i * 6 + 1] = cA.g * 0.35; specCol[i * 6 + 2] = cA.b * 0.35;
      specCol[i * 6 + 3] = cB.r; specCol[i * 6 + 4] = cB.g; specCol[i * 6 + 5] = cB.b;
    }
    specGeo.attributes.position.needsUpdate = true;
    specGeo.attributes.color.needsUpdate = true;

    // Satélites
    sats.forEach((s) => {
      const arr = s.trail.geometry.attributes.position.array;
      const base = animT * s.speed * 1.4 + s.phase;
      const dirSign = Math.sign(s.speed) || 1;
      for (let j = 0; j < TRAIL; j++) {
        const a = base - j * 0.018 * dirSign;
        const rr = s.r * (1 + 0.025 * Math.sin(a * 3));
        tmpV.set(Math.cos(a) * rr, 0, Math.sin(a) * rr).applyQuaternion(s.q);
        arr[j * 3] = tmpV.x; arr[j * 3 + 1] = tmpV.y; arr[j * 3 + 2] = tmpV.z;
        if (j === 0) s.node.position.copy(tmpV);
      }
      s.trail.geometry.attributes.position.needsUpdate = true;
    });

    // Inercia y giro automático
    if (!arrastrando) {
      if (Math.abs(velX) + Math.abs(velY) > 1e-5) {
        rotateBy(velX * dt * 60, velY * dt * 60);
        const decay = Math.pow(0.93, dt * 60);
        velX *= decay; velY *= decay;
      }
      if (autoRotate && t - lastInteract > 1600) rotateBy(dt * 0.16 * timeScale * (0.8 + cur.speed * 0.3), 0);
    }

    dust.quaternion.copy(qId).slerp(root.quaternion, 0.25);
    dust.rotateY(animT * 0.01);

    encuadrar();
    if (composer) composer.render(); else renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  return {
    ok: true,
    modo(clave) { if (MODES[clave]) target = MODES[clave]; },
    nivel(valor) { nivelVoz = Math.max(0, Math.min(1, valor || 0)); },
  };
}
