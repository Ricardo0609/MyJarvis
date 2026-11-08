import asyncio
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from app import cerebro
from app.main import app


class ClaudeFalso:
    """Simula la API de Claude devolviendo respuestas preparadas en orden."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.messages = self

    async def create(self, **kwargs):
        self.llamadas.append({**kwargs, "messages": list(kwargs["messages"])})
        return NS(content=self.respuestas.pop(0))


def tool(id_, nombre, entrada):
    return NS(type="tool_use", id=id_, name=nombre, input=entrada)


def test_claude_usa_herramienta_y_responde(monkeypatch):
    falso = ClaudeFalso([
        [NS(type="text", text="Reviso."), tool("t1", "objetivos_listar", {"seccion": "hoy"})],
        [tool("t2", "responder", {"voz": "Tiene dos tareas hoy.", "mostrar": {
            "tipo": "lista", "titulo": "Hoy", "items": [{"texto": "A"}, {"texto": "B", "hecho": True}]}})],
    ])
    ejecutadas = []

    async def ejecutar_falso(nombre, args):
        ejecutadas.append((nombre, args))
        return {"secciones": [{"seccion": "Hoy", "tareas": [{"id": "1", "texto": "A"}]}]}

    monkeypatch.setattr(cerebro, "_claude", falso)
    monkeypatch.setattr(cerebro, "ejecutar", ejecutar_falso)
    r = asyncio.run(cerebro.con_claude("¿qué tengo hoy?", [], "sistema"))

    assert ejecutadas == [("objetivos_listar", {"seccion": "hoy"})]
    assert r["voz"] == "Tiene dos tareas hoy."
    assert r["mostrar"]["items"][1] == {"texto": "B", "detalle": "", "hecho": True}
    assert r["herramientas"] == ["objetivos_listar"] and r["cerebro"] == "claude"
    segundo_turno = falso.llamadas[1]["messages"][-1]["content"][0]
    assert segundo_turno["type"] == "tool_result" and segundo_turno["tool_use_id"] == "t1"
    assert falso.llamadas[0]["tools"][-1]["name"] == "responder"
    assert "cache_control" in falso.llamadas[0]["tools"][-1]


def test_no_confirma_si_la_herramienta_fallo(monkeypatch):
    """Si Claude responde 'listo' en el mismo paso en que algo falló, se le obliga a corregir."""
    falso = ClaudeFalso([
        [tool("t1", "objetivos_agregar", {"seccion": "x", "texto": "y"}), tool("t2", "responder", {"voz": "Listo."})],
        [tool("t3", "responder", {"voz": "No encontré esa sección, señor."})],
    ])

    async def ejecutar_falso(nombre, args):
        return {"error": "No encontré la sección 'x'."}

    monkeypatch.setattr(cerebro, "_claude", falso)
    monkeypatch.setattr(cerebro, "ejecutar", ejecutar_falso)
    r = asyncio.run(cerebro.con_claude("agrega y a x", [], "sistema"))
    assert r["voz"] == "No encontré esa sección, señor."
    resultados = falso.llamadas[1]["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in resultados] == ["t1", "t2"] and all(x["is_error"] for x in resultados)


def test_si_claude_falla_responde_gemini(monkeypatch):
    class Roto:
        messages = None

        def __init__(self):
            self.messages = self

        async def create(self, **_):
            raise RuntimeError("Your credit balance is too low")

    async def gemini_falso(texto, historial, sistema):
        return {"voz": "Respondo yo.", "mostrar": None, "herramientas": [], "cerebro": "gemini"}

    monkeypatch.setattr(cerebro, "_claude", Roto())
    monkeypatch.setattr(cerebro, "con_gemini", gemini_falso)
    r = asyncio.run(cerebro.procesar("hola", []))
    assert r["cerebro"] == "gemini" and "créditos" in r["aviso"]


def test_gemini_con_function_calling(monkeypatch):
    from google.genai import types

    def respuesta(llamadas):
        partes = [types.Part(function_call=types.FunctionCall(id=f"id-{n}", name=n, args=a)) for n, a in llamadas]
        return types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=partes))])

    cola = [respuesta([("calendario_listar", {"desde": "2026-10-30", "hasta": "2026-10-31"})]),
            respuesta([("responder", {"voz": "Mañana tiene un partido."})])]
    vistos = []

    class Modelos:
        async def generate_content(self, model, contents, config):
            vistos.append(list(contents))
            return cola.pop(0)

    falso = NS(aio=NS(models=Modelos()))

    async def ejecutar_falso(nombre, args):
        return {"eventos": [{"nombre": "Partido"}]}

    import app.research as research
    monkeypatch.setattr(research, "_cliente_gemini", falso)
    monkeypatch.setattr(cerebro, "ejecutar", ejecutar_falso)
    r = asyncio.run(cerebro.con_gemini("¿qué tengo mañana?", [{"role": "user", "content": "hola"},
                                                              {"role": "assistant", "content": "Hola"}], "s"))
    assert r["voz"] == "Mañana tiene un partido." and r["herramientas"] == ["calendario_listar"]
    ultima = vistos[1][-1].parts[0].function_response
    assert ultima.name == "calendario_listar" and ultima.id == "id-calendario_listar"


def test_api_pide_clave_y_responde(monkeypatch):
    async def procesar_falso(texto, historial, *_):
        return {"voz": f"Eco: {texto} ({len(historial)})", "mostrar": None, "herramientas": [], "cerebro": "claude"}

    import app.main as main
    monkeypatch.setattr(main, "procesar", procesar_falso)
    with TestClient(app) as cliente:
        assert cliente.post("/api/comando", json={"texto": "hola"}).status_code == 401
        assert cliente.post("/api/comando", json={"texto": "hola"}, headers={"X-Clave": "mal"}).status_code == 401
        r1 = cliente.post("/api/comando", json={"texto": "hola", "sesion": "s1"}, headers={"X-Clave": "secreto"})
        r2 = cliente.post("/api/comando", json={"texto": "otra", "sesion": "s1"}, headers={"X-Clave": "secreto"})
        assert r1.json()["voz"] == "Eco: hola (0)" and r2.json()["voz"] == "Eco: otra (2)"
        assert cliente.get("/api/estado").json() == {"ok": True, "requiere_clave": True}
        assert cliente.get("/api/estado", headers={"X-Clave": "secreto"}).json()["cerebro"] == "claude"
        assert cliente.get("/").status_code == 200


def test_solo_ofrece_herramientas_configuradas(monkeypatch):
    import dataclasses
    from app import tools
    from app.notion import notion

    monkeypatch.setattr(notion, "token", "")
    monkeypatch.setattr(tools, "config", dataclasses.replace(tools.config, tavily_api_key="", gemini_api_key=""))
    nombres = [h["name"] for h in tools.herramientas_claude()]
    assert nombres == ["responder"]

    monkeypatch.setattr(tools, "config", dataclasses.replace(tools.config, gemini_api_key="g"))
    assert [h["name"] for h in tools.herramientas_claude()] == ["investigar", "analizar_archivo", "guiar", "responder"]


def test_error_interno_no_deja_la_pagina_esperando(monkeypatch):
    async def procesar_roto(texto, historial, *_):
        raise ValueError("algo raro")

    import app.main as main
    monkeypatch.setattr(main, "procesar", procesar_roto)
    with TestClient(app) as cliente:
        r = cliente.post("/api/comando", json={"texto": "hola"}, headers={"X-Clave": "secreto"})
    assert r.status_code == 200 and "problema interno" in r.json()["voz"] and "algo raro" in r.json()["aviso"]


def test_gemini_saturado_cambia_de_modelo(monkeypatch):
    import app.research as research

    llamadas = []

    class Modelos:
        async def generate_content(self, model, contents, config):
            llamadas.append(model)
            if model == "gemini-3.8-flash":
                raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return NS(text="hola", candidates=[])

    async def sin_espera(_):
        return None

    monkeypatch.setattr(research, "_cliente_gemini", NS(aio=NS(models=Modelos())))
    monkeypatch.setattr(research.asyncio, "sleep", sin_espera)
    respuesta, modelo = asyncio.run(research.generar_gemini_con_modelo("gemini-3.8-flash", "hola"))
    assert modelo == "gemini-3.6-flash" and respuesta.text == "hola"
    assert llamadas == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.6-flash"]


def test_error_de_datos_no_cambia_de_modelo(monkeypatch):
    import pytest
    import app.research as research

    class Modelos:
        async def generate_content(self, model, contents, config):
            raise RuntimeError("400 INVALID_ARGUMENT: bad schema")

    monkeypatch.setattr(research, "_cliente_gemini", NS(aio=NS(models=Modelos())))
    with pytest.raises(RuntimeError, match="INVALID_ARGUMENT"):
        asyncio.run(research.generar_gemini_con_modelo("gemini-3.8-flash", "hola"))


def test_api_voz_devuelve_audio_y_respaldo(monkeypatch):
    import app.main as main
    from app import voz

    async def sintetizar_falso(texto, nombre=None):
        return b"RIFF....WAVEfmt " + texto.encode()

    monkeypatch.setattr(voz, "sintetizar", sintetizar_falso)
    with TestClient(app) as cliente:
        sin_clave = cliente.post("/api/voz", json={"texto": "hola"})
        r = cliente.post("/api/voz", json={"texto": "hola", "voz": "Iapetus"}, headers={"X-Clave": "secreto"})
        estado = cliente.get("/api/estado", headers={"X-Clave": "secreto"}).json()
    assert sin_clave.status_code == 401
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content.endswith(b"hola")
    assert estado["voz"] == {"motor": "gemini", "predeterminada": "Charon"}

    async def sintetizar_roto(texto, nombre=None):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(voz, "sintetizar", sintetizar_roto)
    with TestClient(app) as cliente:
        r = cliente.post("/api/voz", json={"texto": "hola"}, headers={"X-Clave": "secreto"})
    assert r.status_code == 503 and "límite de uso" in r.json()["detail"] and "RESOURCE_EXHAUSTED" in r.json()["detail"]


def test_voz_lenta_pasa_al_siguiente_modelo(monkeypatch):
    from app import voz

    usados = []

    async def generar_falso(modelo, texto, nombre, limite):
        usados.append(modelo)
        if modelo == "gemini-3.8-flash-lite-tts":
            await asyncio.sleep(5)  # se "atora"
        return b"RIFF-audio-" + modelo.encode()

    monkeypatch.setattr(voz, "_generar", generar_falso)
    monkeypatch.setattr(voz, "LIMITES_SEGUNDOS", (0.05, 0.05, 0.05))
    voz._cache.clear()
    audio = asyncio.run(voz.sintetizar("Hola"))
    assert usados == ["gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts"]
    assert audio == b"RIFF-audio-gemini-3.8-flash-tts"


def test_voz_todas_lentas_da_error_claro(monkeypatch):
    import pytest
    from app import voz

    async def generar_lento(modelo, texto, nombre, limite):
        await asyncio.sleep(5)

    monkeypatch.setattr(voz, "_generar", generar_lento)
    monkeypatch.setattr(voz, "LIMITES_SEGUNDOS", (0.05, 0.05, 0.05))
    voz._cache.clear()
    with pytest.raises(TimeoutError, match="tardó más de"):
        asyncio.run(voz.sintetizar("Otra frase"))


def test_archivos_de_la_pagina_siempre_se_revalidan():
    with TestClient(app) as cliente:
        for ruta in ("/", "/js/app.js", "/css/styles.css", "/spotify/conectar"):
            r = cliente.get(ruta)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", ruta
        etag = cliente.get("/js/app.js").headers["etag"]
        assert cliente.get("/js/app.js", headers={"If-None-Match": etag}).status_code == 304
