"""El director: recibe lo que dijiste, decide qué herramientas usar y arma la respuesta {voz, mostrar}.

Cerebro principal: Claude (Haiku 5.5). Alternativa 100% gratis: Gemini (plan gratuito).
Si Claude falla (sin créditos, llave inválida), Gemini toma el control automáticamente.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import config
from .notion import notion
from .prompts import prompt_sistema
from .spotify import spotify
from .tools import ejecutar, herramientas_claude, herramientas_gemini, resultado_como_texto

log = logging.getLogger("jarvis.cerebro")
MAX_PASOS = 8

_claude = None


def cliente_claude():
    global _claude
    if _claude is None:
        import anthropic
        _claude = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key, max_retries=2, timeout=60)
    return _claude


def _limpiar_mostrar(mostrar: Any) -> dict | None:
    if not isinstance(mostrar, dict) or mostrar.get("tipo") not in ("lista", "texto"):
        return None
    limpio: dict[str, Any] = {"tipo": mostrar["tipo"], "titulo": str(mostrar.get("titulo") or "")}
    if mostrar["tipo"] == "lista":
        limpio["items"] = [
            {"texto": str(i.get("texto", "")), "detalle": str(i.get("detalle") or ""), "hecho": bool(i.get("hecho"))}
            for i in (mostrar.get("items") or []) if isinstance(i, dict) and i.get("texto")]
    else:
        limpio["contenido"] = str(mostrar.get("contenido") or "")
    fuentes = [f for f in (mostrar.get("fuentes") or []) if isinstance(f, dict) and f.get("url")]
    if fuentes:
        limpio["fuentes"] = [{"titulo": str(f.get("titulo") or f["url"]), "url": str(f["url"])} for f in fuentes[:8]]
    return limpio


def _respuesta(datos: dict[str, Any], usadas: list[str], cerebro: str,
               abrir: dict | None = None) -> dict[str, Any]:
    voz = str(datos.get("voz") or "Listo.").strip()
    respuesta = {"voz": voz, "mostrar": _limpiar_mostrar(datos.get("mostrar")), "herramientas": usadas,
                 "cerebro": cerebro}
    if abrir:
        respuesta["abrir"] = abrir
    return respuesta


async def _ejecutar_llamadas(llamadas: list[tuple[str, dict]], botones: list[dict]) -> list[dict]:
    """Ejecuta las herramientas en paralelo. Si alguna pide un botón en pantalla (abrir o conectar
    Spotify), se guarda aparte: el cerebro solo se entera de que el botón ya está visible."""
    resultados = list(await asyncio.gather(*(ejecutar(nombre, args) for nombre, args in llamadas)))
    for resultado in resultados:
        boton = resultado.pop("_abrir", None)
        if boton:
            botones.append(boton)
            resultado["boton_en_pantalla"] = boton["texto"]
    return resultados


AVISO_RESPONDER = ("No se envió la respuesta: algunas herramientas devolvieron error. Revisa los resultados "
                   "y vuelve a llamar a responder explicándolo con honestidad.")


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

async def con_claude(texto: str, historial: list[dict], sistema: str) -> dict[str, Any]:
    mensajes: list[dict] = historial + [{"role": "user", "content": texto}]
    usadas: list[str] = []
    botones: list[dict] = []
    for _ in range(MAX_PASOS):
        r = await cliente_claude().messages.create(
            model=config.modelo_claude, max_tokens=2048, system=sistema,
            tools=herramientas_claude(), messages=mensajes)
        mensajes.append({"role": "assistant", "content": r.content})
        llamadas = [b for b in r.content if b.type == "tool_use"]
        final = next((b for b in llamadas if b.name == "responder"), None)
        otras = [b for b in llamadas if b.name != "responder"]

        if not llamadas:
            texto_final = "".join(b.text for b in r.content if b.type == "text").strip()
            return _respuesta({"voz": texto_final or "Listo."}, usadas, "claude", botones[-1] if botones else None)

        resultados = await _ejecutar_llamadas([(b.name, b.input) for b in otras], botones)
        usadas += [b.name for b in otras]
        hubo_error = any("error" in res for res in resultados)
        if final and not hubo_error:
            return _respuesta(final.input, usadas, "claude", botones[-1] if botones else None)

        bloques = [{"type": "tool_result", "tool_use_id": b.id, "content": resultado_como_texto(res),
                    **({"is_error": True} if "error" in res else {})} for b, res in zip(otras, resultados)]
        if final:
            bloques.append({"type": "tool_result", "tool_use_id": final.id, "content": AVISO_RESPONDER,
                            "is_error": True})
        mensajes.append({"role": "user", "content": bloques})
    return _respuesta({"voz": "Me tomó demasiados pasos, señor. ¿Lo intentamos de otra forma?"}, usadas, "claude")


# ---------------------------------------------------------------------------
# Gemini (alternativa gratis)
# ---------------------------------------------------------------------------

async def con_gemini(texto: str, historial: list[dict], sistema: str) -> dict[str, Any]:
    from google.genai import types

    from .research import generar_gemini_con_modelo

    contenidos = [types.Content(role="user" if m["role"] == "user" else "model",
                                parts=[types.Part(text=m["content"])]) for m in historial]
    contenidos.append(types.Content(role="user", parts=[types.Part(text=texto)]))
    ajustes = dict(system_instruction=sistema, tools=herramientas_gemini(),
                   automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    usadas: list[str] = []
    botones: list[dict] = []
    modelo = config.modelo_gemini_orquestador
    for _ in range(MAX_PASOS):
        # Si el modelo principal está saturado se usa uno de respaldo, y se mantiene el resto de la orden.
        r, modelo = await generar_gemini_con_modelo(modelo, contenidos, **ajustes)
        if not r.candidates or not r.candidates[0].content:
            return _respuesta({"voz": "No pude procesar eso, señor. ¿Me lo repite de otra forma?"}, usadas, "gemini")
        contenidos.append(r.candidates[0].content)
        llamadas = r.function_calls or []
        final = next((c for c in llamadas if c.name == "responder"), None)
        otras = [c for c in llamadas if c.name != "responder"]

        if not llamadas:
            return _respuesta({"voz": (r.text or "Listo.").strip()}, usadas, "gemini", botones[-1] if botones else None)

        resultados = await _ejecutar_llamadas([(c.name, dict(c.args or {})) for c in otras], botones)
        usadas += [c.name for c in otras]
        hubo_error = any("error" in res for res in resultados)
        if final and not hubo_error:
            return _respuesta(dict(final.args or {}), usadas, "gemini", botones[-1] if botones else None)

        partes = [types.Part(function_response=types.FunctionResponse(id=c.id, name=c.name, response=res))
                  for c, res in zip(otras, resultados)]
        if final:
            partes.append(types.Part(function_response=types.FunctionResponse(
                id=final.id, name="responder", response={"error": AVISO_RESPONDER})))
        contenidos.append(types.Content(role="user", parts=partes))
    return _respuesta({"voz": "Me tomó demasiados pasos, señor. ¿Lo intentamos de otra forma?"}, usadas, "gemini")


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

async def procesar(texto: str, historial: list[dict]) -> dict[str, Any]:
    sistema = prompt_sistema(notion.titulos_en_cache(), notion.tipos_evento_en_cache(), notion.configurado,
                             spotify.configurado)
    cerebro = config.orquestador_efectivo
    if cerebro == "ninguno":
        return _respuesta({"voz": "No tengo cerebro conectado: falta configurar la llave de Claude o de Gemini."},
                          [], "ninguno")

    if cerebro == "claude":
        try:
            return await con_claude(texto, historial, sistema)
        except Exception as error:  # noqa: BLE001
            log.warning("Claude falló (%s: %s)", type(error).__name__, error)
            if not config.gemini_api_key:
                return _respuesta({"voz": f"Claude no respondió: {_explicar_error(error)}"}, [], "claude")
            respuesta = await con_gemini(texto, historial, sistema)
            respuesta["aviso"] = f"Claude no respondió ({_explicar_error(error)}); respondió Gemini."
            return respuesta

    try:
        return await con_gemini(texto, historial, sistema)
    except Exception as error:  # noqa: BLE001
        log.warning("Gemini falló (%s: %s)", type(error).__name__, error)
        if config.anthropic_api_key:
            try:
                respuesta = await con_claude(texto, historial, sistema)
                respuesta["aviso"] = f"Gemini no respondió ({_explicar_error(error)}); respondió Claude."
                return respuesta
            except Exception as error_claude:  # noqa: BLE001
                log.warning("Claude tampoco respondió (%s)", error_claude)
        respuesta = _respuesta({"voz": f"Gemini no respondió: {_explicar_error(error)}"}, [], "gemini")
        respuesta["aviso"] = f"Detalle técnico: {type(error).__name__}: {str(error)[:220]}"
        return respuesta


def _explicar_error(error: Exception) -> str:
    texto = f"{type(error).__name__} {error}".lower()
    if "credit" in texto or "billing" in texto or "balance" in texto:
        return "parece que se acabaron los créditos"
    if "api_key_invalid" in texto or "api key not valid" in texto or "401" in texto or "authentication" in texto:
        return "la llave de la API no es válida"
    if "503" in texto or "unavailable" in texto or "high demand" in texto or "overloaded" in texto:
        return "los modelos de Google están saturados en este momento, intenta en un minuto"
    if "429" in texto or "rate" in texto or "quota" in texto or "resource_exhausted" in texto:
        return "llegué al límite de uso por ahora, intenta en un minuto"
    if "404" in texto or "not_found" in texto or "not found" in texto:
        return "el modelo configurado no está disponible en tu cuenta"
    if "403" in texto or "permission" in texto:
        return "la llave no tiene permiso para ese modelo"
    if "400" in texto or "invalid_argument" in texto:
        return "rechazó la petición por un dato inválido"
    if "timeout" in texto or "timed out" in texto:
        return "tardó demasiado en contestar"
    if "connect" in texto or "ssl" in texto or "certificate" in texto or "proxy" in texto:
        return "no pude conectarme a internet desde el servidor"
    return "ocurrió un error inesperado"
