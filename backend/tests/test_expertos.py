"""Pruebas del reparto de trabajo: archivos, ChatGPT, Gemini (compras, videos, Google) y la pantalla."""
import asyncio
import base64
import dataclasses
import io
import json
import zipfile
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import archivos, cerebro, chatgpt, compras, cuenta_google, sesiones, tools, videos
from app.archivos import ArchivoError, almacen
from app.main import app

from .test_cerebro import ClaudeFalso, tool


def _docx(texto: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p>"
                                        "<w:p><w:r><w:t>Segunda &amp; línea</w:t></w:r></w:p></w:body></w:document>")
    return buffer.getvalue()


def _xlsx() -> bytes:
    from openpyxl import Workbook
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Gastos"
    hoja.append(["Concepto", "Monto"])
    hoja.append(["Renta", 5000])
    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------

def test_lee_word_excel_y_rechaza_formatos_antiguos():
    word = almacen.guardar("reporte.docx", _docx("Hola mundo"))
    assert word.tipo.endswith("wordprocessingml.document")
    assert archivos.extraer_texto(word) == "Hola mundo\nSegunda & línea"
    excel = almacen.guardar("gastos.xlsx", _xlsx())
    assert "--- Hoja «Gastos» ---\nConcepto\tMonto\nRenta\t5000" in archivos.extraer_texto(excel)
    assert archivos.extraer_texto(almacen.guardar("foto.jpg", b"\xff\xd8x", "image/jpeg")) is None
    assert "formato antiguo" in archivos.formato_no_soportado(almacen.guardar("viejo.doc", b"x"))
    with pytest.raises(ArchivoError):
        archivos.extraer_texto(almacen.guardar("roto.docx", b"no es zip"))
    with pytest.raises(ArchivoError):
        almacen.guardar("vacio.txt", b"")
    assert almacen.obtener(word.id) is word and almacen.obtener("no-existe") is None


# ---------------------------------------------------------------------------
# Pantalla: lo que las herramientas mandan directo, sin que Claude lo copie
# ---------------------------------------------------------------------------

def test_productos_se_muestran_tal_cual_y_se_etiqueta_al_experto(monkeypatch):
    panel = {"tipo": "lista", "titulo": "Pantalón", "items": [
        {"texto": "Cargo negro", "detalle": "Liverpool · $899 MXN", "url": "https://liverpool.com.mx/p/1"},
        {"texto": "Malo", "url": "javascript:alert(1)"}], "nota": "Confirma precios"}
    falso = ClaudeFalso([
        [tool("t1", "buscar_productos", {"descripcion": "pantalón cargo negro"})],
        [tool("t2", "responder", {"voz": "Encontré dos opciones, señor.", "mostrar": {"tipo": "texto", "titulo": "x"}})],
    ])

    async def ejecutar_falso(nombre, args):
        return {"total": 2, "_mostrar": panel, "_experto": "Gemini"}

    monkeypatch.setattr(cerebro, "_claude", falso)
    monkeypatch.setattr(cerebro, "ejecutar", ejecutar_falso)
    r = asyncio.run(cerebro.con_claude("búscame un pantalón", [], "sistema"))
    assert r["mostrar"]["titulo"] == "Pantalón" and r["mostrar"]["nota"] == "Confirma precios"
    assert r["mostrar"]["items"][0]["url"] == "https://liverpool.com.mx/p/1"
    assert "url" not in r["mostrar"]["items"][1]  # enlaces peligrosos se descartan
    assert r["expertos"] == ["Claude", "Gemini"]
    visto_por_claude = json.loads(falso.llamadas[1]["messages"][-1]["content"][0]["content"])
    assert visto_por_claude == {"total": 2, "en_pantalla": "Pantalón"}


