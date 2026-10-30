"""Herramientas ("manos") que el cerebro puede usar. Se definen una sola vez y se traducen
al formato de Claude o de Gemini."""
from __future__ import annotations

import json
import logging
from typing import Any

from .config import config
from .notion import NotionError, notion
from .research import investigar

log = logging.getLogger("jarvis.tools")

_OBJ = {"type": "object"}

HERRAMIENTAS: list[dict[str, Any]] = [
    {
        "name": "objetivos_listar",
        "description": (
            "Lee los pendientes de la página 'Objetivos' de Notion (checkboxes agrupados por encabezado/sección, "
            "por ejemplo tareas del día, pendientes de la semana, trabajo, aprender). Devuelve ids de sección y de "
            "tarea. Úsala antes de marcar o editar tareas, y cuando pregunten qué tienen pendiente."),
        "parameters": {**_OBJ, "properties": {
            "seccion": {"type": "string", "description": "Título (o parte) o id de una sección. Vacío = todas."},
            "incluir_hechas": {"type": "boolean", "description": "Incluir tareas ya marcadas. Por defecto false."},
        }},
    },
    {
        "name": "objetivos_agregar",
        "description": "Agrega una tarea (checkbox) a una sección de la página 'Objetivos'.",
        "parameters": {**_OBJ, "properties": {
            "seccion": {"type": "string", "description": "Título exacto o id de la sección (de objetivos_listar)."},
            "texto": {"type": "string", "description": "Texto de la tarea, claro y breve."},
        }, "required": ["seccion", "texto"]},
    },
    {
        "name": "objetivos_marcar",
        "description": "Marca (o desmarca) una tarea de 'Objetivos' como hecha.",
        "parameters": {**_OBJ, "properties": {
            "tarea_id": {"type": "string", "description": "id de la tarea (de objetivos_listar)."},
            "hecho": {"type": "boolean", "description": "true = hecha, false = pendiente. Por defecto true."},
        }, "required": ["tarea_id"]},
    },
    {
        "name": "objetivos_editar",
        "description": "Cambia el texto de una tarea existente de 'Objetivos'.",
        "parameters": {**_OBJ, "properties": {
            "tarea_id": {"type": "string"},
            "texto": {"type": "string"},
        }, "required": ["tarea_id", "texto"]},
    },
    {
        "name": "calendario_listar",
        "description": "Lista eventos del calendario 'Actividades del mes' de Notion entre dos fechas (inclusive).",
        "parameters": {**_OBJ, "properties": {
            "desde": {"type": "string", "description": "Fecha inicial AAAA-MM-DD."},
            "hasta": {"type": "string", "description": "Fecha final AAAA-MM-DD."},
        }, "required": ["desde", "hasta"]},
    },
    {
        "name": "calendario_crear",
        "description": "Crea un evento en el calendario 'Actividades del mes'.",
        "parameters": {**_OBJ, "properties": {
            "nombre": {"type": "string"},
            "inicio": {"type": "string", "description": "AAAA-MM-DD o AAAA-MM-DDTHH:MM (hora local)."},
            "fin": {"type": "string", "description": "Opcional, mismo formato que inicio."},
            "tipo": {"type": "string", "description": "Opcional: uno de los tipos de evento existentes."},
            "notas": {"type": "string", "description": "Opcional."},
        }, "required": ["nombre", "inicio"]},
    },
    {
        "name": "calendario_editar",
        "description": "Cambia nombre, fecha, tipo o notas de un evento existente (id de calendario_listar).",
        "parameters": {**_OBJ, "properties": {
            "evento_id": {"type": "string"},
            "nombre": {"type": "string"},
            "inicio": {"type": "string"},
            "fin": {"type": "string"},
            "tipo": {"type": "string"},
            "notas": {"type": "string"},
        }, "required": ["evento_id"]},
    },
    {
        "name": "notion_buscar",
        "description": "Busca páginas de Notion por título o contenido. Devuelve ids para leerlas.",
        "parameters": {**_OBJ, "properties": {"texto": {"type": "string"}}, "required": ["texto"]},
    },
    {
        "name": "notion_leer_pagina",
        "description": "Lee el contenido completo de una página de Notion (para resumir, analizar o responder sobre ella).",
        "parameters": {**_OBJ, "properties": {"pagina_id": {"type": "string"}}, "required": ["pagina_id"]},
    },
    {
        "name": "notion_crear_pagina",
        "description": (
            "Crea una página nueva en Notion con contenido en markdown sencillo (#, ##, -, - [ ], 1., >, **negritas**). "
            "Sin padre_id se crea en la página de notas de JARVIS."),
        "parameters": {**_OBJ, "properties": {
            "titulo": {"type": "string"},
            "contenido_markdown": {"type": "string"},
            "padre_id": {"type": "string", "description": "Opcional: id de la página donde crearla."},
        }, "required": ["titulo", "contenido_markdown"]},
    },
    {
        "name": "notion_agregar_a_pagina",
        "description": "Agrega contenido (markdown sencillo) al final de una página existente.",
        "parameters": {**_OBJ, "properties": {
            "pagina_id": {"type": "string"},
            "contenido_markdown": {"type": "string"},
        }, "required": ["pagina_id", "contenido_markdown"]},
    },
    {
        "name": "investigar",
        "description": (
            "Delegar a Gemini (el experto en investigación) cualquier pregunta que necesite información actual de "
            "internet: noticias, precios, lanzamientos, clima, datos que cambian, comparativas, recomendaciones."),
        "parameters": {**_OBJ, "properties": {
            "pregunta": {"type": "string", "description": "Pregunta completa y autocontenida, con contexto."},
        }, "required": ["pregunta"]},
    },
]

