import { api, clave, ErrorClave } from "./api.js";
import { desbloquearAudio, reproducirAudio } from "./audio.js";
import { crearOrbe } from "./orbe.js";
import { mostrarEnPanel, ocultarPanel } from "./panel.js";
import { escucha, voz } from "./voz.js";

const $ = (id) => document.getElementById(id);
const textoEstado = $("estado");
const transcripcion = $("transcripcion");
const leyendas = document.querySelector(".leyendas");
const accion = $("accion");
const accionTexto = $("accion-texto");
const formTeclado = $("form-teclado");
const entradaTexto = $("entrada-texto");
const dialogoClave = $("dialogo-clave");
const aviso = $("aviso");

const orbe = crearOrbe({ alTocar: () => alTocarMicrofono() }); // tocar el Núcleo Lumen = hablar
let ocupado = false;
let temporizadorAviso;
let vozGeminiDisponible = false;

const ESTADOS = {
  reposo: "Toca el núcleo para hablar",
  escuchando: "Escuchando…",
  pensando: "Procesando…",
  hablando: "",
};
const ESTADOS_CORTOS = {
  reposo: "En reposo",
  escuchando: "Escuchando",
  pensando: "Procesando",
  hablando: "Hablando",
  error: "Atención",
};
const estadoCorto = $("estado-corto");

function ponerEstado(estado, texto) {
  orbe.estado(estado);
  textoEstado.textContent = texto ?? ESTADOS[estado] ?? "";
  estadoCorto.textContent = ESTADOS_CORTOS[estado] || "";
}

// Pone el subtítulo y, si es largo, encoge el núcleo para que el texto no choque con los botones.
let revisionSubtitulo;
function subtitulo(texto) {
  transcripcion.textContent = texto;
  leyendas.scrollTop = 0;
  // Un texto corto siempre cabe: el núcleo regresa a su tamaño normal.
  if (texto.length < 90) document.body.classList.remove("texto-largo");
  acomodarSubtitulo();
}

function acomodarSubtitulo() {
  const desborda = () => leyendas.scrollHeight > leyendas.clientHeight + 2;
  if (transcripcion.textContent && desborda()) document.body.classList.add("texto-largo");
  // El núcleo tarda ~0.7 s en moverse: después revisamos si todavía hay que desplazar el texto.
  clearTimeout(revisionSubtitulo);
  revisionSubtitulo = setTimeout(() => leyendas.classList.toggle("desborda", desborda()), 750);
  leyendas.classList.toggle("desborda", desborda());
}

window.addEventListener("resize", () => {
  document.body.classList.remove("texto-largo");
  acomodarSubtitulo();
});

// ---------------------------------------------------------------------------
// Botón de acción (abrir o conectar Spotify)
// ---------------------------------------------------------------------------

let detenerEspera = null;

function mostrarAccion(abrir) {
  accionTexto.textContent = abrir.texto || "Abrir";
  accion.href = abrir.url;
  const externa = /^https?:\/\//.test(abrir.url) && !abrir.url.startsWith(location.origin);
  accion.target = externa ? "_blank" : "_self";
  accion.dataset.reintentar = abrir.reintentar ? "1" : "";
  accion.hidden = false;
  document.body.classList.add("con-accion");
  acomodarSubtitulo();
}

function ocultarAccion() {
  accion.hidden = true;
  document.body.classList.remove("con-accion");
}

accion.addEventListener("click", () => {
  if (accion.dataset.reintentar === "1") esperarSpotify();
  setTimeout(ocultarAccion, 300);
});

// Después de abrir Spotify: en cuanto aparezca como dispositivo, empieza a sonar lo que pediste.
function esperarSpotify() {
  detenerEspera?.();
  const inicio = Date.now();
  let enCurso = false;
  const intentar = async () => {
    if (enCurso) return;
    if (Date.now() - inicio > 90000) return detener();
    enCurso = true;
    try {
      const r = await api.spotifyReintentar();
      if (r.ok) {
        detener();
        mostrarAviso(`Reproduciendo ${r.nombre}${r.reproduciendo_en ? ` en ${r.reproduciendo_en}` : ""}.`, 6000);
      } else if (r.motivo === "nada pendiente") {
        detener();
      }
    } catch { /* se vuelve a intentar */ } finally {
      enCurso = false;
    }
  };
  const temporizador = setInterval(intentar, 4000);
  const alVolver = () => { if (document.visibilityState === "visible") intentar(); };
  document.addEventListener("visibilitychange", alVolver);
  function detener() {
    clearInterval(temporizador);
    document.removeEventListener("visibilitychange", alVolver);
    detenerEspera = null;
  }
  detenerEspera = detener;
}

