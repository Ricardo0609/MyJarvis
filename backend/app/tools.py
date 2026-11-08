"""Herramientas ("manos") que el cerebro puede usar. Se definen una sola vez y se traducen
al formato de Claude o de Gemini."""
from __future__ import annotations

import json
import logging
from typing import Any

from . import chatgpt
from .archivos import ArchivoError
from .compras import buscar_productos
from .config import config
from .cuenta_google import HERRAMIENTAS_GOOGLE, NOMBRES_GOOGLE, GoogleError, ejecutar_directo, experto_google, google
from .notion import NotionError, notion
from .research import investigar
from .spotify import SpotifyError, spotify
from .videos import buscar_videos

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
        "description": (
            "Agrega una tarea (checkbox) DENTRO de una sección de la página 'Objetivos', justo debajo de la "
            "última tarea de esa sección. Es la única forma correcta de agregar pendientes a Objetivos."),
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
        "description": (
            "Agrega contenido (markdown sencillo) al final de una página existente. NUNCA la uses para agregar "
            "tareas o pendientes a la página 'Objetivos': para eso usa objetivos_agregar."),
        "parameters": {**_OBJ, "properties": {
            "pagina_id": {"type": "string"},
            "contenido_markdown": {"type": "string"},
        }, "required": ["pagina_id", "contenido_markdown"]},
    },
    {
        "name": "investigar",
        "description": (
            "GEMINI · Investigación y preguntas. Úsala para cualquier pregunta de conocimiento o investigación: qué es, "
            "cómo funciona, por qué, explicaciones, datos, consejos, noticias, precios, clima, lanzamientos, "
            "comparativas o recomendaciones. Devuelve el resumen de Gemini (con fuentes si buscó en la web)."),
        "parameters": {**_OBJ, "properties": {
            "pregunta": {"type": "string", "description": "Pregunta completa y autocontenida, con contexto."},
            "necesita_web": {"type": "boolean", "description": (
                "true si necesita datos actuales o de internet (noticias, precios, clima, horarios, novedades). "
                "false para conocimiento general que no cambia (definiciones, historia, ciencia, cómo funciona algo).")},
        }, "required": ["pregunta"]},
    },
    {
        "name": "experto_google",
        "description": (
            "GEMINI · Su cuenta de Google: Gmail (buscar y leer correos), Google Calendar (ver y crear eventos) y "
            "Google Drive (buscar y leer archivos). Pásale la petición completa en lenguaje natural; Gemini la "
            "resuelve y te devuelve un resumen. Ej.: '¿tengo correos importantes de hoy?', 'qué dice el último correo "
            "de mi jefe', '¿qué tengo en Google Calendar mañana?', 'busca en mi Drive el documento de la tesis'. "
            "Si dice solo 'calendario' o 'agenda' sin mencionar Google, usa el calendario de Notion."),
        "parameters": {**_OBJ, "properties": {
            "peticion": {"type": "string", "description": "Lo que necesita, con fechas y nombres concretos."},
        }, "required": ["peticion"]},
    },
    {
        "name": "gmail_crear_borrador",
        "description": (
            "Guarda en Borradores de Gmail un correo que TÚ redactaste (nunca lo envía: él lo revisa y lo manda). "
            "Si no sabes el correo del destinatario, déjalo vacío o búscalo antes con experto_google."),
        "parameters": {**_OBJ, "properties": {
            "asunto": {"type": "string"},
            "cuerpo": {"type": "string", "description": "Texto completo del correo, listo para enviar."},
            "para": {"type": "string", "description": "Opcional: dirección de correo del destinatario."},
        }, "required": ["asunto", "cuerpo"]},
    },
    {
        "name": "buscar_productos",
        "description": (
            "GEMINI · Compras. Busca un producto en tiendas en línea y muestra en pantalla opciones con tienda, precio "
            "y enlace, ordenadas de mayor a menor precio (a menos que pida otro orden). Ej.: 'búscame un pantalón cargo "
            "negro talla 32', 'audífonos inalámbricos con cancelación de ruido de menos de 2000 pesos'."),
        "parameters": {**_OBJ, "properties": {
            "descripcion": {"type": "string", "description": "Producto con todas sus características (tipo, color, talla, marca, material, uso)."},
            "orden": {"type": "string", "enum": ["mayor_a_menor", "menor_a_mayor", "relevancia"],
                      "description": "Por defecto mayor_a_menor."},
            "presupuesto_max": {"type": "number", "description": "Opcional: precio máximo en pesos."},
        }, "required": ["descripcion"]},
    },
    {
        "name": "buscar_videos",
        "description": (
            "Busca videos en YouTube y los muestra en pantalla con enlace, miniatura, canal y duración. Úsala cuando "
            "pida videos, tutoriales en video, tráilers, canciones en video o 'muéstrame un video de…'."),
        "parameters": {**_OBJ, "properties": {
            "consulta": {"type": "string", "description": "Qué buscar, en palabras clave (en el idioma más útil)."},
            "cantidad": {"type": "integer", "description": "Opcional: cuántos videos (1-10). Por defecto 6."},
        }, "required": ["consulta"]},
    },
    {
        "name": "analizar_archivo",
        "description": (
            "CHATGPT · Analiza documentos e imágenes que él adjuntó: PDF, Word, Excel, PowerPoint, texto, CSV y fotos. "
            "Resume, extrae datos, responde preguntas sobre el contenido, revisa errores, compara archivos, describe o "
            "identifica lo que hay en una foto (componentes, plantas, objetos, texto)."),
        "parameters": {**_OBJ, "properties": {
            "archivo_ids": {"type": "array", "items": {"type": "string"},
                            "description": "Uno o varios archivo_id de los archivos de la conversación."},
            "instruccion": {"type": "string", "description": "Qué quiere saber o hacer con el archivo, completo y concreto."},
        }, "required": ["archivo_ids", "instruccion"]},
    },
    {
        "name": "crear_imagen",
        "description": (
            "CHATGPT · Crea una imagen nueva y la muestra en pantalla. Úsala SOLO si pidió crear, generar, dibujar o "
            "diseñar una imagen (cuesta ~1-2 centavos de dólar). Escribe una descripción visual detallada: sujeto, estilo, "
            "colores, composición, luz, texto exacto si lleva."),
        "parameters": {**_OBJ, "properties": {
            "descripcion": {"type": "string"},
            "formato": {"type": "string", "enum": ["cuadrada", "vertical", "horizontal"],
                        "description": "vertical para fondos de celular o pósters; horizontal para banners o fondos de PC."},
        }, "required": ["descripcion"]},
    },
    {
        "name": "guiar",
        "description": (
            "CHATGPT · Guía paso a paso que él sigue mientras lo hace: recetas, armar o reparar algo, proyectos de "
            "electrónica (Arduino, componentes, soldar), instalar o configurar algo, ejercicios. Muestra la guía en "
            "pantalla y él avanza diciendo 'siguiente', 'anterior' o 'repite'."),
        "parameters": {**_OBJ, "properties": {
            "tema": {"type": "string", "description": "Qué quiere hacer, ej. 'hot cakes esponjosos para 4 personas'."},
            "detalles": {"type": "string", "description": "Opcional: lo que tiene, su nivel, restricciones, medidas."},
            "archivo_ids": {"type": "array", "items": {"type": "string"},
                            "description": "Opcional: fotos o archivos de referencia que adjuntó."},
        }, "required": ["tema"]},
    },
    {
        "name": "spotify_reproducir",
        "description": (
            "Pone música en Spotify. Para playlists busca primero en las playlists del usuario ('mi playlist de "
            "Metallica' → consulta 'Metallica') y si no la encuentra, en todo Spotify. Reproduce en el dispositivo "
            "donde tenga Spotify abierto. Si Spotify está cerrado, aparece un botón en pantalla para abrirlo."),
        "parameters": {**_OBJ, "properties": {
            "consulta": {"type": "string", "description": "Nombre de la playlist, canción, artista o álbum (sin 'mi', 'playlist', etc.)."},
            "tipo": {"type": "string", "enum": ["playlist", "cancion", "artista", "album"],
                     "description": "Por defecto playlist. Usa artista si pide 'pon Metallica' sin decir playlist."},
            "aleatorio": {"type": "boolean", "description": "Opcional: true si pidió reproducir en aleatorio."},
        }, "required": ["consulta"]},
    },
    {
        "name": "spotify_control",
        "description": "Controla la música que está sonando en Spotify.",
        "parameters": {**_OBJ, "properties": {
            "accion": {"type": "string",
                       "enum": ["pausa", "reanudar", "siguiente", "anterior", "volumen", "aleatorio", "repetir"]},
            "valor": {"type": "string", "description": (
                "volumen: '0'-'100', '+15', '-15', 'subir' o 'bajar'. aleatorio: 'si' o 'no'. "
                "repetir: 'cancion', 'playlist' o 'no'.")},
        }, "required": ["accion"]},
    },
    {
        "name": "spotify_estado",
        "description": "Dice qué canción está sonando en Spotify, en qué dispositivo y a qué volumen.",
        "parameters": {**_OBJ, "properties": {}},
    },
]

