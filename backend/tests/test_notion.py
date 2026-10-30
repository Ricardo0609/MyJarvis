import asyncio
import json

import httpx

from app.notion import Notion, construir_secciones, markdown_a_bloques, puntuar_seccion, Nodo

PAGINA = "cdcf919711ba419891bc4634a9eab0a6"


def rt(texto):
    return [{"plain_text": texto, "type": "text", "text": {"content": texto}}]


def b(id_, tipo, texto="", hijos=False, checked=False, toggle=False):
    datos = {"rich_text": rt(texto)}
    if tipo == "to_do":
        datos["checked"] = checked
    if tipo.startswith("heading_"):
        datos["is_toggleable"] = toggle
    if tipo in ("column_list", "column", "unsupported"):
        datos = {}
    return {"object": "block", "id": id_, "type": tipo, tipo: datos, "has_children": hijos}


# Réplica reducida de la estructura real de la página "Objetivos"
ARBOL = {
    PAGINA: [
        b("t-temas", "heading_2", "Temas por aprender a full  (1 mes)", hijos=True, toggle=True),
        b("h-obj", "heading_1", "Objetivos de la semana:"),
        b("btn-1", "unsupported"),
        b("td-tema", "to_do", "Tema de la semana"),
        b("td-extra", "to_do", "Extra:"),
        b("t-trabajo", "heading_3", "Trabajo", hijos=True, toggle=True),
        b("cols", "column_list", hijos=True),
    ],
    "t-temas": [b("td-a", "to_do", "story telling"), b("td-b", "to_do", "Fórmulas y leyes")],
    "t-trabajo": [b("p-vacio", "paragraph"), b("td-ranger", "to_do", "ajustes ranger"),
                  b("td-nav", "to_do", "Navigator", hijos=True)],
    "td-nav": [b("td-visua", "to_do", "Visua", checked=True), b("td-assets", "to_do", "Assets")],
    "cols": [b("col-1", "column", hijos=True), b("col-2", "column", hijos=True)],
    "col-1": [b("h-dia", "heading_2", "Tareas más importantes del día (Alta importancia y alta urgencia)"),
              b("btn-2", "unsupported"),
              b("td-dots", "to_do", "Investigar dots"),
              b("td-asis", "to_do", "Pensar asistente"),
              b("t-octa", "heading_2", "Octagon", hijos=True, toggle=True),
              b("td-fotos", "to_do", "tomar fotos")],
    "t-octa": [b("p-octa", "paragraph", "Checar menú"), b("td-octa", "to_do", "Hacer landing")],
    "col-2": [b("h-sem", "heading_2", " Pendientes de la semana(Alta importancia y baja urgencia)"),
              b("btn-3", "unsupported"),
              b("td-mani", "to_do", "Investigar manifestación"),
              b("td-apuntes", "to_do", "Pasar apuntes"),
              b("p-fin", "paragraph")],
}


def transporte_falso(registro):
    def manejar(request: httpx.Request):
        registro.append((request.method, request.url.path, request.content))
        partes = request.url.path.strip("/").split("/")
        if request.method == "GET" and partes[1] == "blocks" and partes[-1] == "children":
            return httpx.Response(200, json={"results": ARBOL.get(partes[2], []), "has_more": False})
        if request.method == "PATCH" and partes[-1] == "children":
            return httpx.Response(200, json={"results": [{"id": "nuevo-bloque", "type": "to_do"}]})
        if request.method == "PATCH" and partes[1] == "blocks":
            cuerpo = json.loads(request.content)
            return httpx.Response(200, json={"id": partes[2], "type": "to_do",
                                             "to_do": {"rich_text": rt("x"), **cuerpo["to_do"]}})
        return httpx.Response(404, json={"message": "no encontrado"})
    return httpx.MockTransport(manejar)


def nodos(id_):
    return [Nodo(blq, nodos(blq["id"]) if blq["has_children"] else []) for blq in ARBOL.get(id_, [])]


def test_secciones_y_puntos_de_insercion():
    secciones = {s.titulo.strip(): s for s in construir_secciones(PAGINA, nodos(PAGINA))}
    assert list(secciones) == [
        "Temas por aprender a full  (1 mes)", "Objetivos de la semana:", "Trabajo",
        "Tareas más importantes del día (Alta importancia y alta urgencia)", "Octagon",
        "Pendientes de la semana(Alta importancia y baja urgencia)"]

    dia = secciones["Tareas más importantes del día (Alta importancia y alta urgencia)"]
    assert [t.texto for t in dia.tareas] == ["Investigar dots", "Pensar asistente", "tomar fotos"]
    assert dia.contenedor_id == "col-1" and dia.ancla_id == "td-fotos"

    semana = secciones["Pendientes de la semana(Alta importancia y baja urgencia)"]
    assert semana.contenedor_id == "col-2" and semana.ancla_id == "td-apuntes"

    trabajo = secciones["Trabajo"]
    assert trabajo.contenedor_id == "t-trabajo" and trabajo.ancla_id == "td-nav"
    assert [(t.texto, t.nivel, t.hecho) for t in trabajo.tareas] == [
        ("ajustes ranger", 0, False), ("Navigator", 0, False), ("Visua", 1, True), ("Assets", 1, False)]

    objetivos = secciones["Objetivos de la semana:"]
    assert objetivos.contenedor_id == PAGINA and objetivos.ancla_id == "td-extra"
    assert secciones["Octagon"].tareas[0].texto == "Hacer landing"