@pytest.mark.parametrize("mostrar_resultado, esperado", [(True, "Resumen largo"), (False, None)])
def test_resultado_opcional_solo_si_claude_lo_pide(monkeypatch, mostrar_resultado, esperado):
    falso = ClaudeFalso([
        [tool("t1", "investigar", {"pregunta": "¿qué es un transistor?"})],
        [tool("t2", "responder", {"voz": "Es un interruptor electrónico.", "mostrar_resultado": mostrar_resultado})],
    ])

    async def ejecutar_falso(nombre, args):
        return {"resumen": "Resumen largo", "_mostrar_opcional": {"tipo": "texto", "titulo": "Transistor",
                                                                   "contenido": "Resumen largo"},
                "_experto": "Gemini", "_aviso": "Gemini usó un modelo de respaldo."}

    monkeypatch.setattr(cerebro, "_claude", falso)
    monkeypatch.setattr(cerebro, "ejecutar", ejecutar_falso)
    r = asyncio.run(cerebro.con_claude("¿qué es un transistor?", [], "sistema"))
    assert (r["mostrar"] or {}).get("contenido") == esperado
    assert r["aviso"] == "Gemini usó un modelo de respaldo."


def test_guia_e_imagen_pasan_el_filtro_de_pantalla():
    guia = cerebro._limpiar_mostrar({"tipo": "pasos", "titulo": "Hot cakes", "materiales": ["2 huevos", ""],
                                     "pasos": [{"titulo": "Mezcla", "detalle": "Bate todo."}], "consejos": []})
    assert guia["pasos"] == [{"titulo": "Mezcla", "detalle": "Bate todo."}] and guia["materiales"] == ["2 huevos"]
    assert cerebro._limpiar_mostrar({"tipo": "pasos", "titulo": "x", "pasos": []}) is None
    imagen = cerebro._limpiar_mostrar({"tipo": "imagen", "titulo": "Gato", "imagen": "/api/archivo/abc"})
    assert imagen["imagen"] == "/api/archivo/abc"
    assert cerebro._limpiar_mostrar({"tipo": "imagen", "titulo": "x", "imagen": "data:text/html,hola"}) is None


# ---------------------------------------------------------------------------
# Gemini: compras y videos
# ---------------------------------------------------------------------------

def test_productos_ordenados_de_mayor_a_menor_con_enlaces_reales(monkeypatch):
    resultados = [{"titulo": "Pantalón A", "url": "https://tienda-a.mx/1", "contenido": "$1,299"},
                  {"titulo": "Pantalón B", "url": "https://tienda-b.mx/2", "contenido": "$499"},
                  {"titulo": "Blog", "url": "https://blog.mx", "contenido": "los mejores pantalones"}]
    extraidos = {"productos": [
        {"fuente": 2, "nombre": "Cargo B", "tienda": "B", "precio": 499, "moneda": "mxn", "detalle": ""},
        {"fuente": 1, "nombre": "Cargo A", "tienda": "A", "precio": "1,299", "moneda": "MXN", "detalle": "algodón"},
        {"fuente": 1, "nombre": "Sin precio", "tienda": "A", "precio": 0, "moneda": "MXN", "detalle": ""},
        {"fuente": 9, "nombre": "Inventado", "tienda": "X", "precio": 99, "moneda": "MXN", "detalle": ""}]}

    async def tavily_falso(*_, **__):
        return resultados

    async def gemini_falso(*_, **__):
        return NS(text=json.dumps(extraidos))

    monkeypatch.setattr(compras, "buscar_tavily", tavily_falso)
    monkeypatch.setattr(compras, "generar_gemini", gemini_falso)
    r = asyncio.run(compras.buscar_productos("pantalón cargo"))
    items = r["_mostrar"]["items"]
    assert [i["texto"] for i in items] == ["Cargo A", "Cargo B", "Sin precio"]  # el inventado se descarta
    assert items[0]["url"] == "https://tienda-a.mx/1" and items[0]["detalle"] == "A · $1,299 MXN"
    assert r["mas_barato"]["nombre"] == "Cargo B" and "mayor a menor" in r["_mostrar"]["titulo"]
    barato = asyncio.run(compras.buscar_productos("pantalón cargo", "menor_a_mayor", presupuesto_max=600))
    assert [i["texto"] for i in barato["_mostrar"]["items"]] == ["Cargo B", "Sin precio"]


