"""Google (Gmail, Google Calendar y Drive). Lo maneja Gemini: el director le pasa la petición y Gemini
busca, lee y resume (así los correos largos no gastan los créditos de Claude).

Conexión (una sola vez, igual que Spotify): tocas «Conectar Google», das permiso y JARVIS te muestra un código
para guardarlo como GOOGLE_REFRESH_TOKEN. Permisos que pide:
- Gmail: leer correos y crear borradores (JARVIS nunca envía correos por su cuenta).
- Calendar: ver y crear eventos.  - Drive: solo leer archivos.
"""
from __future__ import annotations

import asyncio
import base64
import html
import logging
import re
import secrets
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from .config import config

log = logging.getLogger("jarvis.google")

ALCANCES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
)
AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary"
DRIVE = "https://www.googleapis.com/drive/v3"
CONECTAR = {"url": "/google/conectar", "texto": "Conectar Google", "tipo": "conectar"}
NOMBRES_API = {"gmail": "Gmail API", "calendar": "Google Calendar API", "drive": "Google Drive API"}


class GoogleError(Exception):
    def __init__(self, mensaje: str, abrir: dict | None = None):
        super().__init__(mensaje)
        self.abrir = abrir


class Google:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._refresh = config.google_refresh_token
        self._acceso = ""
        self._vence = 0.0
        self._estados: dict[str, tuple[float, str]] = {}

    @property
    def configurado(self) -> bool:
        return bool(config.google_client_id and config.google_client_secret)

    @property
    def conectado(self) -> bool:
        return self.configurado and bool(self._refresh)

    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=25.0)
        return self._http

    async def cerrar(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ----- Conexión -----

    def crear_enlace(self, regreso: str) -> str:
        if not self.configurado:
            raise GoogleError("Faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en el servidor (ver README, sección Google).")
        ahora = time.time()
        self._estados = {k: v for k, v in self._estados.items() if ahora - v[0] < 600}
        estado = secrets.token_urlsafe(16)
        self._estados[estado] = (ahora, regreso)
        return AUTORIZAR + "?" + urlencode({
            "client_id": config.google_client_id, "redirect_uri": regreso, "response_type": "code",
            "scope": " ".join(ALCANCES), "access_type": "offline", "prompt": "consent",
            "include_granted_scopes": "true", "state": estado})

    async def completar_conexion(self, codigo: str, estado: str) -> str:
        guardado = self._estados.pop(estado, None)
        if not guardado or time.time() - guardado[0] > 600:
            raise GoogleError("El enlace de conexión expiró. Vuelve a tocar «Conectar Google».")
        r = await self.http().post(TOKEN, data={
            "grant_type": "authorization_code", "code": codigo, "redirect_uri": guardado[1],
            "client_id": config.google_client_id, "client_secret": config.google_client_secret})
        datos = r.json() if r.content else {}
        if r.status_code != 200 or not datos.get("refresh_token"):
            raise GoogleError(f"Google no entregó el permiso ({datos.get('error_description') or datos.get('error') or r.status_code}).")
        faltan = [a.rsplit("/", 1)[-1] for a in ALCANCES if a not in (datos.get("scope") or "")]
        if faltan:
            log.warning("Google: no se otorgaron los permisos %s", faltan)
        self._refresh = datos["refresh_token"]
        self._acceso, self._vence = datos.get("access_token", ""), time.time() + int(datos.get("expires_in", 3000)) - 60
        return self._refresh

    async def _token(self, forzar: bool = False) -> str:
        if not self.conectado:
            raise GoogleError("Google no está conectado todavía.", CONECTAR)
        if self._acceso and time.time() < self._vence and not forzar:
            return self._acceso
        r = await self.http().post(TOKEN, data={
            "grant_type": "refresh_token", "refresh_token": self._refresh,
            "client_id": config.google_client_id, "client_secret": config.google_client_secret})
        datos = r.json() if r.content else {}
        if r.status_code != 200:
            if datos.get("error") == "invalid_grant":
                raise GoogleError("El permiso de Google expiró o fue retirado. Vuelve a conectar Google "
                                  "(y revisa que la app esté «En producción» en Google Cloud).", CONECTAR)
            raise GoogleError(f"No pude renovar el acceso a Google ({datos.get('error') or r.status_code}).")
        self._acceso, self._vence = datos["access_token"], time.time() + int(datos.get("expires_in", 3000)) - 60
        return self._acceso

    async def _pedir(self, metodo: str, url: str, *, crudo: bool = False, **kwargs: Any) -> Any:
        for intento in range(2):
            token = await self._token(forzar=intento > 0)
            r = await self.http().request(metodo, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
            if r.status_code == 401 and intento == 0:
                continue
            break
        if r.status_code >= 400:
            raise GoogleError(self._explicar(r))
        if crudo:
            return r
        return r.json() if r.content else {}

    @staticmethod
    def _explicar(r: httpx.Response) -> str:
        try:
            error = r.json().get("error") or {}
        except ValueError:
            error = {}
        mensaje = str(error.get("message") if isinstance(error, dict) else error)
        texto = (mensaje + str(error)).lower()
        servicio = next((s for s in NOMBRES_API if s in str(r.url)), "")
        if "has not been used" in texto or "disabled" in texto or "accessnotconfigured" in texto:
            return f"Activa la {NOMBRES_API.get(servicio, 'API')} en Google Cloud (APIs y servicios → Biblioteca)."
        if r.status_code == 403 and ("insufficient" in texto or "scope" in texto):
            return "Falta un permiso de Google: vuelve a conectar Google y marca todas las casillas."
        if r.status_code == 404:
            return "No encontré ese elemento en Google."
        return f"Google respondió {r.status_code}: {mensaje[:160]}"

    # ----- Gmail -----

    async def gmail_buscar(self, consulta: str, cantidad: int = 8) -> dict[str, Any]:
        cantidad = max(1, min(int(cantidad or 8), 15))
        datos = await self._pedir("GET", f"{GMAIL}/messages", params={"q": consulta or "in:inbox", "maxResults": cantidad})
        ids = [m["id"] for m in datos.get("messages") or []]
        metas = await asyncio.gather(*(self._pedir(
            "GET", f"{GMAIL}/messages/{i}",
            params=[("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"),
                    ("metadataHeaders", "Date")]) for i in ids))
        correos = []
        for m in metas:
            cabeceras = {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers") or []}
            correos.append({"id": m["id"], "de": cabeceras.get("from", ""), "asunto": cabeceras.get("subject", ""),
                            "fecha": cabeceras.get("date", ""), "vista_previa": html.unescape(m.get("snippet", "")),
                            "sin_leer": "UNREAD" in (m.get("labelIds") or [])})
        return {"consulta": consulta, "correos": correos, "total": len(correos)}

    async def gmail_leer(self, mensaje_id: str) -> dict[str, Any]:
        m = await self._pedir("GET", f"{GMAIL}/messages/{mensaje_id}", params={"format": "full"})
        carga = m.get("payload") or {}
        cabeceras = {h["name"].lower(): h["value"] for h in carga.get("headers") or []}
        cuerpo = texto_de_correo(carga)
        adjuntos = [p.get("filename") for p in _partes(carga) if p.get("filename")]
        return {"id": mensaje_id, "de": cabeceras.get("from", ""), "para": cabeceras.get("to", ""),
                "asunto": cabeceras.get("subject", ""), "fecha": cabeceras.get("date", ""),
                "cuerpo": cuerpo[:8000] + ("… (recortado)" if len(cuerpo) > 8000 else ""), "adjuntos": adjuntos}

    async def gmail_crear_borrador(self, asunto: str, cuerpo: str, para: str = "") -> dict[str, Any]:
        crudo = mensaje_crudo(para, asunto, cuerpo)
        datos = await self._pedir("POST", f"{GMAIL}/drafts", json={"message": {"raw": crudo}})
        return {"ok": True, "borrador_id": datos.get("id"), "para": para or "(sin destinatario)", "asunto": asunto,
                "nota": "Quedó en Borradores de Gmail; él lo revisa y lo envía. JARVIS nunca envía correos.",
                "_abrir": {"url": "https://mail.google.com/mail/u/0/#drafts", "texto": "Abrir borradores"}}

    # ----- Calendar -----

    async def calendario_listar(self, desde: str, hasta: str) -> dict[str, Any]:
        zona = ZoneInfo(config.zona_horaria)
        inicio = datetime.fromisoformat(desde[:10]).replace(tzinfo=zona)
        fin = datetime.fromisoformat(hasta[:10]).replace(tzinfo=zona) + timedelta(days=1)
        datos = await self._pedir("GET", f"{CALENDAR}/events", params={
            "timeMin": inicio.isoformat(), "timeMax": fin.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": 50, "timeZone": config.zona_horaria})
        eventos = [{"id": e.get("id"), "titulo": e.get("summary", "(sin título)"),
                    "inicio": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
                    "fin": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
                    "lugar": e.get("location", ""), "enlace_reunion": e.get("hangoutLink", "")}
                   for e in datos.get("items") or []]
        return {"desde": desde, "hasta": hasta, "eventos": eventos}

    async def calendario_crear(self, titulo: str, inicio: str, fin: str = "", descripcion: str = "",
                               lugar: str = "") -> dict[str, Any]:
        evento: dict[str, Any] = {"summary": titulo}
        if descripcion:
            evento["description"] = descripcion
        if lugar:
            evento["location"] = lugar
        if len(inicio) <= 10:  # todo el día
            final = fin[:10] if fin else (datetime.fromisoformat(inicio) + timedelta(days=1)).date().isoformat()
            evento["start"], evento["end"] = {"date": inicio}, {"date": final}
        else:
            comienzo = datetime.fromisoformat(inicio)
            final = datetime.fromisoformat(fin) if fin and len(fin) > 10 else comienzo + timedelta(hours=1)
            evento["start"] = {"dateTime": comienzo.isoformat(timespec="minutes"), "timeZone": config.zona_horaria}
            evento["end"] = {"dateTime": final.isoformat(timespec="minutes"), "timeZone": config.zona_horaria}
        datos = await self._pedir("POST", f"{CALENDAR}/events", json=evento)
        return {"ok": True, "id": datos.get("id"), "titulo": titulo, "inicio": inicio, "enlace": datos.get("htmlLink")}

    # ----- Drive -----

    async def drive_buscar(self, texto: str) -> dict[str, Any]:
        seguro = texto.replace("\\", "\\\\").replace("'", "\\'")
        datos = await self._pedir("GET", f"{DRIVE}/files", params={
            "q": f"(name contains '{seguro}' or fullText contains '{seguro}') and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)", "pageSize": 10})
        return {"archivos": [{"id": f["id"], "nombre": f["name"], "tipo": f.get("mimeType", ""),
                              "modificado": f.get("modifiedTime", ""), "enlace": f.get("webViewLink", "")}
                             for f in datos.get("files") or []]}

    async def drive_leer(self, archivo_id: str) -> dict[str, Any]:
        from .archivos import almacen, extraer_texto

        meta = await self._pedir("GET", f"{DRIVE}/files/{archivo_id}",
                                 params={"fields": "id,name,mimeType,size,webViewLink"})
        tipo = meta.get("mimeType", "")
        exportar = {"application/vnd.google-apps.document": "text/plain",
                    "application/vnd.google-apps.spreadsheet": "text/csv",
                    "application/vnd.google-apps.presentation": "text/plain"}
        if tipo in exportar:
            r = await self._pedir("GET", f"{DRIVE}/files/{archivo_id}/export", params={"mimeType": exportar[tipo]},
                                  crudo=True)
            texto = r.text
            return {"nombre": meta["name"], "enlace": meta.get("webViewLink"),
                    "contenido": texto[:20000] + ("… (recortado)" if len(texto) > 20000 else "")}
        if tipo.startswith("application/vnd.google-apps"):
            return {"error": f"«{meta['name']}» es un tipo de archivo de Google que no puedo leer ({tipo})."}
        if int(meta.get("size") or 0) > 20 * 1024 * 1024:
            return {"error": f"«{meta['name']}» pesa más de 20 MB; es demasiado grande para leerlo aquí."}
        r = await self._pedir("GET", f"{DRIVE}/files/{archivo_id}", params={"alt": "media"}, crudo=True)
        archivo = almacen.guardar(meta["name"], r.content, tipo, origen="drive")
        texto = extraer_texto(archivo)
        if texto is not None:
            return {"nombre": archivo.nombre, "enlace": meta.get("webViewLink"), "contenido": texto[:20000]}
        return {"nombre": archivo.nombre, "archivo_id": archivo.id, "enlace": meta.get("webViewLink"),
                "nota": "Es un PDF o imagen: ya lo descargué. Para analizarlo, el director debe usar "
                        "analizar_archivo con este archivo_id."}


def _partes(carga: dict) -> list[dict]:
    partes, pendientes = [], [carga]
    while pendientes:
        parte = pendientes.pop(0)
        partes.append(parte)
        pendientes.extend(parte.get("parts") or [])
    return partes


def _decodificar(datos: str) -> str:
    return base64.urlsafe_b64decode(datos + "=" * (-len(datos) % 4)).decode("utf-8", "replace")


def texto_de_correo(carga: dict) -> str:
    """Prefiere el texto plano del correo; si solo hay HTML, le quita las etiquetas."""
    partes = _partes(carga)
    for tipo in ("text/plain", "text/html"):
        for parte in partes:
            datos = (parte.get("body") or {}).get("data")
            if parte.get("mimeType") == tipo and datos and not parte.get("filename"):
                texto = _decodificar(datos)
                if tipo == "text/html":
                    texto = re.sub(r"(?is)<(script|style).*?</\1>", "", texto)
                    texto = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", texto)
                    texto = html.unescape(re.sub(r"<[^>]+>", "", texto))
                return re.sub(r"\n\s*\n\s*\n+", "\n\n", texto).strip()
    return ""


def mensaje_crudo(para: str, asunto: str, cuerpo: str) -> str:
    mensaje = EmailMessage()
    if para:
        mensaje["To"] = para
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    return base64.urlsafe_b64encode(mensaje.as_bytes()).decode()


google = Google()


# ---------------------------------------------------------------------------
# El experto de Google: Gemini con acceso a Gmail, Calendar y Drive
# ---------------------------------------------------------------------------

_OBJ = {"type": "object"}
HERRAMIENTAS_GOOGLE: list[dict[str, Any]] = [
    {"name": "gmail_buscar", "description": (
        "Busca correos con la sintaxis de Gmail: from:, to:, subject:, is:unread, newer_than:7d, after:2026/11/01, "
        "has:attachment, category:primary, palabras clave. Devuelve remitente, asunto, fecha y vista previa."),
     "parameters": {**_OBJ, "properties": {"consulta": {"type": "string"}, "cantidad": {"type": "integer"}},
                    "required": ["consulta"]}},
    {"name": "gmail_leer", "description": "Lee el contenido completo de un correo (id de gmail_buscar).",
     "parameters": {**_OBJ, "properties": {"mensaje_id": {"type": "string"}}, "required": ["mensaje_id"]}},
    {"name": "google_calendario_listar", "description": "Lista eventos de Google Calendar entre dos fechas AAAA-MM-DD (inclusive).",
     "parameters": {**_OBJ, "properties": {"desde": {"type": "string"}, "hasta": {"type": "string"}},
                    "required": ["desde", "hasta"]}},
    {"name": "google_calendario_crear", "description": (
        "Crea un evento en Google Calendar. inicio/fin: AAAA-MM-DD (todo el día) o AAAA-MM-DDTHH:MM (hora local). "
        "Sin fin dura una hora."),
     "parameters": {**_OBJ, "properties": {"titulo": {"type": "string"}, "inicio": {"type": "string"},
                                           "fin": {"type": "string"}, "descripcion": {"type": "string"},
                                           "lugar": {"type": "string"}}, "required": ["titulo", "inicio"]}},
    {"name": "drive_buscar", "description": "Busca archivos en Google Drive por nombre o contenido.",
     "parameters": {**_OBJ, "properties": {"texto": {"type": "string"}}, "required": ["texto"]}},
    {"name": "drive_leer", "description": (
        "Lee un archivo de Drive (Docs, Sheets, Slides, Word, Excel, texto). Si es PDF o imagen, lo descarga y "
        "devuelve un archivo_id para que el director lo analice."),
     "parameters": {**_OBJ, "properties": {"archivo_id": {"type": "string"}}, "required": ["archivo_id"]}},
]


def _instrucciones() -> str:
    from .prompts import DIAS

    ahora = datetime.now(ZoneInfo(config.zona_horaria))
    return (
        f"Eres el experto en Google (Gmail, Google Calendar, Drive) de JARVIS, el asistente de "
        f"{config.nombre_usuario}. Hoy es {DIAS[ahora.weekday()]} {ahora:%Y-%m-%d %H:%M} ({config.zona_horaria}). El director te pasa "
        "una petición: usa tus herramientas para resolverla y luego contesta en español de México con lo que "
        "encontraste, en markdown sencillo: primero la respuesta directa en 1-2 frases y después el detalle "
        "(remitente, asunto, fecha y lo importante de cada correo; o los eventos con fecha y hora). Para "
        "'¿tengo correos nuevos/importantes?' busca 'is:unread category:primary newer_than:3d'. Lee un correo "
        "completo solo si hace falta para responder. Si una herramienta da error, explícalo tal cual. Si "
        "drive_leer te da un archivo_id, inclúyelo textual en tu respuesta. Nunca inventes correos ni eventos.")


NOMBRES_GOOGLE = {h["name"] for h in HERRAMIENTAS_GOOGLE}


async def ejecutar_directo(nombre: str, args: dict[str, Any]) -> dict[str, Any]:
    """Con EXPERTO_GOOGLE=claude el director usa estas herramientas él mismo (Gemini no ve tus correos)."""
    if not google.conectado:
        return {"error": "Falta conectar tu cuenta de Google.", "_abrir": CONECTAR}
    resultado = await _ejecutar_google(nombre, args)
    if resultado.pop("necesita_conectar", False):
        resultado["_abrir"] = CONECTAR
    return resultado


async def _ejecutar_google(nombre: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if nombre == "gmail_buscar":
            return await google.gmail_buscar(args.get("consulta", ""), args.get("cantidad") or 8)
        if nombre == "gmail_leer":
            return await google.gmail_leer(args["mensaje_id"])
        if nombre == "google_calendario_listar":
            return await google.calendario_listar(args["desde"], args["hasta"])
        if nombre == "google_calendario_crear":
            return await google.calendario_crear(args["titulo"], args["inicio"], args.get("fin") or "",
                                                 args.get("descripcion") or "", args.get("lugar") or "")
        if nombre == "drive_buscar":
            return await google.drive_buscar(args["texto"])
        if nombre == "drive_leer":
            return await google.drive_leer(args["archivo_id"])
        return {"error": f"Herramienta desconocida: {nombre}"}
    except KeyError as faltante:
        return {"error": f"Falta el parámetro {faltante}."}
    except GoogleError as error:
        return {"error": str(error), **({"necesita_conectar": True} if error.abrir else {})}
    except ValueError as error:
        return {"error": f"Dato inválido: {error}"}
    except httpx.HTTPError as error:
        return {"error": f"No pude conectar con Google ({type(error).__name__})."}


async def experto_google(peticion: str, max_pasos: int = 6) -> dict[str, Any]:
    if not google.configurado:
        return {"error": "Google no está configurado: faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET (ver README)."}
    if not google.conectado:
        return {"error": "Falta conectar tu cuenta de Google.", "_abrir": CONECTAR}
    if not config.gemini_api_key:
        return {"error": "Falta GEMINI_API_KEY: Gemini es quien revisa tu cuenta de Google."}
    try:
        await google._token()  # si el permiso expiró, se avisa de inmediato (sin gastar llamadas a Gemini)
    except GoogleError as error:
        return {"error": str(error), **({"_abrir": error.abrir} if error.abrir else {})}
    from google.genai import types

    from .research import generar_gemini_con_modelo

    herramientas = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=h["name"], description=h["description"], parameters_json_schema=h["parameters"])
        for h in HERRAMIENTAS_GOOGLE])]
    ajustes = dict(system_instruction=_instrucciones(), tools=herramientas,
                   automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contenidos = [types.Content(role="user", parts=[types.Part(text=peticion)])]
    modelo, usadas, abrir = config.modelo_gemini_orquestador, [], None
    for _ in range(max_pasos):
        r, modelo = await generar_gemini_con_modelo(modelo, contenidos, **ajustes)
        if not r.candidates or not r.candidates[0].content:
            break
        contenidos.append(r.candidates[0].content)
        llamadas = r.function_calls or []
        if not llamadas:
            texto = (r.text or "").strip() or "No encontré nada."
            return {"respuesta": texto, "herramientas_google": usadas, "_experto": "Gemini",
                    "_mostrar_opcional": {"tipo": "texto", "titulo": "Google", "contenido": texto}}
        resultados = await asyncio.gather(*(_ejecutar_google(c.name, dict(c.args or {})) for c in llamadas))
        usadas += [c.name for c in llamadas]
        if any(res.get("necesita_conectar") for res in resultados):
            abrir = CONECTAR
        contenidos.append(types.Content(role="user", parts=[
            types.Part(function_response=types.FunctionResponse(id=c.id, name=c.name, response=res))
            for c, res in zip(llamadas, resultados)]))
    resultado: dict[str, Any] = {"error": "Gemini no terminó de revisar tu cuenta de Google. Intenta con una petición más concreta.",
                                 "herramientas_google": usadas}
    if abrir:
        resultado["_abrir"] = abrir
    return resultado