function mostrarAviso(mensaje, ms = 4500) {
  aviso.textContent = mensaje;
  aviso.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, ms);
}

function cerrarPanel() {
  orbe.mostrar(false);
  setTimeout(() => { if (!document.body.classList.contains("mostrando")) ocultarPanel(); }, 550);
}

// ---------------------------------------------------------------------------
// Voz: siempre Charon (Gemini). Solo si el servidor no tiene Gemini se usa la del navegador.
// ---------------------------------------------------------------------------

function configurarVoz() {
  voz.motorRemoto = vozGeminiDisponible ? (texto) => api.voz(texto) : null;
}

// Habla y mueve el núcleo: se queda "pensando" mientras se genera el audio y pasa a "hablando" al sonar.
async function decir(texto) {
  const sono = await voz.hablar(texto, {
    alNivel: (n) => orbe.nivel(n),
    alEmpezar: () => ponerEstado("hablando"),
  });
  if (!sono && voz.motorRemoto) {
    mostrarAviso(`No sonó la voz de Charon: ${voz.ultimoError || "el navegador no dejó reproducir el audio"}.`, 9000);
  }
  return sono;
}

// ---------------------------------------------------------------------------
// Flujo principal: escuchar → pensar → hablar (y mostrar si hace falta)
// ---------------------------------------------------------------------------

async function enviar(texto) {
  texto = texto.trim();
  if (!texto || ocupado) return;
  ocupado = true;
  ocultarAccion();
  subtitulo(texto);
  ponerEstado("pensando");
  const enLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
  const esperas = [
    setTimeout(() => ponerEstado("pensando", enLocal ? "Sigo pensando…" : "Despertando el servidor…"), 8000),
    setTimeout(() => ponerEstado("pensando", "Está tardando más de lo normal…"), 30000),
  ];
  const limpiarEsperas = () => esperas.forEach(clearTimeout);

  try {
    const respuesta = await api.comando(texto);
    limpiarEsperas();
    if (respuesta.aviso) mostrarAviso(respuesta.aviso, 9000);
    $("conexion").textContent = respuesta.cerebro === "gemini" ? "Gemini" : "Claude";

    if (respuesta.abrir) mostrarAccion(respuesta.abrir);

    if (respuesta.mostrar) {
      mostrarEnPanel(respuesta.mostrar);
      requestAnimationFrame(() => orbe.mostrar(true));
    } else if (document.body.classList.contains("mostrando")) {
      cerrarPanel();
    }

    ponerEstado("pensando", vozGeminiDisponible ? "Preparando la voz…" : "");
    subtitulo(respuesta.voz); // la respuesta queda escrita como subtítulo
    await decir(respuesta.voz);
    ponerEstado("reposo");
  } catch (error) {
    limpiarEsperas();
    if (error instanceof ErrorClave) {
      ponerEstado("reposo");
      pedirClave("La clave guardada no es correcta.");
    } else {
      ponerEstado("error", error.message || "Algo falló");
      mostrarAviso(`${error.message || "Algo falló"}. Revisa la terminal donde corre el servidor.`, 10000);
      setTimeout(() => ponerEstado("reposo"), 4000);
    }
  } finally {
    ocupado = false;
  }
}

function escuchar() {
  if (!escucha.soportada) {
    abrirTeclado();
    mostrarAviso("Este navegador no reconoce voz. Usa Chrome en PC/Android o Safari en iPhone; mientras, puedes escribir.", 7000);
    return;
  }
  subtitulo("");
  ponerEstado("escuchando");
  escucha.iniciar({
    alParcial: (texto) => subtitulo(texto),
    alTerminar: (texto) => {
      if (texto) return enviar(texto);
      if (ocupado) return;
      // No se captó nada: lo decimos en lugar de quedarnos callados.
      const motivo = { "no-speech": "no escuché nada", "aborted": "el micrófono se cerró", "audio-capture": "no hay acceso al micrófono", "network": "falló la conexión del dictado" }[escucha.ultimoError];
      ponerEstado("reposo", "No te escuché. Toca el núcleo e inténtalo de nuevo");
      if (escucha.ultimoError) mostrarAviso(`No te escuché (${motivo || escucha.ultimoError}).`, 6000);
      setTimeout(() => { if (document.body.dataset.estado === "reposo") ponerEstado("reposo"); }, 4000);
    },
    alError: (codigo) => {
      const mensajes = {
        "not-allowed": "Necesito permiso para usar el micrófono",
        "service-not-allowed": "Necesito permiso para usar el micrófono",
        "audio-capture": "No encuentro un micrófono",
        "network": "El reconocimiento de voz necesita internet",
      };
      ponerEstado("error", mensajes[codigo] || "No pude escucharte");
      setTimeout(() => ponerEstado("reposo"), 3500);
    },
  });
}