def test_videos_duracion_ids_y_respaldo_con_tavily(monkeypatch):
    assert videos.duracion_legible("PT1H2M3S") == "1:02:03" and videos.duracion_legible("PT4M5S") == "4:05"
    assert videos.id_de_youtube("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert videos.id_de_youtube("https://www.youtube.com/watch?app=desktop&v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    async def tavily_falso(*_, **extra):
        assert extra == {"include_domains": ["youtube.com"]}
        return [{"titulo": "Cómo soldar - YouTube", "url": "https://www.youtube.com/watch?v=abcdefghijk", "contenido": ""},
                {"titulo": "Canal", "url": "https://www.youtube.com/@canal", "contenido": ""}]

    monkeypatch.setattr(videos, "buscar_tavily", tavily_falso)
    monkeypatch.setattr(videos, "config", dataclasses.replace(videos.config, youtube_api_key=""))
    r = asyncio.run(videos.buscar_videos("cómo soldar"))
    assert r["_mostrar"]["items"] == [{"texto": "Cómo soldar", "detalle": "YouTube",
                                       "url": "https://www.youtube.com/watch?v=abcdefghijk",
                                       "imagen": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"}]


# ---------------------------------------------------------------------------
# ChatGPT (con Gemini de respaldo)
# ---------------------------------------------------------------------------

def test_sin_llave_de_openai_gemini_analiza_y_guia(monkeypatch):
    monkeypatch.setattr(chatgpt, "config", dataclasses.replace(chatgpt.config, openai_api_key=""))
    recibido = {}

    async def gemini_falso(contenidos, instrucciones, esquema=None):
        recibido["texto"] = contenidos[0].parts[0].text
        if esquema:
            assert "additionalProperties" not in json.dumps(esquema)
            return json.dumps({"titulo": "Hot cakes", "tiempo": "20 min", "materiales": ["harina"],
                               "pasos": [{"titulo": "Mezclar", "detalle": "Mezcla todo."}], "consejos": []})
        return "El total es $5,000."

    monkeypatch.setattr(chatgpt, "_con_gemini", gemini_falso)
    word = almacen.guardar("renta.docx", _docx("Renta 5000"))
    r = asyncio.run(chatgpt.analizar_archivo([word.id], "¿cuánto es el total?"))
    assert r["analisis"] == "El total es $5,000." and r["_experto"] == "Gemini"
    assert "Renta 5000" in recibido["texto"] and r["_mostrar_opcional"]["tipo"] == "texto"
    g = asyncio.run(chatgpt.guiar("hot cakes"))
    assert g["total_pasos"] == 1 and g["_mostrar"]["tipo"] == "pasos" and g["_mostrar"]["materiales"] == ["harina"]
    assert "falta la llave" in asyncio.run(chatgpt.crear_imagen("un gato"))["error"]
    with pytest.raises(ArchivoError):
        asyncio.run(chatgpt.analizar_archivo(["expirado"], "resume"))


def test_chatgpt_lee_pdf_y_foto_y_crea_imagen(monkeypatch):
    monkeypatch.setattr(chatgpt, "config", dataclasses.replace(chatgpt.config, openai_api_key="sk-x",
                                                              limite_imagenes_dia=1))
    monkeypatch.setattr(chatgpt, "_imagenes_hoy", {})
    pedidos = {}

    class OpenAIFalso:
        def __init__(self):
            self.responses = NS(create=self.crear_respuesta)
            self.images = NS(generate=self.generar)

        async def crear_respuesta(self, **kwargs):
            pedidos["respuesta"] = kwargs
            return NS(output_text="Es un capacitor de 100 µF.")

        async def generar(self, **kwargs):
            pedidos["imagen"] = kwargs
            return NS(data=[NS(b64_json=base64.b64encode(b"\xff\xd8imagen").decode())])

    monkeypatch.setattr(chatgpt, "_cliente", OpenAIFalso())
    pdf = almacen.guardar("hoja.pdf", b"%PDF-1.4")
    foto = almacen.guardar("pieza.jpg", b"\xff\xd8foto", "image/jpeg")
    r = asyncio.run(chatgpt.analizar_archivo([pdf.id, foto.id], "¿qué es esta pieza?"))
    contenido = pedidos["respuesta"]["input"][0]["content"]
    assert [c["type"] for c in contenido] == ["input_file", "input_image", "input_text"]
    assert contenido[0]["file_data"].startswith("data:application/pdf;base64,") and contenido[0]["filename"] == "hoja.pdf"
    assert r["_experto"] == "ChatGPT" and r["analisis"].startswith("Es un capacitor")

    imagen = asyncio.run(chatgpt.crear_imagen("un robot naranja", "vertical"))
    assert pedidos["imagen"]["size"] == "1024x1536" and pedidos["imagen"]["quality"] == "medium"
    guardada = almacen.obtener(imagen["archivo_id"])
    assert guardada.datos == b"\xff\xd8imagen" and imagen["_mostrar"]["imagen"] == guardada.url
    assert "límite" in asyncio.run(chatgpt.crear_imagen("otro"))["error"]  # cuida el saldo


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

def test_google_enlace_correo_y_borrador(monkeypatch):
    monkeypatch.setattr(cuenta_google, "config", dataclasses.replace(
        cuenta_google.config, google_client_id="cid", google_client_secret="sec"))
    g = cuenta_google.Google()
    enlace = g.crear_enlace("https://jarvis.onrender.com/google/callback")
    assert "access_type=offline" in enlace and "prompt=consent" in enlace and "gmail.compose" in enlace
    assert not g.conectado

    carga = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b"<p>Hola <b>Ricardo</b></p>").decode()}},
        {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode("Hola Ricardo, ¿qué tal?".encode()).decode()}}]}
    assert cuenta_google.texto_de_correo(carga) == "Hola Ricardo, ¿qué tal?"
    solo_html = {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b"<style>x</style><p>Hola</p><p>Adios</p>").decode()}}
    assert cuenta_google.texto_de_correo(solo_html) == "Hola\nAdios"

    crudo = base64.urlsafe_b64decode(cuenta_google.mensaje_crudo("ana@correo.com", "Junta", "Nos vemos a las 5."))
    assert b"To: ana@correo.com" in crudo and b"Subject: Junta" in crudo


