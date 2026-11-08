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
from .research import VERSION_API_GEMINI, _conviene_cambiar

# Segundos máximos por intento (el primero tiene más: tras despertar el servidor tarda un poco).
# En total quedan por debajo de los 30 s que espera la página.
LIMITES_SEGUNDOS = (13.0, 10.0, 5.0)
_cliente_tts = None
_no_disponibles: set[str] = set()  # modelos que tu llave no tiene (404): no se vuelven a intentar


class ErrorVoz(Exception):
    """Ningún modelo de voz pudo generar el audio. El mensaje dice qué pasó con cada uno."""


def motivo(error: Exception) -> str:
    texto = f"{type(error).__name__} {error}".lower()
    if "429" in texto or "resource_exhausted" in texto or "quota" in texto:
        return "se acabó su límite gratis de hoy"
    if "503" in texto or "unavailable" in texto or "overloaded" in texto or "high demand" in texto:
        return "está saturado"
    if "404" in texto or "not_found" in texto or "not found" in texto:
        return "no está disponible para tu llave"
    if "401" in texto or "403" in texto or "permission" in texto or "api key" in texto:
        return "la llave no tiene permiso"
    if "500" in texto or "internal" in texto:
        return "falla interna de Google"
    return f"{type(error).__name__}: {str(error)[:100]}"


def cliente_tts():
    """Cliente de Gemini solo para voz, sin los reintentos automáticos del SDK (que pueden esperar
    hasta 30 s cuando un modelo está saturado): nosotros cambiamos de modelo más rápido."""
    global _cliente_tts
    if _cliente_tts is None:
        from google import genai
        from google.genai import types
        _cliente_tts = genai.Client(
            api_key=config.gemini_api_key,
            http_options=types.HttpOptions(api_version=VERSION_API_GEMINI,
                                           retry_options=types.HttpRetryOptions(attempts=1)))
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

    errores: list[str] = []
    modelos = [m for m in dict.fromkeys((config.modelo_tts, *config.modelos_tts_respaldo))
               if m and m not in _no_disponibles] or [config.modelo_tts]
    for posicion, modelo in enumerate(modelos):
        limite = LIMITES_SEGUNDOS[min(posicion, len(LIMITES_SEGUNDOS) - 1)]
        inicio = time.monotonic()
        try:
            audio = await asyncio.wait_for(_generar(modelo, texto, voz, limite), timeout=limite)
        except asyncio.TimeoutError:
            errores.append(f"{modelo} tardó más de {limite:.0f} s")
            log.warning("TTS '%s' tardó más de %.0f s; pruebo otro modelo", modelo, limite)
            continue
        except Exception as error:  # noqa: BLE001
            errores.append(f"{modelo}: {motivo(error)}")
            log.warning("TTS '%s' falló (%s)", modelo, str(error)[:200])
            if motivo(error) == "no está disponible para tu llave":
                _no_disponibles.add(modelo)
            if not _conviene_cambiar(error):
                break
            continue
        log.info("Voz generada con %s en %.1f s", modelo, time.monotonic() - inicio)
        _cache[clave] = audio
        while len(_cache) > _MAX_CACHE:
            _cache.popitem(last=False)
        return audio
    raise ErrorVoz("; ".join(errores) or "no hay modelos de voz configurados")
