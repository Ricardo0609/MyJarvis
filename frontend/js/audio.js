// Reproduce la voz de Gemini (Charon).
//
// Se usa un único elemento <audio> que se "desbloquea" dentro de un toque: así el celular deja
// reproducir la respuesta aunque llegue segundos después (y después de usar el micrófono).
// En computadora, además, el audio pasa por un efecto sutil de IA y se mide su intensidad real
// para mover el núcleo. En celular se reproduce directo (es lo más confiable) y el nivel se simula.

const SILENCIO = "data:audio/wav;base64,UklGRkQDAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YSADAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA=="; // 0.1 s de silencio
const esCelular = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent) || matchMedia("(pointer: coarse)").matches;

const elemento = new Audio();
elemento.preload = "auto";
elemento.setAttribute("playsinline", "");

let contexto = null;
let analizador = null;
let conectado = false;
let urlActual = null;

function prepararEfecto() {
  if (esCelular || conectado) return;
  const Contexto = window.AudioContext || window.webkitAudioContext;
  if (!Contexto) return;
  try {
    contexto = contexto || new Contexto();
    const fuente = contexto.createMediaElementSource(elemento);

    const filtroGraves = contexto.createBiquadFilter();
    filtroGraves.type = "highpass";
    filtroGraves.frequency.value = 85;
    const presencia = contexto.createBiquadFilter();
    presencia.type = "peaking";
    presencia.frequency.value = 3200;
    presencia.Q.value = 0.9;
    presencia.gain.value = 3;
    const compresor = contexto.createDynamicsCompressor();
    compresor.threshold.value = -20;
    compresor.ratio.value = 3;
    const eco = contexto.createDelay(0.05);
    eco.delayTime.value = 0.013;
    const volumenEco = contexto.createGain();
    volumenEco.gain.value = 0.18;

    analizador = contexto.createAnalyser();
    analizador.fftSize = 512;

    fuente.connect(filtroGraves);
    filtroGraves.connect(presencia);
    presencia.connect(compresor);
    compresor.connect(analizador);
    compresor.connect(eco);
    eco.connect(volumenEco);
    volumenEco.connect(analizador);
    analizador.connect(contexto.destination);
    conectado = true;
  } catch {
    conectado = false; // sin efecto: el audio sale directo
  }
}

let desbloqueado = false;

export function audioDesbloqueado() {
  return desbloqueado;
}

// Llamar dentro de un toque. Solo hace falta UNA vez: después ya no se reproduce el silencio,
// porque sonar algo justo cuando se abre el micrófono hace que algunos celulares no escuchen.
export function desbloquearAudio() {
  prepararEfecto();
  if (contexto && contexto.state === "suspended") contexto.resume().catch(() => {});
  if (desbloqueado) return;
  elemento.src = SILENCIO;
  elemento.play().then(() => { desbloqueado = true; }).catch(() => {});
}

export function detenerAudio() {
  elemento.pause();
  elemento.dispatchEvent(new Event("detenido"));
}

// Devuelve true si el audio sonó completo; false si el navegador no lo dejó reproducir.
export async function reproducirAudio(datos, { alNivel, alEmpezar } = {}) {
  if (urlActual) URL.revokeObjectURL(urlActual);
  urlActual = URL.createObjectURL(new Blob([datos], { type: "audio/wav" }));
  elemento.src = urlActual;

  if (contexto && contexto.state === "suspended") {
    await Promise.race([contexto.resume().catch(() => {}), new Promise((r) => setTimeout(r, 600))]);
  }

  try {
    await elemento.play();
    desbloqueado = true;
  } catch {
    return false;
  }
  alEmpezar?.();

  const muestras = analizador ? new Uint8Array(analizador.fftSize) : null;
  let activo = true;
  let pulso = 0;
  const medir = () => {
    if (!activo) return;
    if (analizador && contexto?.state === "running") {
      analizador.getByteTimeDomainData(muestras);
      let suma = 0;
      for (const m of muestras) suma += ((m - 128) / 128) ** 2;
      alNivel?.(Math.min(1, Math.sqrt(suma / muestras.length) * 4.5));
    } else {
      pulso = 0.35 + 0.35 * Math.abs(Math.sin(performance.now() / 110)) + Math.random() * 0.2;
      alNivel?.(pulso);
    }
    requestAnimationFrame(medir);
  };
  requestAnimationFrame(medir);

  return new Promise((resolver) => {
    let cerrado = false;
    const terminar = (completo) => {
      if (cerrado) return;
      cerrado = true;
      activo = false;
      alNivel?.(0);
      // Libera el audio del teléfono para que el micrófono vuelva a funcionar en la siguiente pregunta.
      elemento.pause();
      elemento.removeAttribute("src");
      elemento.load();
      elemento.removeEventListener("ended", alTerminar);
      elemento.removeEventListener("error", alFallar);
      elemento.removeEventListener("detenido", alDetener);
      resolver(completo);
    };
    const alTerminar = () => terminar(true);
    const alDetener = () => terminar(true);
    const alFallar = () => terminar(false);
    elemento.addEventListener("ended", alTerminar);
    elemento.addEventListener("error", alFallar);
    elemento.addEventListener("detenido", alDetener);
    // Respaldo: si el navegador nunca avisa que terminó, cerramos al acabar la duración del audio.
    const duracion = Number.isFinite(elemento.duration) ? elemento.duration : 30;
    setTimeout(() => terminar(true), duracion * 1000 + 3000);
  });
}