RESPONDER: dict[str, Any] = {
    "name": "responder",
    "description": (
        "SIEMPRE termina llamando esta herramienta con tu respuesta final. 'voz' es lo que se dirá en voz alta. "
        "'mostrar' solo cuando el usuario pidió ver algo o la respuesta es una lista/texto largo."),
    "parameters": {**_OBJ, "properties": {
        "voz": {"type": "string", "description": "1 a 3 frases naturales para decir en voz alta. Sin markdown, sin URLs."},
        "mostrar_resultado": {"type": "boolean", "description": (
            "true para poner en pantalla el contenido completo que ya preparó la herramienta anterior (cuando su "
            "resultado dice puede_mostrarse: true). Así no tienes que copiarlo en 'mostrar'.")},
        "mostrar": {
            "type": "object",
            "description": "Opcional. Contenido visual que TÚ escribes para el panel (listas, textos que redactaste).",
            "properties": {
                "tipo": {"type": "string", "enum": ["lista", "texto"]},
                "titulo": {"type": "string"},
                "items": {"type": "array", "description": "Para tipo lista.", "items": {
                    "type": "object", "properties": {
                        "texto": {"type": "string"},
                        "detalle": {"type": "string", "description": "Fecha, sección o nota corta."},
                        "hecho": {"type": "boolean"},
                        "url": {"type": "string", "description": "Opcional: enlace al tocarlo."},
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
    google_directo = config.experto_google == "claude"
    lista = HERRAMIENTAS + ([{**h, "description": "GOOGLE · " + h["description"]} for h in HERRAMIENTAS_GOOGLE]
                            if google_directo else [])
    for h in lista:
        nombre = h["name"]
        if nombre.startswith(("objetivos_", "calendario_", "notion_")) and not notion.configurado:
            continue
        if nombre.startswith("objetivos_") and not config.notion_objetivos_id:
            continue
        if nombre.startswith("calendario_") and not (config.notion_calendario_db_id or config.notion_calendario_ds_id):
            continue
        if nombre == "investigar" and not (config.gemini_api_key or config.tavily_api_key):
            continue
        if nombre in ("experto_google", "gmail_crear_borrador") and not google.configurado:
            continue
        if nombre in NOMBRES_GOOGLE and not google.configurado:
            continue
        if nombre == "experto_google" and google_directo:
            continue  # Claude revisa Google él mismo
        if nombre == "buscar_productos" and not (config.tavily_api_key and config.gemini_api_key):
            continue
        if nombre == "buscar_videos" and not (config.youtube_api_key or config.tavily_api_key):
            continue
        if nombre in ("analizar_archivo", "guiar") and not (config.openai_api_key or config.gemini_api_key):
            continue
        if nombre == "crear_imagen" and not config.openai_api_key:
            continue  # el prompt le explica que falta la llave de ChatGPT
        if nombre.startswith("spotify_") and not spotify.configurado:
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
            return await investigar(args["pregunta"], args.get("necesita_web", True) is not False)
        if nombre == "experto_google":
            return await experto_google(args["peticion"])
        if nombre in NOMBRES_GOOGLE:
            return await ejecutar_directo(nombre, args)
        if nombre == "gmail_crear_borrador":
            return await google.gmail_crear_borrador(args["asunto"], args["cuerpo"], args.get("para") or "")
        if nombre == "buscar_productos":
            return await buscar_productos(args["descripcion"], args.get("orden") or "mayor_a_menor",
                                          args.get("presupuesto_max"))
        if nombre == "buscar_videos":
            return await buscar_videos(args["consulta"], args.get("cantidad") or 6)
        if nombre == "analizar_archivo":
            return await chatgpt.analizar_archivo(_lista(args["archivo_ids"]), args.get("instruccion") or "")
        if nombre == "crear_imagen":
            return await chatgpt.crear_imagen(args["descripcion"], args.get("formato") or "cuadrada")
        if nombre == "guiar":
            return await chatgpt.guiar(args["tema"], args.get("detalles") or "", _lista(args.get("archivo_ids")))
        if nombre == "spotify_reproducir":
            return await spotify.reproducir(args["consulta"], args.get("tipo") or "playlist", args.get("aleatorio"))
        if nombre == "spotify_control":
            return await spotify.controlar(args["accion"], args.get("valor"))
        if nombre == "spotify_estado":
            return await spotify.estado()
        return {"error": f"Herramienta desconocida: {nombre}"}
    except KeyError as faltante:
        return {"error": f"Falta el parámetro {faltante} para {nombre}."}
    except SpotifyError as error:
        log.warning("Spotify: %s", error)
        resultado: dict[str, Any] = {"error": str(error)}
        if error.abrir:
            resultado["_abrir"] = error.abrir
        return resultado
    except GoogleError as error:
        log.warning("Google: %s", error)
        return {"error": str(error), **({"_abrir": error.abrir} if error.abrir else {})}
    except ArchivoError as error:
        return {"error": str(error)}
    except NotionError as error:
        log.warning("Herramienta %s devolvió error: %s", nombre, error)
        return {"error": str(error)}
    except Exception as error:  # noqa: BLE001 — el cerebro debe enterarse de cualquier fallo y explicarlo
        log.exception("Fallo en herramienta %s", nombre)
        return {"error": f"{type(error).__name__}: {error}"}


def _lista(valor: Any) -> list[str]:
    """Acepta una lista de ids o un solo id en texto (a veces el modelo manda uno solo)."""
    if not valor:
        return []
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    return [str(v) for v in valor]


def resultado_como_texto(resultado: dict[str, Any]) -> str:
    return _texto_resultado(resultado)