def test_seccion_vacia_inserta_despues_del_boton():
    arbol = [Nodo(b("h", "heading_2", "Nueva sección")), Nodo(b("btn", "unsupported"))]
    seccion = construir_secciones("raiz", arbol)[0]
    assert seccion.ancla_id == "btn"


def test_elegir_seccion_por_lenguaje_natural():
    titulos = ["Objetivos de la semana:", "Trabajo",
               "Tareas más importantes del día (Alta importancia y alta urgencia)",
               " Pendientes de la semana(Alta importancia y baja urgencia)",
               "Pendientes (Baja importancia alta urgencia) (esto llega a ser más rápido)"]

    def mejor(consulta):
        return max(titulos, key=lambda t: puntuar_seccion(consulta, t))

    assert mejor("pendientes de la semana").startswith(" Pendientes de la semana")
    assert mejor("hoy").startswith("Tareas más importantes del día")
    assert mejor("tareas del día").startswith("Tareas más importantes del día")
    assert mejor("objetivos de la semana") == "Objetivos de la semana:"
    assert mejor("trabajo") == "Trabajo"


def test_agregar_tarea_usa_la_posicion_correcta():
    registro = []
    cliente = Notion(token="ntn", transporte=transporte_falso(registro))

    async def flujo():
        listado = await cliente.listar_objetivos("pendientes de la semana")
        resultado = await cliente.agregar_tarea("pendientes de la semana", "Comprar audífonos")
        marcado = await cliente.marcar_tarea("td-dots", True)
        await cliente.cerrar()
        return listado, resultado, marcado

    listado, resultado, marcado = asyncio.run(flujo())
    assert [t["texto"] for t in listado["secciones"][0]["tareas"]] == ["Investigar manifestación", "Pasar apuntes"]
    assert resultado["seccion"].strip().startswith("Pendientes de la semana")

    patch = next(r for r in registro if r[0] == "PATCH" and r[1].endswith("/children"))
    assert patch[1] == "/v1/blocks/col-2/children"
    cuerpo = json.loads(patch[2])
    assert cuerpo["position"] == {"type": "after_block", "after_block": {"id": "td-apuntes"}}
    assert cuerpo["children"][0]["to_do"]["rich_text"][0]["text"]["content"] == "Comprar audífonos"
    assert marcado["hecho"] is True


def test_markdown_a_bloques():
    md = "# Título\n\nTexto con **negrita** y [link](https://ejemplo.com)\n- punto\n- [x] hecho\n1. uno\n> cita\n---"
    tipos = [blq["type"] for blq in markdown_a_bloques(md)]
    assert tipos == ["heading_1", "paragraph", "bulleted_list_item", "to_do", "numbered_list_item", "quote", "divider"]
    parrafo = markdown_a_bloques("a **b** [c](https://x.com)")[0]["paragraph"]["rich_text"]
    assert parrafo[1]["annotations"]["bold"] is True
    assert parrafo[3]["text"]["link"]["url"] == "https://x.com"
    largo = markdown_a_bloques("x" * 4500)[0]["paragraph"]["rich_text"]
    assert [len(p["text"]["content"]) for p in largo] == [2000, 2000, 500]


def test_calendario_listar_y_crear():
    registro = []
    esquema = {"properties": {
        "Name": {"type": "title"}, "Fecha": {"type": "date"}, "Texto": {"type": "rich_text"},
        "Tipo de evento": {"type": "select", "select": {"options": [{"name": "Partido"}, {"name": "Evento"}]}}}}
    pagina = {"id": "evt-1", "url": "https://notion.so/evt1", "properties": {
        "Name": {"title": rt("Partido de Lakers")},
        "Fecha": {"date": {"start": "2026-11-01T19:00:00.000-06:00", "end": None}},
        "Tipo de evento": {"select": {"name": "Partido"}}, "Texto": {"rich_text": []}}}

    def manejar(request: httpx.Request):
        registro.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        ruta = request.url.path
        if ruta.startswith("/v1/databases/"):
            return httpx.Response(200, json={"data_sources": [{"id": "ds-1", "name": "Actividades"}]})
        if ruta == "/v1/data_sources/ds-1":
            return httpx.Response(200, json=esquema)
        if ruta == "/v1/data_sources/ds-1/query":
            return httpx.Response(200, json={"results": [pagina]})
        if ruta == "/v1/pages":
            return httpx.Response(200, json=pagina)
        return httpx.Response(404, json={"message": "no"})

    cliente = Notion(token="ntn", transporte=httpx.MockTransport(manejar))

    async def flujo():
        eventos = await cliente.listar_eventos("2026-10-30", "2026-11-05")
        creado = await cliente.crear_evento("Partido de Lakers", "2026-11-01T19:00", tipo="Partido")
        return eventos, creado

    eventos, creado = asyncio.run(flujo())
    assert eventos["tipos_disponibles"] == ["Partido", "Evento"]
    assert eventos["eventos"][0]["nombre"] == "Partido de Lakers" and eventos["eventos"][0]["tipo"] == "Partido"
    consulta = next(c for m, r, c in registro if r.endswith("/query"))
    assert consulta["filter"]["and"][0] == {"property": "Fecha", "date": {"on_or_after": "2026-10-30"}}
    alta = next(c for m, r, c in registro if r == "/v1/pages")
    assert alta["parent"] == {"type": "data_source_id", "data_source_id": "ds-1"}
    assert alta["properties"]["Fecha"]["date"] == {"start": "2026-11-01T19:00", "time_zone": "America/Mexico_City"}
    assert alta["properties"]["Tipo de evento"] == {"select": {"name": "Partido"}}
    assert cliente.tipos_evento_en_cache() == ["Partido", "Evento"]
