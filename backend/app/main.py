"""Servidor de JARVIS: sirve la página (frontend) y la API que reparte el trabajo entre Claude, Gemini y ChatGPT."""
from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
import time
from contextlib import asynccontextmanager

from html import escape
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import sesiones, voz
from .archivos import IMAGENES_SEGURAS, MAX_BYTES_ARCHIVO, ArchivoError, almacen
from .cerebro import _explicar_error as explicar_error, procesar
from .config import RAIZ, config
from .cuenta_google import GoogleError, google
from .notion import notion
from .spotify import SpotifyError, spotify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jarvis")
FRONTEND = RAIZ / "frontend"
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


async def _precalentar_notion() -> None:
    """Lee tus secciones de Objetivos al arrancar para que la primera orden sea más rápida."""
    if notion.configurado:
        try:
            await notion.precalentar()
            log.info("Notion listo. Secciones: %s", notion.titulos_en_cache())
        except Exception as error:  # noqa: BLE001
            log.warning("No pude leer Notion al arrancar: %s", error)


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    tarea = asyncio.create_task(_precalentar_notion())
    yield
    tarea.cancel()
    await notion.cerrar()
    await spotify.cerrar()
    await google.cerrar()


app = FastAPI(title="JARVIS", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)


def verificar_clave(x_clave: str = Header(default="")) -> None:
    if not config.clave_app:
        if config.entorno == "local":
            return
        raise HTTPException(503, "Configura APP_CLAVE en el servidor antes de usar JARVIS.")
    if not hmac.compare_digest(x_clave.encode(), config.clave_app.encode()):
        raise HTTPException(401, "Clave incorrecta.")