RESPONDER: dict[str, Any] = {
    "name": "responder",
    "description": (
        "SIEMPRE termina llamando esta herramienta con tu respuesta final. 'voz' es lo que se dirá en voz alta. "
        "'mostrar' solo cuando el usuario pidió ver algo o la respuesta es una lista/texto largo."),
    "parameters": {**_OBJ, "properties": {
        "voz": {"type": "string", "description": "1 a 3 frases naturales para decir en voz alta. Sin markdown, sin URLs."},
        "mostrar": {
            "type": "object",
            "description": "Opcional. Contenido visual para el panel.",
            "properties": {
                "tipo": {"type": "string", "enum": ["lista", "texto"]},
                "titulo": {"type": "string"},
                "items": {"type": "array", "description": "Para tipo lista.", "items": {
                    "type": "object", "properties": {
                        "texto": {"type": "string"},
                        "detalle": {"type": "string", "description": "Fecha, sección o nota corta."},
                        "hecho": {"type": "boolean"},
                    }, "required": ["texto"]}},
                "contenido": {"type": "string", "description": "Para tipo texto: markdown sencillo."},
                "fuentes": {"type": "array", "items": {"type": "object", "properties": {
                    "titulo": {"type": "string"}, "url": {"type": "string"}}, "required": ["url"]}},
            },
            "required": ["tipo", "titulo"],
        },
    }, "required": ["voz"]},
}


def herramientas_disponibles() -> list[dict[str, Any]]:
    """Solo ofrece al cerebro las herramientas que de verdad están configuradas
    (así no pierde tiempo intentando usar Notion si todavía no lo conectas)."""
    disponibles = []
    for h in HERRAMIENTAS:
        nombre = h["name"]
        if nombre.startswith(("objetivos_", "calendario_", "notion_")) and not notion.configurado:
            continue
        if nombre.startswith("objetivos_") and not config.notion_objetivos_id:
            continue
        if nombre.startswith("calendario_") and not (config.notion_calendario_db_id or config.notion_calendario_ds_id):
            continue
        if nombre == "investigar" and not (config.gemini_api_key or config.tavily_api_key):
            continue
        disponibles.append(h)
    return disponibles


def herramientas_claude() -> list[dict[str, Any]]:
    todas = herramientas_disponibles() + [RESPONDER]
    definiciones = [{"name": h["name"], "description": h["description"], "input_schema": h["parameters"]}
                    for h in todas]
    # Cachea las definiciones (son siempre iguales) para que cada llamada cueste menos.
    definiciones[-1]["cache_control"] = {"type": "ephemeral"}
    return definiciones


def herramientas_gemini():
    from google.genai import types
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=h["name"], description=h["description"],
                                  parameters_json_schema=h["parameters"])
        for h in herramientas_disponibles() + [RESPONDER]])]


def _texto_resultado(resultado: Any, limite: int = 14000) -> str:
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    return texto if len(texto) <= limite else texto[:limite] + '… (recortado)"}'


async def ejecutar(nombre: str, args: dict[str, Any]) -> dict[str, Any]:
    args = args or {}
    try:
        if nombre == "objetivos_listar":
            return await notion.listar_objetivos(args.get("seccion") or None, bool(args.get("incluir_hechas")))
        if nombre == "objetivos_agregar":
            return await notion.agregar_tarea(args["seccion"], args["texto"])
        if nombre == "objetivos_marcar":
            return await notion.marcar_tarea(args["tarea_id"], args.get("hecho", True) is not False)
        if nombre == "objetivos_editar":
            return await notion.editar_tarea(args["tarea_id"], args["texto"])
        if nombre == "calendario_listar":
            return await notion.listar_eventos(args["desde"], args["hasta"])
        if nombre == "calendario_crear":
            return await notion.crear_evento(args["nombre"], args["inicio"], args.get("fin"),
                                             args.get("tipo"), args.get("notas"))
        if nombre == "calendario_editar":
            return await notion.editar_evento(args["evento_id"], args.get("nombre"), args.get("inicio"),
                                              args.get("fin"), args.get("tipo"), args.get("notas"))
        if nombre == "notion_buscar":
            return await notion.buscar(args["texto"])
        if nombre == "notion_leer_pagina":
            return await notion.leer_pagina(args["pagina_id"])
        if nombre == "notion_crear_pagina":
            return await notion.crear_pagina(args["titulo"], args["contenido_markdown"], args.get("padre_id"))
        if nombre == "notion_agregar_a_pagina":
            return await notion.agregar_a_pagina(args["pagina_id"], args["contenido_markdown"])
        if nombre == "investigar":
            return await investigar(args["pregunta"])
        return {"error": f"Herramienta desconocida: {nombre}"}
    except KeyError as faltante:
        return {"error": f"Falta el parámetro {faltante} para {nombre}."}
    except NotionError as error:
        log.warning("Herramienta %s devolvió error: %s", nombre, error)
        return {"error": str(error)}
    except Exception as error:  # noqa: BLE001 — el cerebro debe enterarse de cualquier fallo y explicarlo
        log.exception("Fallo en herramienta %s", nombre)
        return {"error": f"{type(error).__name__}: {error}"}


def resultado_como_texto(resultado: dict[str, Any]) -> str:
    return _texto_resultado(resultado)
