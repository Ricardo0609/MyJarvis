import { api, clave, ErrorClave } from "./api.js";
import { desbloquearAudio, reproducirAudio } from "./audio.js";
import { crearOrbe } from "./orbe.js";
import { guia, mostrarEnPanel, ocultarPanel } from "./panel.js";
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
  if (guia.activa) {
    turnoGuia++; // si estaba leyendo un paso, se calla
    voz.callar();
  }
  orbe.mostrar(false);
  setTimeout(() => { if (!document.body.classList.contains("mostrando")) ocultarPanel(); }, 550);
}

function ponerExpertos(respuesta) {
  const director = respuesta.cerebro === "gemini" ? "Gemini" : "Claude";
  $("conexion").textContent = (respuesta.expertos?.length ? respuesta.expertos : [director]).join(" · ");
}

// ---------------------------------------------------------------------------
// Archivos adjuntos: se suben en cuanto los eliges y viajan con tu siguiente orden
// ---------------------------------------------------------------------------

const zonaAdjuntos = $("adjuntos");
const entradaArchivo = $("entrada-archivo");
let adjuntos = [];
let contadorAdjuntos = 0;

const ICONOS_ARCHIVO = { pdf: "picture_as_pdf", doc: "description", docx: "description", xls: "table_chart",
  xlsx: "table_chart", xlsm: "table_chart", csv: "table_chart", ppt: "slideshow", pptx: "slideshow" };

