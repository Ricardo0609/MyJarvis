// Reproduce la voz de Gemini con un efecto sutil de "IA" y mide su intensidad real para el núcleo.

let contexto = null;
let fuenteActual = null;

function obtenerContexto() {
  const Contexto = window.AudioContext || window.webkitAudioContext;
  if (!Contexto) return null;
  if (!contexto) contexto = new Contexto();
  return contexto;
}

// Debe llamarse dentro de un toque: el celular solo deja reproducir audio después de una acción del usuario.
export function desbloquearAudio() {
  const ctx = obtenerContexto();
  if (!ctx) return;
  if (ctx.state === "suspended") ctx.resume();
  const silencio = ctx.createBuffer(1, 1, 22050);
  const fuente = ctx.createBufferSource();
  fuente.buffer = silencio;
  fuente.connect(ctx.destination);
  fuente.start(0);
}

export function detenerAudio() {
  try { fuenteActual?.stop(); } catch { /* ya terminó */ }
  fuenteActual = null;
}

function decodificar(ctx, datos) {
  return new Promise((resolver, rechazar) => {
    // Safari antiguo solo acepta la forma con callbacks
    const promesa = ctx.decodeAudioData(datos, resolver, rechazar);
    promesa?.then?.(resolver, rechazar);
  });
}

// Cadena de efecto: limpia graves, da presencia, comprime y suma un eco cortísimo con brillo metálico.
function cadenaDeEfecto(ctx, destino) {
  const filtroGraves = ctx.createBiquadFilter();
  filtroGraves.type = "highpass";
  filtroGraves.frequency.value = 85;

  const presencia = ctx.createBiquadFilter();
  presencia.type = "peaking";
  presencia.frequency.value = 3200;
  presencia.Q.value = 0.9;
  presencia.gain.value = 3;

  const compresor = ctx.createDynamicsCompressor();
  compresor.threshold.value = -20;
  compresor.ratio.value = 3;

  const eco = ctx.createDelay(0.05);
  eco.delayTime.value = 0.013;
  const volumenEco = ctx.createGain();
  volumenEco.gain.value = 0.18;

  filtroGraves.connect(presencia);
  presencia.connect(compresor);
  compresor.connect(destino);
  compresor.connect(eco);
  eco.connect(volumenEco);
  volumenEco.connect(destino);
  return filtroGraves;
}

// Devuelve true si el audio se reprodujo completo.
export async function reproducirAudio(datos, { alNivel, alEmpezar, efecto = true } = {}) {
  const ctx = obtenerContexto();
  if (!ctx) return false;
  if (ctx.state === "suspended") {
    // Fuera de un toque, algunos celulares dejan esta promesa pendiente para siempre: esperamos 0.8 s máximo.
    try { await Promise.race([ctx.resume(), new Promise((r) => setTimeout(r, 800))]); } catch { /* sin permiso */ }
  }
  if (ctx.state !== "running") return false;

  const buffer = await decodificar(ctx, datos.slice(0));
  detenerAudio();

  const analizador = ctx.createAnalyser();
  analizador.fftSize = 512;
  analizador.connect(ctx.destination);

  const fuente = ctx.createBufferSource();
  fuente.buffer = buffer;
  fuente.connect(efecto ? cadenaDeEfecto(ctx, analizador) : analizador);
  fuenteActual = fuente;

  const muestras = new Uint8Array(analizador.fftSize);
  let activo = true;
  const medir = () => {
    if (!activo) return;
    analizador.getByteTimeDomainData(muestras);
    let suma = 0;
    for (const m of muestras) suma += ((m - 128) / 128) ** 2;
    alNivel?.(Math.min(1, Math.sqrt(suma / muestras.length) * 4.5));
    requestAnimationFrame(medir);
  };

  return new Promise((resolver) => {
    fuente.onended = () => {
      activo = false;
      alNivel?.(0);
      if (fuenteActual === fuente) fuenteActual = null;
      resolver(true);
    };
    alEmpezar?.();
    fuente.start();
    requestAnimationFrame(medir);
  });
}
