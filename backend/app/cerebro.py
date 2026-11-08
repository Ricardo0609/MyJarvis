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


# Quién resolvió cada herramienta (se muestra arriba a la derecha, ej. "CLAUDE · GEMINI").
EXPERTO_POR_HERRAMIENTA = {"investigar": "Gemini", "experto_google": "Gemini", "buscar_productos": "Gemini",
                           "buscar_videos": "YouTube", "analizar_archivo": "ChatGPT", "crear_imagen": "ChatGPT",
                           "guiar": "ChatGPT"}
TIPOS_PANEL = ("lista", "texto", "imagen", "pasos")


def _enlace_seguro(url: Any) -> str:
    """Solo enlaces web o archivos de JARVIS (nada de javascript: ni rutas raras)."""
    url = str(url or "").strip()
    return url if url.startswith(("https://", "http://", "/api/archivo/")) else ""


def _textos(valores: Any, limite: int) -> list[str]:
    return [str(v) for v in (valores or []) if str(v).strip()][:limite]


def _limpiar_mostrar(mostrar: Any) -> dict | None:
    if not isinstance(mostrar, dict) or mostrar.get("tipo") not in TIPOS_PANEL:
        return None
    tipo = mostrar["tipo"]
    limpio: dict[str, Any] = {"tipo": tipo, "titulo": str(mostrar.get("titulo") or "")}
    if tipo == "lista":
        limpio["items"] = []
        for i in mostrar.get("items") or []:
            if not isinstance(i, dict) or not i.get("texto"):
                continue
            item = {"texto": str(i.get("texto", "")), "detalle": str(i.get("detalle") or ""), "hecho": bool(i.get("hecho"))}
            for campo in ("url", "imagen"):
                if _enlace_seguro(i.get(campo)):
                    item[campo] = _enlace_seguro(i.get(campo))
            if i.get("nota"):
                item["nota"] = str(i["nota"])
            limpio["items"].append(item)
    elif tipo == "imagen":
        if not _enlace_seguro(mostrar.get("imagen")):
            return None
        limpio.update(imagen=_enlace_seguro(mostrar["imagen"]), nombre=str(mostrar.get("nombre") or "imagen.jpg"),
                      contenido=str(mostrar.get("contenido") or ""))
    elif tipo == "pasos":
        pasos = [{"titulo": str(p.get("titulo") or ""), "detalle": str(p.get("detalle") or "")}
                 for p in mostrar.get("pasos") or [] if isinstance(p, dict)]
        if not pasos:
            return None
        limpio.update(pasos=pasos, tiempo=str(mostrar.get("tiempo") or ""),
                      materiales=_textos(mostrar.get("materiales"), 30), consejos=_textos(mostrar.get("consejos"), 8))
    else:
        limpio["contenido"] = str(mostrar.get("contenido") or "")
    if mostrar.get("nota"):
        limpio["nota"] = str(mostrar["nota"])
    fuentes = [f for f in (mostrar.get("fuentes") or []) if isinstance(f, dict) and _enlace_seguro(f.get("url"))]
    if fuentes:
        limpio["fuentes"] = [{"titulo": str(f.get("titulo") or f["url"]), "url": str(f["url"])} for f in fuentes[:8]]
    return limpio


class Extras:
    """Lo que las herramientas dejan para la pantalla sin pasar por el cerebro: botones (abrir/conectar),
    paneles ya armados (productos, videos, imágenes, guías), paneles opcionales y quién trabajó."""

    def __init__(self, director: str) -> None:
        self.director = director
        self.botones: list[dict] = []
        self.paneles: list[dict] = []
        self.opcionales: list[dict] = []
        self.avisos: list[str] = []
        self.expertos: list[str] = []

    def recoger(self, nombre: str, resultado: dict[str, Any]) -> None:
        boton = resultado.pop("_abrir", None)
        if boton:
            self.botones.append(boton)
            resultado["boton_en_pantalla"] = boton["texto"]
        experto = resultado.pop("_experto", None) or EXPERTO_POR_HERRAMIENTA.get(nombre)
        if experto and "error" not in resultado and experto not in self.expertos:
            self.expertos.append(experto)
        aviso = resultado.pop("_aviso", None)
        if aviso:
            self.avisos.append(aviso)
        panel = _limpiar_mostrar(resultado.pop("_mostrar", None))
        if panel:
            self.paneles.append(panel)
            resultado["en_pantalla"] = panel["titulo"] or panel["tipo"]
        opcional = _limpiar_mostrar(resultado.pop("_mostrar_opcional", None))
        if opcional:
            self.opcionales.append(opcional)
            resultado["puede_mostrarse"] = True


def _respuesta(datos: dict[str, Any], usadas: list[str], cerebro: str, extras: Extras | None = None) -> dict[str, Any]:
    voz = str(datos.get("voz") or "Listo.").strip()
    mostrar = None
    if extras and extras.paneles:
        mostrar = extras.paneles[-1]  # productos, videos, imagen o guía: siempre se muestran tal cual
    elif extras and extras.opcionales and datos.get("mostrar_resultado"):
        mostrar = extras.opcionales[-1]
    if mostrar is None:
        mostrar = _limpiar_mostrar(datos.get("mostrar"))
    nombre = "Gemini" if cerebro == "gemini" else "Claude"
    respuesta: dict[str, Any] = {"voz": voz, "mostrar": mostrar, "herramientas": usadas, "cerebro": cerebro,
                                 "expertos": [nombre] + [e for e in (extras.expertos if extras else []) if e != nombre]}
    if extras and extras.botones:
        respuesta["abrir"] = extras.botones[-1]
    if extras and extras.avisos:
        respuesta["aviso"] = " ".join(dict.fromkeys(extras.avisos))
    return respuesta


