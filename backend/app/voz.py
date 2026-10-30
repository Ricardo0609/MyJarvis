"""Voz de JARVIS con Gemini TTS (plan gratuito).

Convierte el texto de la respuesta en audio WAV (24 kHz, mono) con la voz Charon y un estilo de
mayordomo sereno. Usa primero el modelo de voz más rápido; si un modelo tarda demasiado, está
saturado o llegó a su límite, pasa al siguiente sin quedarse esperando.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import OrderedDict

from .config import config
from .research import _conviene_cambiar

# Segundos máximos por intento (el primer modelo tiene un poco más). En total quedan por debajo
# de los 30 s que espera la página.
LIMITES_SEGUNDOS = (10.0, 7.0, 7.0)
_cliente_tts = None


def cliente_tts():
    """Cliente de Gemini solo para voz, sin los reintentos automáticos del SDK (que pueden esperar
    hasta 30 s cuando un modelo está saturado): nosotros cambiamos de modelo más rápido."""
    global _cliente_tts
    if _cliente_tts is None:
        from google import genai
        from google.genai import types
        _cliente_tts = genai.Client(
            api_key=config.gemini_api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
    return _cliente_tts

log = logging.getLogger("jarvis.voz")

# Voces prediseñadas de Gemini (nombre → carácter). Las primeras son las más adecuadas para JARVIS.
VOCES = {
    "Charon": "informativa, grave",
    "Iapetus": "clara",
    "Algieba": "suave",
    "Sadaltager": "conocedora",
    "Rasalgethi": "informativa",
    "Schedar": "pareja",
    "Orus": "firme",
    "Alnilam": "firme",
    "Gacrux": "madura",
    "Algenib": "rasposa",
    "Umbriel": "relajada",
    "Enceladus": "aireada",
    "Kore": "firme",
    "Zephyr": "brillante",
    "Puck": "animada",
    "Fenrir": "enérgica",
    "Leda": "juvenil",
    "Aoede": "ligera",
    "Callirrhoe": "relajada",
    "Autonoe": "brillante",
    "Despina": "suave",
    "Erinome": "clara",
    "Laomedeia": "animada",
    "Achernar": "suave",
    "Pulcherrima": "directa",
    "Achird": "amigable",
    "Zubenelgenubi": "casual",
    "Vindemiatrix": "amable",
    "Sadachbia": "viva",
    "Sulafat": "cálida",
}

_cache: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()
_MAX_CACHE = 40


def voz_permitida(nombre: str | None) -> str:
    """Solo acepta voces conocidas o la voz diseñada configurada en el servidor."""
    if nombre and (nombre in VOCES or nombre == config.voz_gemini):
        return nombre
    return config.voz_gemini


def disponible() -> bool:
    return config.voz_motor == "gemini" and bool(config.gemini_api_key)


async def _generar(modelo: str, texto: str, voz: str, limite: float) -> bytes:
    contenido: dict = {"type": "text", "text": texto}
    if config.voz_estilo:
        contenido["annotations"] = [{"type": "speech_metadata", "style": config.voz_estilo}]
    interaccion = await cliente_tts().aio.interactions.create(
        model=modelo,
        input=[{"type": "user_input", "content": [contenido]}],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": voz}]},
        timeout=limite,
    )
    audio = getattr(interaccion, "output_audio", None)
    datos = getattr(audio, "data", None) if audio else None
    if not datos:
        raise RuntimeError("Gemini no devolvió audio")
    return base64.b64decode(datos) if isinstance(datos, str) else bytes(datos)


async def sintetizar(texto: str, voz: str | None = None) -> bytes:
    """Devuelve el audio WAV de `texto`. Lanza excepción si ningún modelo pudo generarlo."""
    voz = voz_permitida(voz)
    clave = (voz, texto)
    if clave in _cache:
        _cache.move_to_end(clave)
        return _cache[clave]

    ultimo_error: Exception | None = None
    modelos = (config.modelo_tts, *[m for m in config.modelos_tts_respaldo if m != config.modelo_tts])
    for posicion, modelo in enumerate(modelos):
        limite = LIMITES_SEGUNDOS[min(posicion, len(LIMITES_SEGUNDOS) - 1)]
        inicio = time.monotonic()
        try:
            audio = await asyncio.wait_for(_generar(modelo, texto, voz, limite), timeout=limite)
        except asyncio.TimeoutError:
            ultimo_error = TimeoutError(f"el modelo de voz {modelo} tardó más de {limite:.0f} s")
            log.warning("TTS '%s' tardó más de %.0f s; pruebo otro modelo", modelo, limite)
            continue
        except Exception as error:  # noqa: BLE001
            ultimo_error = error
            if not _conviene_cambiar(error):
                break
            log.warning("TTS '%s' no disponible (%s); pruebo otro modelo", modelo, str(error)[:120])
            continue
        log.info("Voz generada con %s en %.1f s", modelo, time.monotonic() - inicio)
        _cache[clave] = audio
        while len(_cache) > _MAX_CACHE:
            _cache.popitem(last=False)
        return audio
    raise ultimo_error or RuntimeError("Sin modelos de voz")
