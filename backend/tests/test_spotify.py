import asyncio
import dataclasses
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi.testclient import TestClient

import app.spotify as modulo
from app.spotify import Spotify, SpotifyError, puntuar


class SpotifyFalso:
    """Imita las APIs de cuentas y web de Spotify."""

    def __init__(self, dispositivos=None, playlists=None):
        self.dispositivos = dispositivos if dispositivos is not None else []
        self.playlists = playlists or []
        self.registro = []
        self.volumen = 40

    def __call__(self, request: httpx.Request):
        ruta, metodo = request.url.path, request.method
        cuerpo = request.content.decode() if request.content else ""
        self.registro.append((metodo, ruta, dict(request.url.params), cuerpo, request.headers.get("authorization", "")))
        if request.url.host == "accounts.spotify.com":
            datos = dict(x.split("=", 1) for x in cuerpo.split("&"))
            if datos.get("refresh_token") == "malo":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600,
                                             **({"refresh_token": "nuevo-refresh"} if datos["grant_type"] == "authorization_code" else {})})
        if ruta == "/v1/me/playlists":
            return httpx.Response(200, json={"items": self.playlists, "next": None})
        if ruta == "/v1/search":
            tipo = request.url.params["type"]
            return httpx.Response(200, json={f"{tipo}s": {"items": [
                {"name": "Master of Puppets", "uri": f"spotify:{tipo}:XYZ", "artists": [{"name": "Metallica"}]}]}})
        if ruta == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": self.dispositivos})
        if ruta == "/v1/me/player" and metodo == "GET":
            return httpx.Response(200, json={"device": {"name": "PC", "volume_percent": self.volumen}, "is_playing": True,
                                             "item": {"name": "One", "artists": [{"name": "Metallica"}],
                                                      "album": {"name": "...And Justice for All"}}})
        if ruta.startswith("/v1/me/player"):
            if not self.dispositivos:
                return httpx.Response(404, json={"error": {"status": 404, "message": "Player command failed: No active device found",
                                                           "reason": "NO_ACTIVE_DEVICE"}})
            return httpx.Response(204)
        return httpx.Response(404, json={"error": {"status": 404, "message": "no"}})


PLAYLISTS = [{"name": "Gym rock", "uri": "spotify:playlist:GYM", "owner": {"display_name": "Ricardo"}},
             {"name": "Metallica 🤘", "uri": "spotify:playlist:MET", "owner": {"display_name": "Ricardo"}}]
CEL = {"id": "cel", "name": "iPhone de Ricardo", "type": "Smartphone", "is_active": False, "is_restricted": False}
PC = {"id": "pc", "name": "PC", "type": "Computer", "is_active": False, "is_restricted": False}


@pytest.fixture
def configurar(monkeypatch):
    def hacer(falso, refresh="refresh-ok"):
        monkeypatch.setattr(modulo, "config", dataclasses.replace(
            modulo.config, spotify_client_id="id", spotify_client_secret="secreto", spotify_refresh_token=refresh))
        return Spotify(transporte=httpx.MockTransport(falso))
    return hacer


def test_puntuar_nombres():
    assert puntuar("mi playlist de metallica", "Metallica 🤘") > 1
    assert puntuar("rock del gym", "Gym rock") >= 0.6
    assert puntuar("metallica", "Gym rock") < 0.6


def test_reproduce_tu_playlist_en_el_dispositivo_preferido(configurar):
    falso = SpotifyFalso(dispositivos=[CEL, PC], playlists=PLAYLISTS)
    s = configurar(falso)
    r = asyncio.run(s.reproducir("mi playlist de Metallica", "playlist", aleatorio=True))
    assert r == {"ok": True, "nombre": "Metallica 🤘", "de_tu_biblioteca": True,
                 "reproduciendo_en": "PC", "tipo_de_dispositivo": "Computer"}
    play = next(x for x in falso.registro if x[1] == "/v1/me/player/play")
    assert play[2] == {"device_id": "pc"} and json.loads(play[3]) == {"context_uri": "spotify:playlist:MET"}
    shuffle = next(x for x in falso.registro if x[1] == "/v1/me/player/shuffle")
    assert shuffle[2]["state"] == "true"
    token = next(x for x in falso.registro if x[1] == "/api/token")
    assert token[4].startswith("Basic ") and "grant_type=refresh_token" in token[3]