def test_experto_google_pide_conectar_si_falta_permiso(monkeypatch):
    monkeypatch.setattr(cuenta_google, "config", dataclasses.replace(
        cuenta_google.config, google_client_id="cid", google_client_secret="sec"))
    monkeypatch.setattr(cuenta_google, "google", cuenta_google.Google())
    r = asyncio.run(cuenta_google.experto_google("¿tengo correos nuevos?"))
    assert r["_abrir"]["url"] == "/google/conectar"


# ---------------------------------------------------------------------------
# Servidor: subir y ver archivos
# ---------------------------------------------------------------------------

def test_subir_ver_y_usar_archivos(monkeypatch):
    recibido = {}

    async def procesar_falso(texto, historial, archivos_sesion):
        recibido.update(texto=texto, archivos=archivos_sesion)
        return {"voz": "Listo.", "mostrar": None, "herramientas": [], "cerebro": "claude"}

    import app.main as main
    monkeypatch.setattr(main, "procesar", procesar_falso)
    with TestClient(app) as cliente:
        assert cliente.post("/api/archivo", content=b"x").status_code == 401
        r = cliente.post("/api/archivo", content=b"\x89PNG", headers={
            "X-Clave": "secreto", "X-Nombre": "captura%20de%20pantalla.png", "Content-Type": "image/png"})
        datos = r.json()
        assert r.status_code == 200 and datos["nombre"] == "captura de pantalla.png"
        ver = cliente.get(f"/api/archivo/{datos['id']}")
        assert ver.headers["content-type"] == "image/png" and ver.headers["x-content-type-options"] == "nosniff"
        assert ver.headers["content-disposition"].startswith("inline")

        html = cliente.post("/api/archivo", content=b"<script>alert(1)</script>",
                            headers={"X-Clave": "secreto", "X-Nombre": "pagina.html"}).json()
        peligroso = cliente.get(f"/api/archivo/{html['id']}")
        assert peligroso.headers["content-type"] == "application/octet-stream"
        assert peligroso.headers["content-disposition"].startswith("attachment")
        assert cliente.get("/api/archivo/no-existe").status_code == 404

        cliente.post("/api/comando", json={"texto": "¿qué ves?", "sesion": "s-arch", "archivos": [datos["id"]]},
                     headers={"X-Clave": "secreto"})
        assert f"archivo_id={datos['id']}" in recibido["texto"]
        cliente.post("/api/comando", json={"texto": "¿y el color?", "sesion": "s-arch"}, headers={"X-Clave": "secreto"})
        assert recibido["texto"] == "¿y el color?" and recibido["archivos"][0]["archivo_id"] == datos["id"]
    sesiones.olvidar("s-arch")
    assert sesiones.archivos("s-arch") == []


