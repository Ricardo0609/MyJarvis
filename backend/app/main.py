"""Servidor de JARVIS: sirve la página (frontend) y la API que habla con Claude, Gemini y Notion."""
from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
import time
from contextlib import asynccontextmanager

from html import escape

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import sesiones, voz
from .cerebro import _explicar_error as explicar_error, procesar
from .config import RAIZ, config
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


class Sesion(BaseModel):
    sesion: str = Field(default="principal", max_length=64)


@app.post("/api/comando", dependencies=[Depends(verificar_clave)])
async def comando(datos: Comando) -> dict:
    texto = datos.texto.strip()
    inicio = time.monotonic()
    log.info("Orden recibida: %s", texto[:120])
    try:
        respuesta = await procesar(texto, sesiones.historial(datos.sesion))
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
            "spotify": "conectado" if spotify.conectado else "sin conectar" if spotify.configurado else "no configurado"}


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
    except Exception as error:  # noqa: BLE001
        log.warning("No se pudo generar la voz: %s", str(error)[:300])
        raise HTTPException(503, f"{explicar_error(error)} ({type(error).__name__}: {str(error)[:120]})") from error
    log.info("Voz generada en %.1f s (%s)", time.monotonic() - inicio, voz.voz_permitida(datos.voz))
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Spotify: conexión de la cuenta (una vez) y reintento al abrir la app
# ---------------------------------------------------------------------------

def _url_de_regreso(request: Request) -> str:
    """Dirección a la que Spotify regresa después de iniciar sesión (debe estar registrada en tu app)."""
    if config.spotify_redirect_uri:
        return config.spotify_redirect_uri
    protocolo = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    if host.split(":")[0] == "localhost":
        host = host.replace("localhost", "127.0.0.1", 1)  # Spotify no acepta "localhost"
    return f"{protocolo}://{host}/spotify/callback"


@app.post("/api/spotify/enlace", dependencies=[Depends(verificar_clave)])
async def spotify_enlace(request: Request) -> dict:
    try:
        return {"url": spotify.crear_enlace(_url_de_regreso(request)), "regreso": _url_de_regreso(request)}
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


@app.get("/salud")
async def salud() -> dict:
    return {"ok": True}


@app.get("/")
async def inicio() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