class Comando(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    sesion: str = Field(default="principal", max_length=64)
    archivos: list[str] = Field(default_factory=list, max_length=8)


class Sesion(BaseModel):
    sesion: str = Field(default="principal", max_length=64)


@app.post("/api/comando", dependencies=[Depends(verificar_clave)])
async def comando(datos: Comando) -> dict:
    texto = datos.texto.strip()
    inicio = time.monotonic()
    nuevos = [a.resumen() for a in almacen.varios(datos.archivos)]
    if nuevos:
        sesiones.agregar_archivos(datos.sesion, nuevos)
        texto += "\n\n[Adjuntó ahora: " + "; ".join(f"{a['nombre']} (archivo_id={a['archivo_id']})" for a in nuevos) + "]"
    else:
        sesiones.tocar_archivos(datos.sesion)
    vigentes = [a for a in sesiones.archivos(datos.sesion) if almacen.obtener(a["archivo_id"])]
    log.info("Orden recibida: %s", texto[:160])
    try:
        respuesta = await procesar(texto, sesiones.historial(datos.sesion), vigentes)
    except Exception as error:  # noqa: BLE001 — nunca dejamos la página esperando sin respuesta
        log.exception("Error procesando la orden")
        respuesta = {"voz": "Tuve un problema interno procesando eso, señor. Revise la terminal del servidor.",
                     "mostrar": None, "herramientas": [], "cerebro": config.orquestador_efectivo,
                     "aviso": f"Error del servidor: {type(error).__name__}: {error}"}
    recuerdo = respuesta["voz"]
    if respuesta.get("mostrar"):
        recuerdo += f" [En pantalla: {respuesta['mostrar'].get('titulo', '')}]"
    sesiones.guardar_turno(datos.sesion, texto, recuerdo)
    log.info("Respondió %s en %.1f s usando %s | voz: %s", respuesta.get("cerebro"), time.monotonic() - inicio,
             respuesta.get("herramientas") or "ninguna herramienta", respuesta["voz"][:160])
    if respuesta.get("aviso"):
        log.warning("Aviso: %s", respuesta["aviso"])
    return respuesta


@app.post("/api/olvidar", dependencies=[Depends(verificar_clave)])
async def olvidar(datos: Sesion) -> dict:
    sesiones.olvidar(datos.sesion)
    return {"ok": True}


@app.get("/api/estado")
async def estado(x_clave: str = Header(default="")) -> dict:
    autorizado = (not config.clave_app and config.entorno == "local") or (
        bool(config.clave_app) and hmac.compare_digest(x_clave.encode(), config.clave_app.encode()))
    base = {"ok": True, "requiere_clave": bool(config.clave_app) or config.entorno != "local"}
    if not autorizado:
        return base
    return {**base, "autorizado": True, "cerebro": config.orquestador_efectivo,
            "investigacion": config.investigacion_modo if config.gemini_api_key else "no configurada",
            "web_gratis": bool(config.tavily_api_key), "notion": notion.configurado,
            "voz": {"motor": "gemini" if voz.disponible() else "navegador", "predeterminada": config.voz_gemini},
            "spotify": "conectado" if spotify.conectado else "sin conectar" if spotify.configurado else "no configurado",
            "chatgpt": "conectado" if config.openai_api_key else "sin llave (Gemini lo cubre)",
            "google": "conectado" if google.conectado else "sin conectar" if google.configurado else "no configurado",
            "youtube": bool(config.youtube_api_key)}


class PeticionVoz(BaseModel):
    texto: str = Field(min_length=1, max_length=1500)
    voz: str | None = Field(default=None, max_length=80)


@app.post("/api/voz", dependencies=[Depends(verificar_clave)])
async def hablar(datos: PeticionVoz) -> Response:
    """Convierte texto en audio con la voz de Gemini. Si falla, la página usa la voz del navegador."""
    if not voz.disponible():
        raise HTTPException(503, "La voz de Gemini no está activada (VOZ_MOTOR o GEMINI_API_KEY).")
    inicio = time.monotonic()
    try:
        audio = await voz.sintetizar(datos.texto, datos.voz)
    except voz.ErrorVoz as error:
        log.warning("No se pudo generar la voz: %s", error)
        raise HTTPException(503, f"ningún modelo de voz respondió ({str(error)[:300]})") from error
    except Exception as error:  # noqa: BLE001
        log.warning("No se pudo generar la voz: %s", str(error)[:300])
        raise HTTPException(503, f"{explicar_error(error)} ({type(error).__name__}: {str(error)[:120]})") from error
    log.info("Voz generada en %.1f s (%s)", time.monotonic() - inicio, voz.voz_permitida(datos.voz))
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Archivos: subir (PDF, Word, Excel, fotos) y ver/descargar (incluye las imágenes que crea ChatGPT)
# ---------------------------------------------------------------------------

@app.post("/api/archivo", dependencies=[Depends(verificar_clave)])
async def subir_archivo(request: Request, x_nombre: str = Header(default="archivo")) -> dict:
    """Recibe el archivo tal cual (sin formularios) con su nombre en la cabecera X-Nombre."""
    if int(request.headers.get("content-length") or 0) > MAX_BYTES_ARCHIVO:
        raise HTTPException(413, "El archivo pesa más de 20 MB.")
    datos = bytearray()
    async for trozo in request.stream():
        datos += trozo
        if len(datos) > MAX_BYTES_ARCHIVO:
            raise HTTPException(413, "El archivo pesa más de 20 MB.")
    try:
        archivo = almacen.guardar(unquote(x_nombre), bytes(datos), request.headers.get("content-type", ""))
    except ArchivoError as error:
        raise HTTPException(400, str(error)) from error
    log.info("Archivo recibido: %s (%s, %d KB)", archivo.nombre, archivo.tipo, len(archivo.datos) // 1024)
    return {"id": archivo.id, "nombre": archivo.nombre, "tipo": archivo.tipo, "kb": len(archivo.datos) // 1024}


@app.get("/api/archivo/{archivo_id}")
async def ver_archivo(archivo_id: str, descargar: bool = False) -> Response:
    """El id es imposible de adivinar (funciona como contraseña del archivo). Solo las fotos se muestran
    dentro de la página; todo lo demás se descarga, para que ningún archivo pueda ejecutar código aquí."""
    archivo = almacen.obtener(archivo_id)
    if not archivo:
        raise HTTPException(404, "Ese archivo ya expiró (duran 3 horas).")
    en_linea = archivo.tipo in IMAGENES_SEGURAS and not descargar
    disposicion = "inline" if en_linea else "attachment"
    return Response(archivo.datos, media_type=archivo.tipo if en_linea else "application/octet-stream", headers={
        "Content-Disposition": f"{disposicion}; filename*=UTF-8''{quote(archivo.nombre)}",
        "Cache-Control": "private, max-age=10800", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox", "Referrer-Policy": "no-referrer"})


# ---------------------------------------------------------------------------
# Spotify y Google: conexión de la cuenta (una vez)
# ---------------------------------------------------------------------------

def _url_de_regreso(request: Request, servicio: str = "spotify") -> str:
    """Dirección a la que Spotify o Google regresan después de iniciar sesión (debe estar registrada)."""
    fija = config.spotify_redirect_uri if servicio == "spotify" else config.google_redirect_uri
    if fija:
        return fija
    protocolo = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    if host.split(":")[0] == "localhost":
        host = host.replace("localhost", "127.0.0.1", 1)  # Spotify no acepta "localhost"
    return f"{protocolo}://{host}/{servicio}/callback"


@app.post("/api/spotify/enlace", dependencies=[Depends(verificar_clave)])
async def spotify_enlace(request: Request) -> dict:
    try:
        return {"url": spotify.crear_enlace(_url_de_regreso(request, "spotify")),
                "regreso": _url_de_regreso(request, "spotify")}
    except SpotifyError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/spotify/reintentar", dependencies=[Depends(verificar_clave)])
async def spotify_reintentar() -> dict:
    try:
        return await spotify.reintentar_pendiente()
    except SpotifyError as error:
        return {"ok": False, "motivo": str(error)}


@app.get("/spotify/conectar")
async def spotify_conectar() -> FileResponse:
    return FileResponse(FRONTEND / "spotify.html", headers={"Cache-Control": "no-cache"})


def _pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    html = f"""<!doctype html><html lang="es-MX"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer">
<title>{escape(titulo)}</title><link rel="stylesheet" href="/css/spotify.css"></head>
<body><main class="tarjeta"><h1>{escape(titulo)}</h1>{cuerpo}</main></body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/spotify/callback")
async def spotify_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    if error:
        motivo = "Cancelaste el permiso." if error == "access_denied" else f"Spotify respondió: {error}."
        return _pagina("No se conectó Spotify", f"<p>{escape(motivo)}</p><a class='boton' href='/'>Volver a JARVIS</a>")
    try:
        codigo = await spotify.completar_conexion(code, state)
    except SpotifyError as fallo:
        return _pagina("No se conectó Spotify", f"<p>{escape(str(fallo))}</p><a class='boton' href='/'>Volver a JARVIS</a>")
    cuerpo = f"""<p>Listo: JARVIS ya puede controlar tu música.</p>
<p>Para que no se pierda cuando el servidor se reinicie, guarda este código como
<b>SPOTIFY_REFRESH_TOKEN</b> en Render (Environment) y en tu <b>.env</b>. Es privado, como una contraseña.</p>
<textarea id="codigo" readonly rows="4">{escape(codigo)}</textarea>
<button class="boton" type="button" onclick="navigator.clipboard.writeText(document.getElementById('codigo').value).then(()=>this.textContent='Copiado')">Copiar código</button>
<a class="boton boton--suave" href="/">Volver a JARVIS</a>"""
    return _pagina("Spotify conectado", cuerpo)


@app.post("/api/google/enlace", dependencies=[Depends(verificar_clave)])
async def google_enlace(request: Request) -> dict:
    regreso = _url_de_regreso(request, "google")
    try:
        return {"url": google.crear_enlace(regreso), "regreso": regreso}
    except GoogleError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/google/conectar")
async def google_conectar() -> FileResponse:
    return FileResponse(FRONTEND / "google.html", headers={"Cache-Control": "no-cache"})


@app.get("/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    volver = "<a class='boton' href='/'>Volver a JARVIS</a>"
    if error:
        motivo = "Cancelaste el permiso." if error == "access_denied" else f"Google respondió: {error}."
        return _pagina("No se conectó Google", f"<p>{escape(motivo)}</p>{volver}")
    try:
        codigo = await google.completar_conexion(code, state)
    except GoogleError as fallo:
        return _pagina("No se conectó Google", f"<p>{escape(str(fallo))}</p>{volver}")
    except Exception as fallo:  # noqa: BLE001
        log.exception("Error conectando Google")
        return _pagina("No se conectó Google", f"<p>{escape(type(fallo).__name__)}: {escape(str(fallo)[:200])}</p>{volver}")
    cuerpo = f"""<p>Listo: Gemini ya puede revisar tu Gmail, Google Calendar y Drive.</p>
<p>Para que no se pierda cuando el servidor se reinicie, guarda este código como
<b>GOOGLE_REFRESH_TOKEN</b> en Render (Environment) y en tu <b>.env</b>. Es privado, como una contraseña.</p>
<textarea id="codigo" readonly rows="4">{escape(codigo)}</textarea>
<button class="boton" type="button" onclick="navigator.clipboard.writeText(document.getElementById('codigo').value).then(()=>this.textContent='Copiado')">Copiar código</button>
<a class="boton boton--suave" href="/">Volver a JARVIS</a>"""
    return _pagina("Google conectado", cuerpo)


@app.get("/salud")
async def salud() -> dict:
    return {"ok": True}


@app.get("/")
async def inicio() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})


class EstaticosSinCache(StaticFiles):
    """Sirve la página pidiendo al navegador que revise si hay versión nueva cada vez (respuesta 304 si no
    cambió, así que sigue siendo rápido). Sin esto, el celular se quedaba con JavaScript viejo tras actualizar."""

    async def get_response(self, path, scope):
        respuesta = await super().get_response(path, scope)
        respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


app.mount("/", EstaticosSinCache(directory=FRONTEND), name="frontend")