def test_sin_dispositivo_muestra_boton_y_luego_reproduce(configurar):
    falso = SpotifyFalso(dispositivos=[], playlists=PLAYLISTS)
    s = configurar(falso)
    r = asyncio.run(s.reproducir("metallica"))
    assert r["spotify_cerrado"] and r["_abrir"] == {"url": "https://open.spotify.com/playlist/MET", "texto": "Abrir Spotify",
                                                    "tipo": "spotify", "reintentar": True}
    assert asyncio.run(s.reintentar_pendiente()) == {"ok": False, "motivo": "Spotify aún no aparece como dispositivo"}
    falso.dispositivos = [CEL]  # el usuario abrió Spotify en el celular
    assert asyncio.run(s.reintentar_pendiente()) == {"ok": True, "nombre": "Metallica 🤘", "reproduciendo_en": "iPhone de Ricardo"}
    assert asyncio.run(s.reintentar_pendiente())["motivo"] == "nada pendiente"


def test_busca_en_el_catalogo_y_controla(configurar):
    falso = SpotifyFalso(dispositivos=[{**PC, "is_active": True}], playlists=PLAYLISTS)
    s = configurar(falso)
    r = asyncio.run(s.reproducir("Master of Puppets", "cancion"))
    assert r["nombre"] == "Master of Puppets de Metallica" and r["de_tu_biblioteca"] is False
    play = [x for x in falso.registro if x[1] == "/v1/me/player/play"][-1]
    assert json.loads(play[3]) == {"uris": ["spotify:track:XYZ"]}
    assert asyncio.run(s.controlar("volumen", "+20"))["volumen"] == 60
    assert asyncio.run(s.controlar("volumen", "bajar"))["volumen"] == 25
    assert asyncio.run(s.controlar("pausa")) == {"ok": True, "accion": "pausa"}
    assert asyncio.run(s.estado())["cancion"] == "One"


def test_sin_conectar_o_vencido_pide_conectar(configurar):
    s = configurar(SpotifyFalso(), refresh="")
    with pytest.raises(SpotifyError) as error:
        asyncio.run(s.reproducir("metallica"))
    assert error.value.abrir["tipo"] == "conectar"
    s = configurar(SpotifyFalso(), refresh="malo")
    with pytest.raises(SpotifyError, match="expiró") as error:
        asyncio.run(s.estado())
    assert error.value.abrir["url"] == "/spotify/conectar"


def test_el_boton_llega_a_la_respuesta(monkeypatch):
    from app import cerebro, tools

    class ClaudeFalso:
        def __init__(self):
            self.messages = self
            self.vistos = []
            self.cola = [
                [NS(type="tool_use", id="t1", name="spotify_reproducir", input={"consulta": "metallica"})],
                [NS(type="tool_use", id="t2", name="responder", input={"voz": "Toque el botón para abrir Spotify, señor."})],
            ]

        async def create(self, **kwargs):
            self.vistos.append(list(kwargs["messages"]))
            return NS(content=self.cola.pop(0))

    async def reproducir_falso(consulta, tipo, aleatorio):
        return {"ok": False, "spotify_cerrado": True, "_abrir": {"url": "https://open.spotify.com/playlist/MET",
                                                                 "texto": "Abrir Spotify", "reintentar": True}}

    falso = ClaudeFalso()
    monkeypatch.setattr(cerebro, "_claude", falso)
    monkeypatch.setattr(tools.spotify, "reproducir", reproducir_falso)
    r = asyncio.run(cerebro.con_claude("pon mi playlist de metallica", [], "s"))
    assert r["abrir"]["url"] == "https://open.spotify.com/playlist/MET"
    resultado = falso.vistos[1][-1]["content"][0]["content"]
    assert "_abrir" not in resultado and "boton_en_pantalla" in resultado and "open.spotify.com" not in resultado


def test_conexion_por_la_pagina(configurar, monkeypatch):
    import app.main as main
    falso = SpotifyFalso()
    s = configurar(falso, refresh="")
    monkeypatch.setattr(main, "spotify", s)
    with TestClient(main.app) as cliente:
        assert cliente.post("/api/spotify/enlace").status_code == 401
        r = cliente.post("/api/spotify/enlace", headers={"X-Clave": "secreto", "x-forwarded-proto": "https",
                                                         "host": "jarvis-x.onrender.com"}).json()
        assert r["regreso"] == "https://jarvis-x.onrender.com/spotify/callback"
        estado = r["url"].split("state=")[1].split("&")[0]
        pagina = cliente.get(f"/spotify/callback?code=abc&state={estado}")
        assert pagina.status_code == 200 and "nuevo-refresh" in pagina.text and "SPOTIFY_REFRESH_TOKEN" in pagina.text
        assert "no-store" in pagina.headers["cache-control"]
        repetida = cliente.get(f"/spotify/callback?code=abc&state={estado}")
        assert "expiró" in repetida.text
        local = cliente.post("/api/spotify/enlace", headers={"X-Clave": "secreto", "host": "localhost:8000"}).json()
        assert local["regreso"] == "http://127.0.0.1:8000/spotify/callback"
        assert cliente.get("/spotify/conectar").status_code == 200
    assert s.conectado
