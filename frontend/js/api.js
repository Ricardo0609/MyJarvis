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

export const api = {
  estado: () => pedir("/api/estado", { tiempoMax: 70000 }),
  comando: (texto) => pedir("/api/comando", { metodo: "POST", cuerpo: { texto, sesion: sesionId() } }),
  olvidar: () => pedir("/api/olvidar", { metodo: "POST", cuerpo: { sesion: sesionId() } }),
};
