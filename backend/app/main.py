"""Servidor de JARVIS: sirve la página (frontend) y la API que habla con Claude, Gemini y Notion."""
from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import sesiones
from .cerebro import procesar
from .config import RAIZ, config
from .notion import notion

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
            "web_gratis": bool(config.tavily_api_key), "notion": notion.configurado}


@app.get("/salud")
async def salud() -> dict:
    return {"ok": True}


@app.get("/")
async def inicio() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