async def _ejecutar_llamadas(llamadas: list[tuple[str, dict]], extras: Extras) -> list[dict]:
    """Ejecuta las herramientas en paralelo y aparta lo que va directo a la pantalla: el cerebro solo se
    entera de que ya está visible (así no tiene que repetir listas largas, y responde más rápido)."""
    resultados = list(await asyncio.gather(*(ejecutar(nombre, args) for nombre, args in llamadas)))
    for (nombre, _), resultado in zip(llamadas, resultados):
        extras.recoger(nombre, resultado)
    return resultados


AVISO_RESPONDER = ("No se envió la respuesta: algunas herramientas devolvieron error. Revisa los resultados "
                   "y vuelve a llamar a responder explicándolo con honestidad.")


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

async def con_claude(texto: str, historial: list[dict], sistema: str) -> dict[str, Any]:
    mensajes: list[dict] = historial + [{"role": "user", "content": texto}]
    usadas: list[str] = []
    extras = Extras("claude")
    for _ in range(MAX_PASOS):
        r = await cliente_claude().messages.create(
            model=config.modelo_claude, max_tokens=4096, system=sistema,
            tools=herramientas_claude(), messages=mensajes)
        mensajes.append({"role": "assistant", "content": r.content})
        llamadas = [b for b in r.content if b.type == "tool_use"]
        final = next((b for b in llamadas if b.name == "responder"), None)
        otras = [b for b in llamadas if b.name != "responder"]

        if not llamadas:
            texto_final = "".join(b.text for b in r.content if b.type == "text").strip()
            return _respuesta({"voz": texto_final or "Listo."}, usadas, "claude", extras)

        resultados = await _ejecutar_llamadas([(b.name, b.input) for b in otras], extras)
        usadas += [b.name for b in otras]
        hubo_error = any("error" in res for res in resultados)
        if final and not hubo_error:
            return _respuesta(final.input, usadas, "claude", extras)

        bloques = [{"type": "tool_result", "tool_use_id": b.id, "content": resultado_como_texto(res),
                    **({"is_error": True} if "error" in res else {})} for b, res in zip(otras, resultados)]
        if final:
            bloques.append({"type": "tool_result", "tool_use_id": final.id, "content": AVISO_RESPONDER,
                            "is_error": True})
        mensajes.append({"role": "user", "content": bloques})
    return _respuesta({"voz": "Me tomó demasiados pasos, señor. ¿Lo intentamos de otra forma?"}, usadas, "claude", extras)


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
    extras = Extras("gemini")
    modelo = config.modelo_gemini_orquestador
    for _ in range(MAX_PASOS):
        # Si el modelo principal está saturado se usa uno de respaldo, y se mantiene el resto de la orden.
        r, modelo = await generar_gemini_con_modelo(modelo, contenidos, **ajustes)
        if not r.candidates or not r.candidates[0].content:
            return _respuesta({"voz": "No pude procesar eso, señor. ¿Me lo repite de otra forma?"}, usadas, "gemini", extras)
        contenidos.append(r.candidates[0].content)
        llamadas = r.function_calls or []
        final = next((c for c in llamadas if c.name == "responder"), None)
        otras = [c for c in llamadas if c.name != "responder"]

        if not llamadas:
            return _respuesta({"voz": (r.text or "Listo.").strip()}, usadas, "gemini", extras)

        resultados = await _ejecutar_llamadas([(c.name, dict(c.args or {})) for c in otras], extras)
        usadas += [c.name for c in otras]
        hubo_error = any("error" in res for res in resultados)
        if final and not hubo_error:
            return _respuesta(dict(final.args or {}), usadas, "gemini", extras)

        partes = [types.Part(function_response=types.FunctionResponse(id=c.id, name=c.name, response=res))
                  for c, res in zip(otras, resultados)]
        if final:
            partes.append(types.Part(function_response=types.FunctionResponse(
                id=final.id, name="responder", response={"error": AVISO_RESPONDER})))
        contenidos.append(types.Content(role="user", parts=partes))
    return _respuesta({"voz": "Me tomó demasiados pasos, señor. ¿Lo intentamos de otra forma?"}, usadas, "gemini", extras)


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

async def procesar(texto: str, historial: list[dict], archivos: list[dict] | None = None) -> dict[str, Any]:
    sistema = prompt_sistema(notion.titulos_en_cache(), notion.tipos_evento_en_cache(), notion.configurado,
                             spotify.configurado, archivos or [])
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
            respuesta["aviso"] = " ".join(filter(None, [
                f"Claude no respondió ({_explicar_error(error)}); respondió Gemini.", respuesta.get("aviso")]))
            return respuesta

    try:
        return await con_gemini(texto, historial, sistema)
    except Exception as error:  # noqa: BLE001
        log.warning("Gemini falló (%s: %s)", type(error).__name__, error)
        if config.anthropic_api_key:
            try:
                respuesta = await con_claude(texto, historial, sistema)
                respuesta["aviso"] = " ".join(filter(None, [
                    f"Gemini no respondió ({_explicar_error(error)}); respondió Claude.", respuesta.get("aviso")]))
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
