import { api, clave, ErrorClave, preferenciaVoz } from "./api.js";
import { desbloquearAudio } from "./audio.js";
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
const selectorVoz = $("selector-voz");

const orbe = crearOrbe({ alTocar: () => alTocarMicrofono() }); // tocar el Núcleo Lumen = hablar
let ocupado = false;
let temporizadorAviso;
let vozGeminiDisponible = false;
let avisoVozMostrado = false;

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
// Voz: Gemini (la que elijas en el selector) o la del navegador de respaldo
// ---------------------------------------------------------------------------

function configurarVoz() {
  const elegida = preferenciaVoz.obtener();
  voz.motorRemoto = vozGeminiDisponible && elegida !== "navegador"
    ? (texto) => api.voz(texto, elegida || null)
    : null;
}

// Habla y mueve el núcleo: se queda "pensando" mientras se genera el audio y pasa a "hablando" al sonar.
async function decir(texto) {
  const sono = await voz.hablar(texto, {
    alNivel: (n) => orbe.nivel(n),
    alEmpezar: () => ponerEstado("hablando"),
  });
  if (voz.motorRemoto && voz.ultimoMotor === "navegador" && !avisoVozMostrado) {
    avisoVozMostrado = true;
    mostrarAviso(`La voz de Gemini no respondió (${voz.ultimoError}); usé la del navegador.`, 9000);
  }
  return sono;
}

function llenarSelectorVoz(infoVoz) {
  selectorVoz.replaceChildren();
  const elegida = preferenciaVoz.obtener();
  if (infoVoz?.motor === "gemini") {
    for (const { nombre, caracter } of infoVoz.voces) {
      const opcion = new Option(`${nombre} · ${caracter}${nombre === infoVoz.predeterminada ? " (predeterminada)" : ""}`, nombre);
      selectorVoz.append(opcion);
    }
  }
  selectorVoz.append(new Option("Voz del navegador", "navegador"));
  const valores = [...selectorVoz.options].map((o) => o.value);
  selectorVoz.value = valores.includes(elegida) ? elegida : (infoVoz?.motor === "gemini" ? infoVoz.predeterminada : "navegador");
  selectorVoz.hidden = false;
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

    ponerEstado("pensando", "");
    transcripcion.textContent = respuesta.voz; // la respuesta queda escrita como subtítulo
    const sono = await decir(respuesta.voz);
    ponerEstado("reposo");
    if (!sono) mostrarAviso("No se reprodujo la voz. Toca “Probar voz” arriba para revisar el audio.", 9000);
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

// TEMPORAL: prueba de voz, selector de voces y diagnóstico rápido
async function probarVoz() {
  // El audio se habilita aquí mismo, dentro del toque (lo exige el celular).
  desbloquearAudio();
  voz.callar();
  const saludo = "Hola, bienvenido de nuevo.";
  ponerEstado("pensando", "");
  transcripcion.textContent = saludo;
  const sono = await decir(saludo);
  ponerEstado("reposo");

  const estado = await api.estado().catch(() => null);
  const servidor = !estado
    ? "Servidor: sin conexión"
    : `Cerebro: ${estado.cerebro || "?"} · Notion: ${estado.notion ? "conectado" : "sin conectar"} · Web: ${estado.web_gratis ? "Tavily" : "sin búsqueda web"}`;
  const queVoz = voz.ultimoMotor === "gemini"
    ? `Voz: Gemini (${selectorVoz.value})`
    : `Voz: navegador (${voz.nombre()})${voz.ultimoError ? ` — Gemini: ${voz.ultimoError}` : ""}`;
  mostrarAviso(`${sono ? "✓ Voz funcionando" : "✗ No se reprodujo la voz: revisa el volumen y la salida de audio"} · ${queVoz} · ${servidor}`, 12000);
}

$("btn-prueba").addEventListener("click", probarVoz);
selectorVoz.addEventListener("change", () => {
  preferenciaVoz.guardar(selectorVoz.value);
  configurarVoz();
  probarVoz();
});

$("btn-microfono").addEventListener("click", alTocarMicrofono);
$("orbe").addEventListener("click", alTocarMicrofono);
$("panel-cerrar").addEventListener("click", cerrarPanel);

document.addEventListener("keydown", (evento) => {
  const escribiendo = evento.target.closest("input, textarea, select, dialog");
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
  llenarSelectorVoz(estado.voz);
  configurarVoz();
}

$("form-clave").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  clave.guardar($("entrada-clave").value.trim());
  const estado = await api.estado().catch(() => null);
  if (estado && estado.autorizado) {
    dialogoClave.close();
    aplicarEstado(estado);
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
    if (estado.cerebro === "ninguno") mostrarAviso("Falta configurar la llave de Claude o de Gemini en el servidor.", 8000);
  } catch {
    ponerEstado("error", "Sin conexión con el servidor");
    setTimeout(() => ponerEstado("reposo"), 4000);
  }
}

iniciar();