// Las fotos del celular pesan mucho: se reducen a 2048 px antes de subirlas (más rápido y más barato de analizar).
async function reducirImagen(archivo) {
  if (!archivo.type.startsWith("image/") || archivo.type === "image/gif" || archivo.size < 1.5e6) return archivo;
  try {
    const imagen = await createImageBitmap(archivo, { imageOrientation: "from-image" });
    const escala = Math.min(1, 2048 / Math.max(imagen.width, imagen.height));
    const lienzo = document.createElement("canvas");
    lienzo.width = Math.round(imagen.width * escala);
    lienzo.height = Math.round(imagen.height * escala);
    lienzo.getContext("2d").drawImage(imagen, 0, 0, lienzo.width, lienzo.height);
    const reducida = await new Promise((listo) => lienzo.toBlob(listo, "image/jpeg", 0.86));
    if (!reducida || reducida.size >= archivo.size) return archivo;
    return new File([reducida], archivo.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return archivo; // formato que el navegador no sabe abrir (p. ej. HEIC en Chrome): se sube tal cual
  }
}

function dibujarAdjuntos() {
  zonaAdjuntos.replaceChildren();
  for (const a of adjuntos) {
    const chip = document.createElement("div");
    chip.className = `adjunto adjunto--${a.estado}`;
    chip.title = a.estado === "error" ? a.error : a.nombre;
    if (a.miniatura) {
      const img = document.createElement("img");
      img.src = a.miniatura;
      img.alt = "";
      chip.append(img);
    } else {
      const icono = document.createElement("span");
      icono.className = "material-symbols-rounded";
      icono.textContent = a.estado === "error" ? "error" : ICONOS_ARCHIVO[a.nombre.split(".").pop().toLowerCase()] || "draft";
      chip.append(icono);
    }
    const nombre = document.createElement("span");
    nombre.className = "adjunto__nombre";
    nombre.textContent = a.estado === "subiendo" ? `Subiendo ${a.nombre}` : a.nombre;
    const quitar = document.createElement("button");
    quitar.type = "button";
    quitar.className = "adjunto__quitar";
    quitar.setAttribute("aria-label", `Quitar ${a.nombre}`);
    quitar.innerHTML = '<span class="material-symbols-rounded">close</span>';
    quitar.addEventListener("click", () => quitarAdjunto(a.clave));
    chip.append(nombre, quitar);
    zonaAdjuntos.append(chip);
  }
  zonaAdjuntos.hidden = !adjuntos.length;
  document.body.classList.toggle("con-adjuntos", adjuntos.length > 0);
  acomodarSubtitulo();
}

function quitarAdjunto(claveAdjunto) {
  const quitado = adjuntos.find((a) => a.clave === claveAdjunto);
  if (quitado?.miniatura) URL.revokeObjectURL(quitado.miniatura);
  adjuntos = adjuntos.filter((a) => a.clave !== claveAdjunto);
  dibujarAdjuntos();
}

function limpiarAdjuntos() {
  adjuntos.forEach((a) => a.miniatura && URL.revokeObjectURL(a.miniatura));
  adjuntos = [];
  dibujarAdjuntos();
}

async function agregarArchivos(lista) {
  for (const original of Array.from(lista).slice(0, 6)) {
    const adjunto = { clave: ++contadorAdjuntos, nombre: original.name || "foto.jpg", estado: "subiendo",
      miniatura: original.type.startsWith("image/") ? URL.createObjectURL(original) : "" };
    adjuntos.push(adjunto);
    adjunto.promesa = (async () => {
      try {
        if (original.size > 20 * 1024 * 1024 && !original.type.startsWith("image/")) {
          throw new Error("pesa más de 20 MB");
        }
        const listo = await reducirImagen(original);
        const datos = await api.subirArchivo(listo, listo.name || adjunto.nombre);
        Object.assign(adjunto, { id: datos.id, nombre: datos.nombre, estado: "listo" });
      } catch (error) {
        if (error instanceof ErrorClave) pedirClave();
        Object.assign(adjunto, { estado: "error", error: error.message });
        mostrarAviso(`No se pudo subir ${adjunto.nombre}: ${error.message}.`, 8000);
      }
      dibujarAdjuntos();
    })();
  }
  dibujarAdjuntos();
  await Promise.allSettled(adjuntos.map((a) => a.promesa));
  if (adjuntos.some((a) => a.estado === "listo") && document.body.dataset.estado === "reposo" && !ocupado) {
    ponerEstado("reposo", "Archivo listo · dime qué hago con él");
  }
}

$("btn-adjuntar").addEventListener("click", () => {
  voz.desbloquear();
  entradaArchivo.click();
});
entradaArchivo.addEventListener("change", () => {
  if (entradaArchivo.files?.length) agregarArchivos(entradaArchivo.files);
  entradaArchivo.value = "";
});

// También puedes arrastrar archivos a la ventana (PC) o pegar una captura de pantalla (Ctrl+V).
window.addEventListener("dragover", (evento) => evento.preventDefault());
window.addEventListener("drop", (evento) => {
  evento.preventDefault();
  if (evento.dataTransfer?.files?.length) agregarArchivos(evento.dataTransfer.files);
});
window.addEventListener("paste", (evento) => {
  const archivos = Array.from(evento.clipboardData?.files || []);
  if (archivos.length) {
    evento.preventDefault();
    agregarArchivos(archivos);
  }
});

// ---------------------------------------------------------------------------
// Guía paso a paso: "siguiente", "anterior", "repite", "paso 3" se resuelven aquí mismo (al instante)
// ---------------------------------------------------------------------------

let turnoGuia = 0;
const NUMEROS = { uno: 1, primero: 1, primer: 1, dos: 2, segundo: 2, tres: 3, tercero: 3, tercer: 3, cuatro: 4,
  cuarto: 4, cinco: 5, quinto: 5, seis: 6, sexto: 6, siete: 7, septimo: 7, ocho: 8, octavo: 8, nueve: 9, noveno: 9,
  diez: 10, decimo: 10, once: 11, doce: 12, trece: 13, catorce: 14, quince: 15 };

function normalizar(texto) {
  return texto.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[¿?¡!.,;:"]/g, " ").replace(/\s+/g, " ").trim();
}

export function comandoGuia(texto) {
  let t = normalizar(texto);
  for (let i = 0; i < 3; i++) t = t.replace(/^(jarvis|oye|ok|okay|bien|muy bien|va|vale|perfecto|bueno|y|ahora)\s+/, "");
  t = t.replace(/\s+(por favor|porfa|jarvis|senor)$/, "");
  if (/^(siguiente|sigue|continua|continuar|continuamos|continuemos|adelante|proximo|el siguiente|siguiente paso|que sigue|ya|ya esta|ya quedo|ya lo hice|listo|hecho|empezar|empieza|empecemos|comenzar|comienza|comencemos|vamos|dale)$/.test(t)) return { accion: "siguiente" };
  if (/^(anterior|atras|regresa|regresar|paso anterior|el anterior|vuelve|volver|regresa un paso|un paso atras)$/.test(t)) return { accion: "anterior" };
  if (/^(repite|repitelo|repetir|repite el paso|repite eso|otra vez|de nuevo|que dijiste|no te escuche|no escuche|como|mande)$/.test(t)) return { accion: "repetir" };
  const m = t.match(/^(?:ve al |ir al |vamos al |ve a |al |pasa al )?paso (?:numero )?(\d+|[a-z]+)$/);
  if (m) {
    const n = Number(m[1]) || NUMEROS[m[1]];
    if (n) return { accion: "ir", paso: n - 1 };
  }
  if (/^(que (necesito|ocupo)|materiales|ingredientes|que materiales|que ingredientes|lista de (materiales|ingredientes))$/.test(t)) return { accion: "materiales" };
  if (/^(termina|terminar|terminamos|salir|sal|cerrar|cierra|quita|quitar)( de)?( la)?( guia| receta)?$/.test(t)) return { accion: "cerrar" };
  return null;
}

async function hablarGuia(texto) {
  const turno = ++turnoGuia;
  voz.callar();
  if (!texto || !vozGeminiDisponible) return;
  ponerEstado("pensando", "Preparando la voz…");
  let audio;
  try {
    audio = await api.voz(texto);
  } catch (error) {
    if (turno === turnoGuia) {
      ponerEstado("reposo");
      mostrarAviso(`No sonó la voz de Charon: ${error.message}.`, 7000);
    }
    return;
  }
  if (turno !== turnoGuia) return; // ya pidió otro paso
  await reproducirAudio(audio, { alNivel: (n) => orbe.nivel(n), alEmpezar: () => ponerEstado("hablando") });
  if (turno === turnoGuia) ponerEstado("reposo");
}

guia.alCambiar = async (texto, indice) => {
  await hablarGuia(texto);
  // Prepara el audio del siguiente paso para que al decir "siguiente" suene al instante.
  const siguiente = guia.textoPaso(indice + 1);
  if (siguiente && vozGeminiDisponible && guia.activa) api.voz(siguiente).catch(() => {});
};

function manejarGuia(comando) {
  if (comando.accion === "siguiente") guia.siguiente();
  else if (comando.accion === "anterior") guia.anterior();
  else if (comando.accion === "repetir") guia.repetir();
  else if (comando.accion === "ir") guia.ir(comando.paso);
  else if (comando.accion === "materiales") hablarGuia(guia.textoMateriales());
  else if (comando.accion === "cerrar") {
    cerrarPanel();
    hablarGuia("Muy bien, señor. Cerré la guía.");
  }
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
  if (guia.activa && !adjuntos.length) {
    const comando = comandoGuia(texto);
    if (comando) return manejarGuia(comando);
  }
  ocupado = true;
  ocultarAccion();
  subtitulo(texto);
  ponerEstado("pensando");
  if (adjuntos.some((a) => a.estado === "subiendo")) {
    ponerEstado("pensando", "Subiendo archivo…");
    await Promise.allSettled(adjuntos.map((a) => a.promesa));
    ponerEstado("pensando");
  }
  const ids = adjuntos.filter((a) => a.estado === "listo").map((a) => a.id);
  const enLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
  const esperas = [
    setTimeout(() => ponerEstado("pensando", ids.length ? "Revisando el archivo…" : enLocal ? "Sigo pensando…" : "Despertando el servidor…"), 8000),
    setTimeout(() => ponerEstado("pensando", "Sigo en ello: archivos, imágenes y correos tardan un poco más…"), 30000),
  ];
  const limpiarEsperas = () => esperas.forEach(clearTimeout);

  try {
    const respuesta = await api.comando(texto, ids);
    limpiarEsperas();
    if (ids.length) limpiarAdjuntos(); // ya quedaron en la conversación: puedes seguir preguntando por ellos
    if (respuesta.aviso) mostrarAviso(respuesta.aviso, 9000);
    ponerExpertos(respuesta);

    if (respuesta.abrir) mostrarAccion(respuesta.abrir);

    if (respuesta.mostrar) {
      turnoGuia++;
      mostrarEnPanel(respuesta.mostrar);
      requestAnimationFrame(() => orbe.mostrar(true));
    } else if (document.body.classList.contains("mostrando") && !guia.activa) {
      cerrarPanel(); // si estás siguiendo una guía, se queda en pantalla
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
  limpiarAdjuntos();
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
