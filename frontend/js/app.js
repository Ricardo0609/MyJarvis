import { api, clave, ErrorClave } from "./api.js";
import { crearOrbe } from "./orbe.js";
import { mostrarEnPanel, ocultarPanel } from "./panel.js";
import { escucha, voz } from "./voz.js";

const $ = (id) => document.getElementById(id);
const textoEstado = $("estado");
const transcripcion = $("transcripcion");
const formTeclado = $("form-teclado");
const entradaTexto = $("entrada-texto");
const dialogoClave = $("dialogo-clave");
const aviso = $("aviso");

const orbe = crearOrbe({ alTocar: () => alTocarMicrofono() }); // tocar el Núcleo Lumen = hablar
let ocupado = false;
let temporizadorAviso;

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
// Flujo principal: escuchar → pensar → hablar (y mostrar si hace falta)
// ---------------------------------------------------------------------------

async function enviar(texto) {
  texto = texto.trim();
  if (!texto || ocupado) return;
  ocupado = true;
  transcripcion.textContent = texto;
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

    if (respuesta.mostrar) {
      mostrarEnPanel(respuesta.mostrar);
      requestAnimationFrame(() => orbe.mostrar(true));
    } else if (document.body.classList.contains("mostrando")) {
      cerrarPanel();
    }

    ponerEstado("hablando");
    transcripcion.textContent = respuesta.voz; // la respuesta queda escrita como subtítulo
    const seEscucho = await voz.hablar(respuesta.voz, { alNivel: (n) => orbe.nivel(n) });
    ponerEstado("reposo");
    if (!seEscucho) mostrarAviso("No se reprodujo la voz. Toca “Probar voz” arriba para revisar el audio.", 9000);
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
  transcripcion.textContent = "";
  ponerEstado("escuchando");
  escucha.iniciar({
    alParcial: (texto) => { transcripcion.textContent = texto; },
    alTerminar: (texto) => {
      if (texto) enviar(texto);
      else if (!ocupado) ponerEstado("reposo");
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
  transcripcion.textContent = "";
  try {
    await api.olvidar();
    mostrarAviso("Conversación nueva");
  } catch (error) {
    if (error instanceof ErrorClave) pedirClave();
  }
});

// TEMPORAL: prueba de audio y diagnóstico rápido (se quitará cuando todo funcione)
$("btn-prueba").addEventListener("click", async () => {
  voz.desbloquear();
  if (!voz.soportada) {
    mostrarAviso("Este navegador no puede hablar (no tiene síntesis de voz). Prueba con Chrome.", 9000);
    return;
  }
  voz.callar();
  const saludo = "Hola, bienvenido de nuevo.";
  ponerEstado("hablando");
  transcripcion.textContent = saludo;
  const seEscucho = await voz.hablar(saludo, { alNivel: (n) => orbe.nivel(n) });
  ponerEstado("reposo");

  const estado = await api.estado().catch(() => null);
  const servidor = !estado
    ? "Servidor: sin conexión"
    : `Cerebro: ${estado.cerebro || "?"} · Notion: ${estado.notion ? "conectado" : "sin conectar"} · Web: ${estado.web_gratis ? "Tavily" : "sin búsqueda web"}`;
  mostrarAviso(
    `${seEscucho ? "✓ Voz funcionando" : "✗ El navegador no reprodujo la voz: revisa el volumen y la salida de audio"} · Voz: ${voz.nombre()} · ${servidor}`,
    12000,
  );
});

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

$("form-clave").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  clave.guardar($("entrada-clave").value.trim());
  const estado = await api.estado().catch(() => null);
  if (estado && estado.autorizado) {
    dialogoClave.close();
    $("conexion").textContent = estado.cerebro === "gemini" ? "Gemini" : "Claude";
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
    $("conexion").textContent = estado.cerebro === "gemini" ? "Gemini" : estado.cerebro === "claude" ? "Claude" : "";
    if (estado.cerebro === "ninguno") mostrarAviso("Falta configurar la llave de Claude o de Gemini en el servidor.", 8000);
  } catch {
    ponerEstado("error", "Sin conexión con el servidor");
    setTimeout(() => ponerEstado("reposo"), 4000);
  }
}

iniciar();
