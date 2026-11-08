// Comunicación con el servidor de JARVIS.

const LLAVE_CLAVE = "jarvis.clave";
const LLAVE_SESION = "jarvis.sesion";

function leer(llave) {
  try { return localStorage.getItem(llave) || ""; } catch { return ""; }
}
function guardar(llave, valor) {
  try { localStorage.setItem(llave, valor); } catch { /* modo privado: se usa solo en memoria */ }
}

let claveEnMemoria = leer(LLAVE_CLAVE);

export const clave = {
  obtener: () => claveEnMemoria,
  guardar(valor) { claveEnMemoria = valor; guardar(LLAVE_CLAVE, valor); },
};

export function sesionId() {
  let id = leer(LLAVE_SESION);
  if (!id) {
    id = (crypto.randomUUID?.() || String(Date.now())).slice(0, 36);
    guardar(LLAVE_SESION, id);
  }
  return id;
}

export class ErrorClave extends Error {}
export class ErrorServidor extends Error {}

async function pedir(ruta, { metodo = "GET", cuerpo, tiempoMax = 90000 } = {}) {
  const control = new AbortController();
  const temporizador = setTimeout(() => control.abort(), tiempoMax);
  try {
    const respuesta = await fetch(ruta, {
      method: metodo,
      headers: { "Content-Type": "application/json", "X-Clave": claveEnMemoria },
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
      signal: control.signal,
    });
    if (respuesta.status === 401) throw new ErrorClave("Clave incorrecta");
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new ErrorServidor(datos.detail || `Error ${respuesta.status}`);
    return datos;
  } catch (error) {
    if (error.name === "AbortError") throw new ErrorServidor("El servidor tardó demasiado en responder");
    if (error instanceof TypeError) throw new ErrorServidor("Sin conexión con el servidor");
    throw error;
  } finally {
    clearTimeout(temporizador);
  }
}

// Pide a Gemini el audio de una frase (WAV). Lanza error si no se pudo generar.
async function pedirAudio(texto) {
  const control = new AbortController();
  const temporizador = setTimeout(() => control.abort(), 30000);
  try {
    const respuesta = await fetch("/api/voz", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Clave": claveEnMemoria },
      body: JSON.stringify({ texto }),
      signal: control.signal,
    });
    if (respuesta.status === 401) throw new ErrorClave("Clave incorrecta");
    if (!respuesta.ok) {
      const datos = await respuesta.json().catch(() => ({}));
      throw new ErrorServidor(datos.detail || `Error ${respuesta.status} al generar la voz`);
    }
    return await respuesta.arrayBuffer();
  } catch (error) {
    if (error.name === "AbortError") throw new ErrorServidor("La voz tardó demasiado en generarse");
    throw error;
  } finally {
    clearTimeout(temporizador);
  }
}

// Sube un archivo tal cual (sin formularios); el servidor responde con su id.
async function subirArchivo(archivo, nombre = archivo.name) {
  const control = new AbortController();
  const temporizador = setTimeout(() => control.abort(), 180000);
  try {
    const respuesta = await fetch("/api/archivo", {
      method: "POST",
      headers: {
        "X-Clave": claveEnMemoria,
        "X-Nombre": encodeURIComponent(nombre || "archivo"),
        "Content-Type": archivo.type || "application/octet-stream",
      },
      body: archivo,
      signal: control.signal,
    });
    if (respuesta.status === 401) throw new ErrorClave("Clave incorrecta");
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new ErrorServidor(datos.detail || `Error ${respuesta.status} al subir el archivo`);
    return datos;
  } catch (error) {
    if (error.name === "AbortError") throw new ErrorServidor("El archivo tardó demasiado en subir");
    if (error instanceof TypeError) throw new ErrorServidor("Sin conexión con el servidor");
    throw error;
  } finally {
    clearTimeout(temporizador);
  }
}

export const api = {
  voz: pedirAudio,
  subirArchivo,
  estado: () => pedir("/api/estado", { tiempoMax: 70000 }),
  comando: (texto, archivos = []) => pedir("/api/comando", {
    metodo: "POST", cuerpo: { texto, sesion: sesionId(), archivos }, tiempoMax: 150000 }),
  olvidar: () => pedir("/api/olvidar", { metodo: "POST", cuerpo: { sesion: sesionId() } }),
  spotifyReintentar: () => pedir("/api/spotify/reintentar", { metodo: "POST", tiempoMax: 15000 }),
};
