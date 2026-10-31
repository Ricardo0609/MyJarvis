"""Spotify: busca y reproduce tu música, y la controla (pausa, siguiente, volumen...).

Requisitos: Spotify Premium y una app gratuita en https://developer.spotify.com/dashboard.
La cuenta se conecta una sola vez (botón "Conectar Spotify"); el código que entrega Spotify
se guarda como SPOTIFY_REFRESH_TOKEN para no tener que volver a conectar.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import config

log = logging.getLogger("jarvis.spotify")

API = "https://api.spotify.com/v1"
CUENTAS = "https://accounts.spotify.com"
PERMISOS = ("playlist-read-private playlist-read-collaborative user-read-playback-state "
            "user-modify-playback-state user-read-currently-playing")
CONECTAR = {"url": "/spotify/conectar", "texto": "Conectar Spotify", "tipo": "conectar"}
TIPOS = {"playlist": "playlist", "cancion": "track", "artista": "artist", "album": "album"}
PREFERENCIA_DISPOSITIVO = {"Computer": 0, "Smartphone": 1, "Speaker": 2, "TV": 3, "CastAudio": 4}
PALABRAS_VACIAS = {"mi", "mis", "playlist", "playlists", "lista", "de", "del", "la", "el", "los", "las",
                   "musica", "canciones", "pon", "ponme", "reproduce", "la", "que", "se", "llama", "y"}


class SpotifyError(Exception):
    def __init__(self, mensaje: str, abrir: dict | None = None):
        super().__init__(mensaje)
        self.abrir = abrir


class SinDispositivo(SpotifyError):
    pass


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", texto).strip()


def puntuar(consulta: str, nombre: str) -> float:
    """Qué tanto se parece lo que dijiste al nombre de una playlist (0 a 1.15)."""
    c = " ".join(p for p in normalizar(consulta).split() if p not in PALABRAS_VACIAS)
    n = normalizar(nombre)
    if not c or not n:
        return 0.0
    if c == n:
        return 1.15
    tc, tn = set(c.split()), set(n.split())
    cobertura = len(tc & tn) / len(tc)
    contiene = 0.15 if c in n else 0.0
    return max(cobertura * 0.9 + contiene, SequenceMatcher(None, c, n).ratio())


def enlace_web(uri: str) -> str:
    """spotify:playlist:ABC → https://open.spotify.com/playlist/ABC (abre la app en el celular)."""
    partes = uri.split(":")
    return f"https://open.spotify.com/{partes[1]}/{partes[2]}" if len(partes) == 3 else "https://open.spotify.com"


