"""Investigación: Gemini es el experto que busca y resume.

Modos (variable INVESTIGACION_MODO):
- "gratis" (por defecto): busca en la web con Tavily (1,000 búsquedas gratis al mes, sin tarjeta)
  y Gemini (plan gratuito) resume los resultados. Costo: $0.
- "google": Gemini busca directo en Google Search. Requiere activar facturación en Google AI Studio
  (incluye 5,000 búsquedas gratis al mes, pero los tokens de Gemini se cobran).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import config

log = logging.getLogger("jarvis.gemini")
_cliente_gemini = None

# Errores pasajeros (modelo saturado, límite por minuto, fallo interno) o modelo no disponible:
# en esos casos conviene reintentar o cambiar a otro modelo gratis.
_SENALES_CAMBIAR = ("503", "unavailable", "high demand", "overloaded", "429", "resource_exhausted",
                    "500", "internal", "404", "not_found", "not found")


def gemini():
    global _cliente_gemini
    if _cliente_gemini is None:
        from google import genai
        _cliente_gemini = genai.Client(api_key=config.gemini_api_key)
    return _cliente_gemini


def _conviene_cambiar(error: Exception) -> bool:
    texto = f"{type(error).__name__} {error}".lower()
    return any(senal in texto for senal in _SENALES_CAMBIAR)


async def _llamar(modelo: str, contenidos: Any, ajustes: dict[str, Any]):
    """Pide razonamiento corto (responde más rápido); si el modelo no lo acepta, repite sin esa opción."""
    from google.genai import types

    try:
        return await gemini().aio.models.generate_content(
            model=modelo, contents=contenidos,
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="LOW"), **ajustes))
    except Exception as error:  # noqa: BLE001
        if "thinking" not in str(error).lower():
            raise
        return await gemini().aio.models.generate_content(
            model=modelo, contents=contenidos, config=types.GenerateContentConfig(**ajustes))


async def generar_gemini_con_modelo(modelo: str, contenidos: Any, **ajustes: Any):
    """Llama a Gemini y, si el modelo está saturado o no disponible, reintenta una vez y luego
    prueba con los modelos de respaldo. Devuelve (respuesta, modelo_que_respondió)."""
    candidatos = [modelo] + [m for m in config.modelos_gemini_respaldo if m and m != modelo]
    ultimo_error: Exception | None = None
    for posicion, nombre in enumerate(candidatos):
        intentos = 2 if posicion == 0 else 1
        for intento in range(intentos):
            try:
                return await _llamar(nombre, contenidos, ajustes), nombre
            except Exception as error:  # noqa: BLE001
                if not _conviene_cambiar(error):
                    raise
                ultimo_error = error
                log.warning("Gemini '%s' no disponible (%s). %s", nombre, str(error)[:120],
                            "Reintento en 1.5 s" if intento + 1 < intentos else "Pruebo otro modelo")
                if intento + 1 < intentos:
                    await asyncio.sleep(1.5)
    raise ultimo_error  # type: ignore[misc]


async def generar_gemini(modelo: str, contenidos: Any, **ajustes: Any):
    respuesta, _ = await generar_gemini_con_modelo(modelo, contenidos, **ajustes)
    return respuesta


INSTRUCCIONES = (
    "Eres el analista de investigación de un asistente personal por voz. Responde en español de México, "
    "con datos concretos y actuales. Empieza con una respuesta directa de 1-2 frases y luego los puntos clave "
    "en viñetas cortas. Si las fuentes no alcanzan para responder con seguridad, dilo. No inventes datos."
)


async def buscar_tavily(pregunta: str, max_resultados: int = 5) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20.0) as http:
        respuesta = await http.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {config.tavily_api_key}"},
            json={"query": pregunta, "search_depth": "basic", "max_results": max_resultados,
                  "include_answer": False},
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
    return [{"titulo": r.get("title", ""), "url": r.get("url", ""), "contenido": (r.get("content") or "")[:1500]}
            for r in datos.get("results", [])]


async def _resumir_con_gemini(prompt: str, con_google: bool = False) -> tuple[str, list[dict]]:
    from google.genai import types

    herramientas = [types.Tool(google_search=types.GoogleSearch())] if con_google else None
    respuesta = await generar_gemini(config.modelo_gemini, prompt,
                                     system_instruction=INSTRUCCIONES, tools=herramientas)
    fuentes: list[dict] = []
    if con_google and respuesta.candidates:
        metadatos = getattr(respuesta.candidates[0], "grounding_metadata", None)
        for chunk in (getattr(metadatos, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web and getattr(web, "uri", None):
                fuentes.append({"titulo": getattr(web, "title", "") or web.uri, "url": web.uri})
    return (respuesta.text or "").strip(), fuentes[:6]


async def investigar(pregunta: str) -> dict[str, Any]:
    if not config.gemini_api_key:
        if config.tavily_api_key:
            resultados = await buscar_tavily(pregunta)
            return {"con_web": True, "resultados_sin_resumir": resultados,
                    "nota": "Falta GEMINI_API_KEY: resume tú estos resultados."}
        return {"error": "No hay GEMINI_API_KEY ni TAVILY_API_KEY configuradas para investigar."}

    if config.investigacion_modo == "google":
        resumen, fuentes = await _resumir_con_gemini(pregunta, con_google=True)
        return {"con_web": True, "resumen": resumen, "fuentes": fuentes, "motor": "gemini + google"}

    if config.tavily_api_key:
        resultados = await buscar_tavily(pregunta)
        contexto = "\n\n".join(
            f"[{i}] {r['titulo']} ({r['url']})\n{r['contenido']}" for i, r in enumerate(resultados, 1))
        prompt = (f"Pregunta: {pregunta}\n\nResultados de búsqueda web de hoy:\n{contexto}\n\n"
                  "Responde usando solo estos resultados y cita los números [n] que uses.")
        resumen, _ = await _resumir_con_gemini(prompt)
        return {"con_web": True, "resumen": resumen,
                "fuentes": [{"titulo": r["titulo"], "url": r["url"]} for r in resultados],
                "motor": "gemini + tavily"}

    resumen, _ = await _resumir_con_gemini(
        f"{pregunta}\n\n(No tienes acceso a internet: responde con tu conocimiento y aclara si podría estar desactualizado.)")
    return {"con_web": False, "resumen": resumen, "fuentes": [], "motor": "gemini (sin web)",
            "nota": "Sin búsqueda web: configura TAVILY_API_KEY para datos actuales."}
