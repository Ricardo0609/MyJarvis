"""Voz de JARVIS con Gemini TTS (plan gratuito).

Convierte el texto de la respuesta en audio WAV (24 kHz, mono) con una voz de Gemini y un estilo
de mayordomo sereno. Si el modelo está saturado prueba otro; si todo falla, la página usa la voz
del navegador como respaldo.
"""
from __future__ import annotations

import base64
import logging
from collections import OrderedDict

from .config import config
from .research import _conviene_cambiar, gemini

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


async def _generar(modelo: str, texto: str, voz: str) -> bytes:
    contenido: dict = {"type": "text", "text": texto}
    if config.voz_estilo:
        contenido["annotations"] = [{"type": "speech_metadata", "style": config.voz_estilo}]
    interaccion = await gemini().aio.interactions.create(
        model=modelo,
        input=[{"type": "user_input", "content": [contenido]}],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": voz}]},
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
    for modelo in (config.modelo_tts, *[m for m in config.modelos_tts_respaldo if m != config.modelo_tts]):
        try:
            audio = await _generar(modelo, texto, voz)
            _cache[clave] = audio
            while len(_cache) > _MAX_CACHE:
                _cache.popitem(last=False)
            return audio
        except Exception as error:  # noqa: BLE001
            ultimo_error = error
            if not _conviene_cambiar(error):
                break
            log.warning("TTS '%s' no disponible (%s); pruebo otro modelo", modelo, str(error)[:120])
    raise ultimo_error or RuntimeError("Sin modelos de voz")