class Spotify:
    def __init__(self, transporte: httpx.AsyncBaseTransport | None = None):
        self._transporte = transporte
        self._http: httpx.AsyncClient | None = None
        self._refresh = config.spotify_refresh_token
        self._token = ""
        self._expira = 0.0
        self._estados: dict[str, tuple[float, str]] = {}
        self._playlists: tuple[float, list[dict]] | None = None
        self.pendiente: dict | None = None

    # ---- Estado ------------------------------------------------------------

    @property
    def configurado(self) -> bool:
        return bool(config.spotify_client_id and config.spotify_client_secret)

    @property
    def conectado(self) -> bool:
        return self.configurado and bool(self._refresh)

    def _cliente(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0, transport=self._transporte)
        return self._http

    def _basic(self) -> str:
        par = f"{config.spotify_client_id}:{config.spotify_client_secret}".encode()
        return "Basic " + base64.b64encode(par).decode()

    # ---- Conexión de la cuenta (una sola vez) -------------------------------

    def crear_enlace(self, redirect_uri: str) -> str:
        if not self.configurado:
            raise SpotifyError("Faltan SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET en la configuración.")
        ahora = time.time()
        self._estados = {k: v for k, v in self._estados.items() if v[0] > ahora}
        estado = secrets.token_urlsafe(24)
        self._estados[estado] = (ahora + 600, redirect_uri)
        return f"{CUENTAS}/authorize?" + urlencode({
            "client_id": config.spotify_client_id, "response_type": "code", "redirect_uri": redirect_uri,
            "scope": PERMISOS, "state": estado, "show_dialog": "true"})

    async def completar_conexion(self, codigo: str, estado: str) -> str:
        """Cambia el código de Spotify por un refresh token. Devuelve el refresh token."""
        guardado = self._estados.pop(estado, None)
        if not guardado or guardado[0] < time.time():
            raise SpotifyError("El enlace de conexión expiró o no es válido. Vuelve a tocar «Conectar Spotify».")
        datos = await self._pedir_token({"grant_type": "authorization_code", "code": codigo,
                                         "redirect_uri": guardado[1]})
        if not datos.get("refresh_token"):
            raise SpotifyError("Spotify no entregó el código de acceso. Intenta conectar de nuevo.")
        self._refresh = datos["refresh_token"]
        self._playlists = None
        log.info("Spotify conectado")
        return self._refresh

    async def _pedir_token(self, formulario: dict) -> dict:
        r = await self._cliente().post(f"{CUENTAS}/api/token", data=formulario,
                                       headers={"Authorization": self._basic()})
        datos = r.json() if r.content else {}
        if r.status_code >= 400:
            motivo = datos.get("error_description") or datos.get("error") or r.text
            if datos.get("error") == "invalid_grant":
                self._refresh = ""
                raise SpotifyError("La conexión con Spotify expiró. Hay que volver a conectarlo.", abrir=CONECTAR)
            if datos.get("error") == "invalid_client":
                raise SpotifyError("SPOTIFY_CLIENT_ID o SPOTIFY_CLIENT_SECRET no son correctos.")
            raise SpotifyError(f"Spotify rechazó el acceso: {motivo}")
        self._token = datos["access_token"]
        self._expira = time.time() + int(datos.get("expires_in", 3600))
        if datos.get("refresh_token") and datos["refresh_token"] != self._refresh and formulario["grant_type"] == "refresh_token":
            log.warning("Spotify entregó un código de acceso nuevo; si tras reiniciar falla, vuelve a conectar Spotify.")
            self._refresh = datos["refresh_token"]
        return datos

    async def _token_vigente(self) -> str:
        if not self.configurado:
            raise SpotifyError("Spotify no está configurado (faltan SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET).")
        if not self._refresh:
            raise SpotifyError("Spotify todavía no está conectado a tu cuenta.", abrir=CONECTAR)
        if not self._token or time.time() > self._expira - 60:
            await self._pedir_token({"grant_type": "refresh_token", "refresh_token": self._refresh})
        return self._token

    # ---- Peticiones a la API -----------------------------------------------

    async def _pedir(self, metodo: str, ruta: str, **kwargs: Any) -> dict | None:
        for intento in range(3):
            token = await self._token_vigente()
            r = await self._cliente().request(metodo, f"{API}{ruta}", headers={"Authorization": f"Bearer {token}"},
                                              **kwargs)
            if r.status_code == 401 and intento == 0:
                self._token = ""  # se renueva y se reintenta
                continue
            if r.status_code == 429 and intento < 2:
                await asyncio.sleep(min(float(r.headers.get("Retry-After", 1)), 3))
                continue
            if r.status_code == 204 or not r.content:
                if r.status_code < 400:
                    return None
            try:
                datos = r.json()
            except ValueError:
                datos = {}
            if r.status_code < 400:
                return datos
            error = datos.get("error") if isinstance(datos.get("error"), dict) else {}
            mensaje, motivo = error.get("message") or r.text[:200], error.get("reason", "")
            if motivo == "NO_ACTIVE_DEVICE" or "no active device" in mensaje.lower():
                raise SinDispositivo("Spotify no está abierto en ningún dispositivo.")
            if motivo == "PREMIUM_REQUIRED":
                raise SpotifyError("Spotify pide una cuenta Premium para controlar la música.")
            if r.status_code == 403 and "registered" in mensaje.lower():
                raise SpotifyError("Tu cuenta no está registrada en la app de Spotify: agrégala en User Management.")
            raise SpotifyError(f"Spotify {r.status_code}: {mensaje}")
        raise SpotifyError("Spotify no respondió; intenta en unos segundos.")

    # ---- Búsqueda ----------------------------------------------------------

    async def mis_playlists(self) -> list[dict]:
        if self._playlists and time.time() - self._playlists[0] < 300:
            return self._playlists[1]
        salida: list[dict] = []
        for offset in range(0, 300, 50):
            datos = await self._pedir("GET", "/me/playlists", params={"limit": 50, "offset": offset}) or {}
            for p in datos.get("items") or []:
                if p and p.get("uri"):
                    salida.append({"nombre": p.get("name", ""), "uri": p["uri"],
                                   "dueno": (p.get("owner") or {}).get("display_name", "")})
            if not datos.get("next"):
                break
        self._playlists = (time.time(), salida)
        return salida

    async def _buscar_catalogo(self, consulta: str, tipo: str) -> dict | None:
        datos = await self._pedir("GET", "/search", params={"q": consulta, "type": TIPOS[tipo], "limit": 5}) or {}
        items = [i for i in (datos.get(f"{TIPOS[tipo]}s") or {}).get("items") or [] if i]
        if not items:
            return None
        item = items[0]
        nombre = item.get("name", "")
        if tipo in ("cancion", "album"):
            artistas = ", ".join(a.get("name", "") for a in item.get("artists") or [])
            nombre = f"{nombre} de {artistas}" if artistas else nombre
        return {"nombre": nombre, "uri": item["uri"]}

    async def _encontrar(self, consulta: str, tipo: str) -> tuple[dict | None, bool]:
        """Devuelve (objetivo, es_de_tu_biblioteca)."""
        if tipo == "playlist":
            propias = await self.mis_playlists()
            if propias:
                mejor = max(propias, key=lambda p: puntuar(consulta, p["nombre"]))
                if puntuar(consulta, mejor["nombre"]) >= 0.6:
                    return mejor, True
        return await self._buscar_catalogo(consulta, tipo), False

    # ---- Reproducción ------------------------------------------------------

    async def _dispositivo(self) -> dict | None:
        datos = await self._pedir("GET", "/me/player/devices") or {}
        dispositivos = [d for d in datos.get("devices") or [] if d.get("id") and not d.get("is_restricted")]
        if not dispositivos:
            return None
        activo = next((d for d in dispositivos if d.get("is_active")), None)
        return activo or sorted(dispositivos, key=lambda d: PREFERENCIA_DISPOSITIVO.get(d.get("type"), 9))[0]

    async def _tocar(self, cuerpo: dict, dispositivo: dict, aleatorio: bool | None) -> None:
        await self._pedir("PUT", "/me/player/play", params={"device_id": dispositivo["id"]}, json=cuerpo)
        if aleatorio is not None:
            try:
                await self._pedir("PUT", "/me/player/shuffle",
                                  params={"state": str(bool(aleatorio)).lower(), "device_id": dispositivo["id"]})
            except SpotifyError as error:
                log.warning("No pude cambiar el modo aleatorio: %s", error)

    async def reproducir(self, consulta: str, tipo: str = "playlist", aleatorio: bool | None = None) -> dict:
        tipo = tipo if tipo in TIPOS else "playlist"
        objetivo, propia = await self._encontrar(consulta, tipo)
        if not objetivo:
            return {"error": f"No encontré «{consulta}» en Spotify."}
        cuerpo = {"uris": [objetivo["uri"]]} if tipo == "cancion" else {"context_uri": objetivo["uri"]}
        base = {"nombre": objetivo["nombre"], "de_tu_biblioteca": propia}
        dispositivo = await self._dispositivo()
        if dispositivo:
            try:
                await self._tocar(cuerpo, dispositivo, aleatorio)
                self.pendiente = None
                return {"ok": True, **base, "reproduciendo_en": dispositivo.get("name"),
                        "tipo_de_dispositivo": dispositivo.get("type")}
            except SinDispositivo:
                pass
        # Spotify no está abierto: se guarda la orden y se muestra el botón para abrirlo.
        self.pendiente = {"cuerpo": cuerpo, "nombre": objetivo["nombre"], "aleatorio": aleatorio,
                          "expira": time.time() + 180}
        return {"ok": False, **base, "spotify_cerrado": True,
                "nota": "Spotify no está abierto en ningún dispositivo. Dile que toque el botón en pantalla "
                        "para abrirlo; empezará a sonar solo.",
                "_abrir": {"url": enlace_web(objetivo["uri"]), "texto": "Abrir Spotify", "tipo": "spotify",
                           "reintentar": True}}

    async def reintentar_pendiente(self) -> dict:
        """Se llama después de abrir Spotify: reproduce lo que se había pedido."""
        if not self.pendiente or self.pendiente["expira"] < time.time():
            self.pendiente = None
            return {"ok": False, "motivo": "nada pendiente"}
        dispositivo = await self._dispositivo()
        if not dispositivo:
            return {"ok": False, "motivo": "Spotify aún no aparece como dispositivo"}
        try:
            await self._tocar(self.pendiente["cuerpo"], dispositivo, self.pendiente.get("aleatorio"))
        except SinDispositivo:
            return {"ok": False, "motivo": "Spotify aún no está listo"}
        nombre = self.pendiente["nombre"]
        self.pendiente = None
        return {"ok": True, "nombre": nombre, "reproduciendo_en": dispositivo.get("name")}

    async def controlar(self, accion: str, valor: str | None = None) -> dict:
        accion = normalizar(accion)
        try:
            if accion in ("pausa", "pausar", "detener"):
                await self._pedir("PUT", "/me/player/pause")
            elif accion in ("reanudar", "continuar", "play"):
                await self._pedir("PUT", "/me/player/play")
            elif accion in ("siguiente", "saltar"):
                await self._pedir("POST", "/me/player/next")
            elif accion == "anterior":
                await self._pedir("POST", "/me/player/previous")
            elif accion == "volumen":
                nivel = await self._calcular_volumen(valor)
                await self._pedir("PUT", "/me/player/volume", params={"volume_percent": nivel})
                return {"ok": True, "accion": "volumen", "volumen": nivel}
            elif accion == "aleatorio":
                activo = normalizar(valor or "si") not in ("no", "false", "apagar", "desactivar")
                await self._pedir("PUT", "/me/player/shuffle", params={"state": str(activo).lower()})
                return {"ok": True, "accion": "aleatorio", "activo": activo}
            elif accion == "repetir":
                modo = {"cancion": "track", "playlist": "context", "album": "context"}.get(normalizar(valor or ""), "off")
                await self._pedir("PUT", "/me/player/repeat", params={"state": modo})
                return {"ok": True, "accion": "repetir", "modo": modo}
            else:
                return {"error": f"No conozco la acción «{accion}»."}
        except SinDispositivo:
            return {"error": "No hay música sonando en ningún dispositivo ahora mismo."}
        return {"ok": True, "accion": accion}

    async def _calcular_volumen(self, valor: str | None) -> int:
        """Acepta "70" (absoluto), "+10"/"-10" o "subir"/"bajar" (relativo, 15 por defecto)."""
        crudo = str(valor or "").strip()
        texto = normalizar(crudo)
        numero = re.search(r"\d+", texto)
        bajar = crudo.startswith("-") or texto.startswith(("baj", "menos"))
        subir = crudo.startswith("+") or texto.startswith(("sub", "mas"))
        if bajar or subir:
            actual = await self._pedir("GET", "/me/player") or {}
            volumen = (actual.get("device") or {}).get("volume_percent", 50)
            paso = int(numero.group()) if numero else 15
            return max(0, min(100, volumen - paso if bajar else volumen + paso))
        return max(0, min(100, int(numero.group()) if numero else 50))

    async def estado(self) -> dict:
        datos = await self._pedir("GET", "/me/player")
        if not datos or not datos.get("item"):
            return {"sonando": False}
        item = datos["item"]
        artistas = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        return {"sonando": bool(datos.get("is_playing")), "cancion": item.get("name"), "artista": artistas,
                "album": (item.get("album") or {}).get("name"),
                "dispositivo": (datos.get("device") or {}).get("name"),
                "volumen": (datos.get("device") or {}).get("volume_percent"),
                "aleatorio": datos.get("shuffle_state")}

    async def cerrar(self) -> None:
        if self._http:
            await self._http.aclose()


spotify = Spotify()