def test_herramientas_nuevas_segun_configuracion(monkeypatch):
    monkeypatch.setattr(tools, "config", dataclasses.replace(
        tools.config, openai_api_key="sk", youtube_api_key="yt", tavily_api_key="t", gemini_api_key="g"))
    nombres = [h["name"] for h in tools.herramientas_disponibles()]
    for nombre in ("buscar_productos", "buscar_videos", "analizar_archivo", "crear_imagen", "guiar"):
        assert nombre in nombres
    assert "experto_google" not in nombres  # sin GOOGLE_CLIENT_ID no se ofrece


def test_despacho_de_herramientas_nuevas(monkeypatch):
    llamadas = []

    def grabar(nombre):
        async def falso(*args):
            llamadas.append((nombre, args))
            return {"ok": True}
        return falso

    monkeypatch.setattr(tools, "investigar", grabar("investigar"))
    monkeypatch.setattr(tools, "experto_google", grabar("experto_google"))
    monkeypatch.setattr(tools, "buscar_productos", grabar("buscar_productos"))
    monkeypatch.setattr(tools, "buscar_videos", grabar("buscar_videos"))
    monkeypatch.setattr(tools.chatgpt, "analizar_archivo", grabar("analizar_archivo"))
    monkeypatch.setattr(tools.chatgpt, "crear_imagen", grabar("crear_imagen"))
    monkeypatch.setattr(tools.chatgpt, "guiar", grabar("guiar"))
    monkeypatch.setattr(tools.google, "gmail_crear_borrador", grabar("gmail_crear_borrador"))
    ordenes = [("investigar", {"pregunta": "¿qué es RAM?", "necesita_web": False}),
               ("experto_google", {"peticion": "correos de hoy"}),
               ("buscar_productos", {"descripcion": "tenis", "orden": "menor_a_mayor"}),
               ("buscar_videos", {"consulta": "arduino"}),
               ("analizar_archivo", {"archivo_ids": "a1, a2", "instruccion": "resume"}),
               ("crear_imagen", {"descripcion": "un gato"}),
               ("guiar", {"tema": "hot cakes"}),
               ("gmail_crear_borrador", {"asunto": "Hola", "cuerpo": "Texto"})]
    for nombre, args in ordenes:
        assert asyncio.run(tools.ejecutar(nombre, args)) == {"ok": True}
    assert llamadas == [
        ("investigar", ("¿qué es RAM?", False)), ("experto_google", ("correos de hoy",)),
        ("buscar_productos", ("tenis", "menor_a_mayor", None)), ("buscar_videos", ("arduino", 6)),
        ("analizar_archivo", (["a1", "a2"], "resume")), ("crear_imagen", ("un gato", "cuadrada")),
        ("guiar", ("hot cakes", "", [])), ("gmail_crear_borrador", ("Hola", "Texto", ""))]
    assert "Falta el parámetro" in asyncio.run(tools.ejecutar("guiar", {}))["error"]


def test_modo_privado_claude_revisa_google_directo(monkeypatch):
    configurada = dataclasses.replace(cuenta_google.config, google_client_id="cid", google_client_secret="sec",
                                      experto_google="claude")
    monkeypatch.setattr(cuenta_google, "config", configurada)
    monkeypatch.setattr(tools, "config", dataclasses.replace(tools.config, experto_google="claude"))
    sin_conectar = cuenta_google.Google()
    monkeypatch.setattr(cuenta_google, "google", sin_conectar)
    monkeypatch.setattr(tools, "google", sin_conectar)
    nombres = [h["name"] for h in tools.herramientas_disponibles()]
    assert "gmail_buscar" in nombres and "google_calendario_listar" in nombres and "experto_google" not in nombres
    r = asyncio.run(tools.ejecutar("gmail_buscar", {"consulta": "is:unread"}))
    assert r["_abrir"]["url"] == "/google/conectar"