function alTocarMicrofono() {
  voz.desbloquear();
  const estado = document.body.dataset.estado;
  if (estado === "pensando") return;
  if (estado === "escuchando") return escucha.detener();
  if (estado === "hablando") voz.callar();
  escuchar();
}

// ---------------------------------------------------------------------------
// Teclado, conversación nueva y clave
// ---------------------------------------------------------------------------

function abrirTeclado() {
  formTeclado.hidden = false;
  entradaTexto.focus();
}

$("btn-teclado").addEventListener("click", () => {
  if (formTeclado.hidden) abrirTeclado();
  else formTeclado.hidden = true;
});

formTeclado.addEventListener("submit", (evento) => {
  evento.preventDefault();
  voz.desbloquear();
  const texto = entradaTexto.value;
  entradaTexto.value = "";
  formTeclado.hidden = true;
  enviar(texto);
});

$("btn-nueva").addEventListener("click", async () => {
  voz.callar();
  cerrarPanel();
  ponerEstado("reposo");
  subtitulo("");
  try {
    await api.olvidar();
    mostrarAviso("Conversación nueva");
  } catch (error) {
    if (error instanceof ErrorClave) pedirClave();
  }
});

// ---------------------------------------------------------------------------
// Saludo al entrar: también confirma que el audio funciona
// ---------------------------------------------------------------------------

const SALUDO = "Bienvenido de nuevo, señor.";
const activacion = $("activar-audio");

async function saludar() {
  if (!vozGeminiDisponible) return;
  ponerEstado("pensando", "Preparando la voz…");
  let audio;
  try {
    audio = await api.voz(SALUDO);
  } catch (error) {
    ponerEstado("reposo");
    mostrarAviso(`No sonó la voz de Charon: ${error.message}.`, 9000);
    return;
  }
  subtitulo(SALUDO);
  const reproducir = async () => {
    const sono = await reproducirAudio(audio, {
      alNivel: (n) => orbe.nivel(n),
      alEmpezar: () => ponerEstado("hablando"),
    });
    ponerEstado("reposo");
    return sono;
  };
  if (await reproducir()) return;

  // El navegador no deja sonar audio hasta que toques la pantalla una vez (regla de Chrome y Safari).
  ponerEstado("reposo", "");
  activacion.hidden = false;
  activacion.addEventListener("click", () => {
    activacion.hidden = true;
    desbloquearAudio();
    reproducir(); // se reproduce dentro del toque: así el celular sí lo permite
  }, { once: true });
}

$("btn-microfono").addEventListener("click", alTocarMicrofono);
$("orbe").addEventListener("click", alTocarMicrofono);
$("panel-cerrar").addEventListener("click", cerrarPanel);

document.addEventListener("keydown", (evento) => {
  const escribiendo = evento.target.closest("input, textarea, dialog");
  if (evento.code === "Space" && !escribiendo && !evento.repeat) {
    evento.preventDefault();
    alTocarMicrofono();
  }
  if (evento.key === "Escape" && document.body.classList.contains("mostrando")) cerrarPanel();
});

function pedirClave(error = "") {
  $("error-clave").textContent = error;
  $("entrada-clave").value = "";
  if (!dialogoClave.open) dialogoClave.showModal();
}

function aplicarEstado(estado) {
  $("conexion").textContent = estado.cerebro === "gemini" ? "Gemini" : estado.cerebro === "claude" ? "Claude" : "";
  vozGeminiDisponible = estado.voz?.motor === "gemini";
  configurarVoz();
}

$("form-clave").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  clave.guardar($("entrada-clave").value.trim());
  const estado = await api.estado().catch(() => null);
  if (estado && estado.autorizado) {
    dialogoClave.close();
    aplicarEstado(estado);
    saludar();
  } else {
    $("error-clave").textContent = estado ? "Esa clave no coincide con APP_CLAVE." : "No pude conectar con el servidor.";
  }
});

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------

async function iniciar() {
  ponerEstado("reposo", "Conectando…");
  try {
    const estado = await api.estado();
    ponerEstado("reposo");
    if (estado.requiere_clave && !estado.autorizado) {
      pedirClave(clave.obtener() ? "La clave guardada ya no es válida." : "");
      return;
    }
    aplicarEstado(estado);
    saludar();
    if (estado.cerebro === "ninguno") mostrarAviso("Falta configurar la llave de Claude o de Gemini en el servidor.", 8000);
  } catch {
    ponerEstado("error", "Sin conexión con el servidor");
    setTimeout(() => ponerEstado("reposo"), 4000);
  }
}

iniciar();
