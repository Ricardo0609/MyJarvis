"""ChatGPT (OpenAI): el experto en archivos, imágenes y guías paso a paso.

- analizar_archivo: lee PDF, Word, Excel, PowerPoint, texto y fotos, y responde lo que pidas sobre ellos.
- crear_imagen: genera imágenes (cada una cuesta ~1-2 centavos de dólar en calidad media).
- guiar: arma una guía paso a paso (recetas, armar algo, electrónica, instalar) para seguirla por voz.

Mientras no haya OPENAI_API_KEY, Gemini hace el análisis y las guías (gratis); solo crear imágenes la necesita.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from .archivos import Archivo, ArchivoError, almacen, extraer_texto, formato_no_soportado
from .config import config

log = logging.getLogger("jarvis.chatgpt")
_cliente = None
_imagenes_hoy: dict[str, int] = {}

TAMANOS = {"cuadrada": "1024x1024", "vertical": "1024x1536", "horizontal": "1536x1024"}

INSTRUCCIONES_ANALISIS = (
    "Eres el analista de documentos e imágenes de JARVIS, un asistente personal. Responde en español de México. "
    "Haz exactamente lo que se pide sobre los archivos (resumir, extraer datos, responder una pregunta, revisar, "
    "comparar, describir una foto, identificar componentes). Empieza con la respuesta directa en 1-2 frases y luego "
    "el detalle en markdown sencillo (##, viñetas, **negritas**, tablas como listas). Cita cifras, fechas y nombres "
    "tal como aparecen. Si algo no se ve o no está en el archivo, dilo; no inventes."
)

INSTRUCCIONES_GUIA = (
    "Eres un instructor paciente y práctico. Crea una guía paso a paso en español de México para que la persona la "
    "siga mientras lo hace (con las manos ocupadas, escuchando cada paso en voz alta). Pasos cortos, concretos y en "
    "orden, uno por acción: cantidades, tiempos, temperaturas, medidas, colores de cables o pines exactos. Cada "
    "'detalle' en 1-3 frases que suenen bien en voz alta (sin markdown, sin símbolos raros). Incluye advertencias de "
    "seguridad dentro del paso donde aplican (calor, cuchillos, electricidad, soldar). Entre 4 y 15 pasos."
)

ESQUEMA_GUIA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "tiempo": {"type": "string", "description": "Tiempo total aproximado, ej. '25 minutos'. Vacío si no aplica."},
        "materiales": {"type": "array", "items": {"type": "string"},
                       "description": "Ingredientes, herramientas o componentes con cantidades."},
        "pasos": {"type": "array", "items": {
            "type": "object",
            "properties": {"titulo": {"type": "string"}, "detalle": {"type": "string"}},
            "required": ["titulo", "detalle"], "additionalProperties": False}},
        "consejos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo", "tiempo", "materiales", "pasos", "consejos"],
    "additionalProperties": False,
}


def _sin_extras(esquema: Any) -> Any:
    """Mismo esquema sin 'additionalProperties' (Gemini no lo necesita y algunos modelos lo rechazan)."""
    if isinstance(esquema, dict):
        return {k: _sin_extras(v) for k, v in esquema.items() if k != "additionalProperties"}
    if isinstance(esquema, list):
        return [_sin_extras(v) for v in esquema]
    return esquema


def configurado() -> bool:
    return bool(config.openai_api_key)


def cliente():
    global _cliente
    if _cliente is None:
        from openai import AsyncOpenAI
        _cliente = AsyncOpenAI(api_key=config.openai_api_key, timeout=120, max_retries=1)
    return _cliente


def explicar_error_openai(error: Exception) -> str:
    texto = f"{type(error).__name__} {error}".lower()
    if "insufficient_quota" in texto or "billing" in texto or "quota" in texto:
        return "se acabó el saldo de OpenAI (recarga en platform.openai.com → Billing)"
    if "invalid_api_key" in texto or "incorrect api key" in texto or "401" in texto:
        return "la OPENAI_API_KEY no es válida"
    if "verif" in texto and "organization" in texto:
        return "OpenAI pide verificar tu organización para usar este modelo de imágenes (platform.openai.com → Settings → Organization)"
    if "content_policy" in texto or "safety" in texto or "moderation" in texto:
        return "OpenAI rechazó la petición por sus reglas de contenido"
    if "429" in texto or "rate" in texto:
        return "OpenAI está limitando las peticiones; intenta en un minuto"
    if "timeout" in texto or "timed out" in texto:
        return "OpenAI tardó demasiado en contestar"
    return f"{type(error).__name__}: {str(error)[:160]}"


def _data_url(archivo: Archivo) -> str:
    return f"data:{archivo.tipo};base64,{base64.b64encode(archivo.datos).decode()}"


def _preparar(ids: list[str]) -> list[Archivo]:
    archivos = almacen.varios(ids)
    if not archivos:
        raise ArchivoError("No encontré el archivo: pudo haber expirado (duran 3 horas). Vuelve a adjuntarlo.")
    for archivo in archivos:
        problema = formato_no_soportado(archivo)
        if problema:
            raise ArchivoError(problema)
    return archivos


# ---------------------------------------------------------------------------
# Contenido para cada IA
# ---------------------------------------------------------------------------

def _contenido_openai(archivos: list[Archivo], instruccion: str) -> list[dict]:
    partes: list[dict] = []
    for archivo in archivos:
        if archivo.es_imagen:
            partes.append({"type": "input_image", "image_url": _data_url(archivo), "detail": "auto"})
            continue
        texto = extraer_texto(archivo)
        if texto is not None:
            partes.append({"type": "input_text", "text": f"=== Archivo: {archivo.nombre} ===\n{texto}"})
        else:  # PDF y otros: OpenAI los lee directo (texto e imágenes de cada página)
            partes.append({"type": "input_file", "filename": archivo.nombre, "file_data": _data_url(archivo)})
    partes.append({"type": "input_text", "text": instruccion})
    return partes


def _contenido_gemini(archivos: list[Archivo], instruccion: str) -> list:
    from google.genai import types

    partes = []
    for archivo in archivos:
        if archivo.es_imagen or archivo.es_pdf:
            partes.append(types.Part.from_bytes(data=archivo.datos, mime_type=archivo.tipo))
            continue
        texto = extraer_texto(archivo)
        if texto is None:
            raise ArchivoError(f"No sé leer «{archivo.nombre}». Prueba con PDF, Word, Excel, PowerPoint, texto o foto.")
        partes.append(types.Part(text=f"=== Archivo: {archivo.nombre} ===\n{texto}"))
    partes.append(types.Part(text=instruccion))
    return [types.Content(role="user", parts=partes)]


async def _con_openai(contenido: list[dict], instrucciones: str, formato: dict | None = None) -> str:
    ajustes: dict[str, Any] = {"model": config.modelo_chatgpt, "instructions": instrucciones,
                               "input": [{"role": "user", "content": contenido}], "max_output_tokens": 4000}
    if formato:
        ajustes["text"] = {"format": formato}
    respuesta = await cliente().responses.create(**ajustes)
    return (respuesta.output_text or "").strip()


async def _con_gemini(contenidos: Any, instrucciones: str, esquema: dict | None = None) -> str:
    from .research import generar_gemini

    ajustes: dict[str, Any] = {"system_instruction": instrucciones}
    if esquema:
        ajustes.update(response_mime_type="application/json", response_json_schema=esquema)
    respuesta = await generar_gemini(config.modelo_gemini_orquestador, contenidos, **ajustes)
    return (respuesta.text or "").strip()


async def _experto(contenido_openai, contenido_gemini, instrucciones: str,
                   formato: dict | None = None, esquema: dict | None = None) -> tuple[str, str, str | None]:
    """Usa ChatGPT; si no hay llave o falla, Gemini. Devuelve (texto, experto, aviso)."""
    aviso = None
    if configurado():
        try:
            return await _con_openai(contenido_openai(), instrucciones, formato), "ChatGPT", None
        except ArchivoError:
            raise
        except Exception as error:  # noqa: BLE001
            log.warning("ChatGPT falló: %s", error)
            aviso = f"ChatGPT no respondió ({explicar_error_openai(error)}); lo resolvió Gemini."
            if not config.gemini_api_key:
                raise
    if not config.gemini_api_key:
        raise ArchivoError("Falta OPENAI_API_KEY (ChatGPT) o GEMINI_API_KEY para esto.")
    return await _con_gemini(contenido_gemini(), instrucciones, esquema), "Gemini", aviso


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

async def analizar_archivo(archivo_ids: list[str], instruccion: str) -> dict[str, Any]:
    archivos = _preparar(archivo_ids)
    instruccion = instruccion.strip() or "Resume el contenido y dime lo más importante."
    texto, experto, aviso = await _experto(lambda: _contenido_openai(archivos, instruccion),
                                           lambda: _contenido_gemini(archivos, instruccion),
                                           INSTRUCCIONES_ANALISIS)
    nombres = ", ".join(a.nombre for a in archivos)
    resultado: dict[str, Any] = {
        "archivos": nombres, "analisis": texto, "_experto": experto,
        "_mostrar_opcional": {"tipo": "texto", "titulo": f"Análisis · {nombres}", "contenido": texto}}
    if aviso:
        resultado["_aviso"] = aviso
    return resultado


def _limpiar_guia(datos: Any, tema: str) -> dict[str, Any]:
    if not isinstance(datos, dict):
        datos = {}
    pasos = [{"titulo": str(p.get("titulo") or f"Paso {i}").strip(), "detalle": str(p.get("detalle") or "").strip()}
             for i, p in enumerate(datos.get("pasos") or [], 1) if isinstance(p, dict)]
    if not pasos:
        raise ArchivoError("No pude armar la guía. ¿Me das más detalles de lo que quieres hacer?")
    return {"tipo": "pasos", "titulo": str(datos.get("titulo") or tema)[:120],
            "tiempo": str(datos.get("tiempo") or ""),
            "materiales": [str(m) for m in (datos.get("materiales") or []) if str(m).strip()][:30],
            "pasos": pasos[:20],
            "consejos": [str(c) for c in (datos.get("consejos") or []) if str(c).strip()][:8]}


async def guiar(tema: str, detalles: str = "", archivo_ids: list[str] | None = None) -> dict[str, Any]:
    archivos = _preparar(archivo_ids) if archivo_ids else []
    pedido = f"Quiero hacer: {tema}." + (f"\nDetalles: {detalles}" if detalles else "")
    if archivos:
        pedido += "\nUsa los archivos o fotos adjuntos como referencia (componentes, diagrama, ingredientes que tengo)."
    formato = {"type": "json_schema", "name": "guia", "schema": ESQUEMA_GUIA, "strict": True}
    texto, experto, aviso = await _experto(lambda: _contenido_openai(archivos, pedido),
                                           lambda: _contenido_gemini(archivos, pedido),
                                           INSTRUCCIONES_GUIA, formato=formato, esquema=_sin_extras(ESQUEMA_GUIA))
    try:
        datos = json.loads(texto.strip().removeprefix("```json").removesuffix("```"))
    except json.JSONDecodeError as error:
        raise ArchivoError("La guía llegó incompleta. ¿Lo intentamos de nuevo?") from error
    guia = _limpiar_guia(datos, tema)
    resultado: dict[str, Any] = {
        "titulo": guia["titulo"], "total_pasos": len(guia["pasos"]), "tiempo": guia["tiempo"],
        "materiales": len(guia["materiales"]), "_experto": experto, "_mostrar": guia,
        "nota": "La guía ya está en pantalla. Él la recorre diciendo 'siguiente', 'anterior' o 'repite'."}
    if aviso:
        resultado["_aviso"] = aviso
    return resultado


async def crear_imagen(descripcion: str, formato: str = "cuadrada") -> dict[str, Any]:
    if not configurado():
        return {"error": "Para crear imágenes falta la llave de ChatGPT (OPENAI_API_KEY en el servidor)."}
    hoy = time.strftime("%Y-%m-%d")
    if _imagenes_hoy.get(hoy, 0) >= config.limite_imagenes_dia:
        return {"error": f"Ya se crearon {config.limite_imagenes_dia} imágenes hoy (límite LIMITE_IMAGENES_DIA "
                         "para cuidar tu saldo). Mañana se reinicia."}
    tamano = TAMANOS.get(formato, TAMANOS["cuadrada"])
    try:
        respuesta = await cliente().images.generate(
            model=config.modelo_imagen, prompt=descripcion, size=tamano, quality=config.calidad_imagen,
            n=1, output_format="jpeg", output_compression=88)
    except Exception as error:  # noqa: BLE001
        log.warning("No se pudo crear la imagen: %s", error)
        return {"error": f"No se pudo crear la imagen: {explicar_error_openai(error)}."}
    datos = respuesta.data[0].b64_json if respuesta.data else None
    if not datos:
        return {"error": "OpenAI no devolvió ninguna imagen."}
    if hoy not in _imagenes_hoy:
        _imagenes_hoy.clear()  # solo se cuenta el día de hoy
    _imagenes_hoy[hoy] = _imagenes_hoy.get(hoy, 0) + 1
    nombre = "jarvis-" + "-".join(descripcion.lower().split()[:5])[:50] + ".jpg"
    archivo = almacen.guardar(nombre, base64.b64decode(datos), "image/jpeg", origen="creado")
    return {"ok": True, "archivo_id": archivo.id, "_experto": "ChatGPT",
            "_mostrar": {"tipo": "imagen", "titulo": descripcion[:90], "imagen": archivo.url, "nombre": archivo.nombre,
                         "contenido": descripcion},
            "nota": "La imagen ya está en pantalla con botón para descargarla (dura 3 horas en el servidor)."}
