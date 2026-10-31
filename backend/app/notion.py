"""Conexión con Notion: tu página de Objetivos (encabezados + checkboxes), tu calendario
"Actividades del mes" y páginas en general (leer, buscar, crear).

Usa la API REST de Notion directamente con httpx para no depender de un SDK que cambie de versión.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import config

log = logging.getLogger("jarvis.notion")
API = "https://api.notion.com/v1"
LIMITE_TEXTO = 2000  # Notion acepta hasta 2000 caracteres por fragmento de texto
TIPOS_HEADING = ("heading_1", "heading_2", "heading_3", "heading_4")
CONTENEDORES = ("column_list", "column", "toggle", "synced_block", "callout", "quote")


class NotionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", texto).strip()


def texto_plano(rich_text: list[dict] | None) -> str:
    return "".join(parte.get("plain_text", "") for parte in (rich_text or []))


def _fragmentos(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    return [texto[i:i + limite] for i in range(0, len(texto), limite)] or [""]


def a_rich_text(texto: str) -> list[dict]:
    """Convierte texto con **negritas** y [enlaces](url) al formato rich_text de Notion."""
    resultado: list[dict] = []
    patron = re.compile(r"\*\*(.+?)\*\*|\[([^\]]+)\]\((https?://[^)\s]+)\)")
    posicion = 0

    def agregar(contenido: str, negrita: bool = False, url: str | None = None) -> None:
        for trozo in _fragmentos(contenido):
            if not trozo:
                continue
            item: dict[str, Any] = {"type": "text", "text": {"content": trozo}}
            if url:
                item["text"]["link"] = {"url": url}
            if negrita:
                item["annotations"] = {"bold": True}
            resultado.append(item)

    for coincidencia in patron.finditer(texto):
        agregar(texto[posicion:coincidencia.start()])
        if coincidencia.group(1):
            agregar(coincidencia.group(1), negrita=True)
        else:
            agregar(coincidencia.group(2), url=coincidencia.group(3))
        posicion = coincidencia.end()
    agregar(texto[posicion:])
    return resultado[:100] or [{"type": "text", "text": {"content": ""}}]


def markdown_a_bloques(markdown: str) -> list[dict]:
    """Markdown sencillo → bloques de Notion (títulos, listas, checkboxes, citas, código, párrafos)."""
    bloques: list[dict] = []
    lineas = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lineas):
        linea = lineas[i].rstrip()
        limpia = linea.strip()
        if not limpia:
            i += 1
            continue
        if limpia.startswith("```"):
            codigo: list[str] = []
            i += 1
            while i < len(lineas) and not lineas[i].strip().startswith("```"):
                codigo.append(lineas[i])
                i += 1
            contenido = "\n".join(codigo)
            bloques.append({"type": "code", "code": {
                "rich_text": [{"type": "text", "text": {"content": t}} for t in _fragmentos(contenido)],
                "language": "plain text"}})
            i += 1
            continue
        if limpia in ("---", "***"):
            bloques.append({"type": "divider", "divider": {}})
        elif m := re.match(r"^(#{1,3})\s+(.*)", limpia):
            tipo = f"heading_{len(m.group(1))}"
            bloques.append({"type": tipo, tipo: {"rich_text": a_rich_text(m.group(2))}})
        elif m := re.match(r"^[-*]\s+\[( |x|X)\]\s+(.*)", limpia):
            bloques.append({"type": "to_do", "to_do": {
                "rich_text": a_rich_text(m.group(2)), "checked": m.group(1).lower() == "x"}})
        elif m := re.match(r"^[-*•]\s+(.*)", limpia):
            bloques.append({"type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": a_rich_text(m.group(1))}})
        elif m := re.match(r"^\d+[.)]\s+(.*)", limpia):
            bloques.append({"type": "numbered_list_item",
                            "numbered_list_item": {"rich_text": a_rich_text(m.group(1))}})
        elif limpia.startswith(">"):
            bloques.append({"type": "quote", "quote": {"rich_text": a_rich_text(limpia.lstrip("> "))}})
        else:
            bloques.append({"type": "paragraph", "paragraph": {"rich_text": a_rich_text(limpia)}})
        i += 1
    return bloques


def _id_corto(id_notion: str) -> str:
    return id_notion.replace("-", "")


# ---------------------------------------------------------------------------
# Modelo de la página de Objetivos
# ---------------------------------------------------------------------------

@dataclass
class Tarea:
    id: str
    texto: str
    hecho: bool
    nivel: int


@dataclass
class Seccion:
    id: str
    titulo: str
    contenedor_id: str          # bloque donde viven las tareas de esta sección
    ancla_id: str               # después de este bloque se insertan tareas nuevas
    es_toggle: bool
    tareas: list[Tarea] = field(default_factory=list)


@dataclass
class Nodo:
    bloque: dict
    hijos: list["Nodo"] = field(default_factory=list)

    @property
    def tipo(self) -> str:
        return self.bloque.get("type", "")

    @property
    def id(self) -> str:
        return self.bloque.get("id", "")

    @property
    def texto(self) -> str:
        datos = self.bloque.get(self.tipo, {}) or {}
        return texto_plano(datos.get("rich_text"))


def construir_secciones(raiz_id: str, nodos: list[Nodo]) -> list[Seccion]:
    """Recorre el árbol en orden y agrupa los checkboxes bajo el encabezado que les toca.

    - Encabezado normal: todo lo que le sigue (en el mismo contenedor) le pertenece.
    - Encabezado desplegable (toggle): solo lo que está dentro le pertenece.
    """
    secciones: list[Seccion] = []
    general = Seccion(id="general", titulo="Sin sección", contenedor_id=raiz_id,
                      ancla_id="", es_toggle=False)

    def sin_tareas_propias(seccion: Seccion) -> bool:
        return not seccion.ancla_id or _id_corto(seccion.ancla_id) == seccion.id

    def recorrer(lista: list[Nodo], contenedor_id: str, actual: Seccion, nivel: int) -> None:
        for nodo in lista:
            if nodo.tipo in TIPOS_HEADING:
                es_toggle = bool(nodo.bloque.get(nodo.tipo, {}).get("is_toggleable"))
                titulo = nodo.texto.strip() or "(sin título)"
                if es_toggle:
                    seccion = Seccion(id=_id_corto(nodo.id), titulo=titulo, contenedor_id=nodo.id,
                                      ancla_id="", es_toggle=True)
                    secciones.append(seccion)
                    recorrer(nodo.hijos, nodo.id, seccion, 0)
                else:
                    seccion = Seccion(id=_id_corto(nodo.id), titulo=titulo, contenedor_id=contenedor_id,
                                      ancla_id=nodo.id, es_toggle=False)
                    secciones.append(seccion)
                    actual = seccion
                continue

            if nodo.tipo == "to_do":
                datos = nodo.bloque.get("to_do", {})
                actual.tareas.append(Tarea(id=_id_corto(nodo.id), texto=nodo.texto.strip(),
                                           hecho=bool(datos.get("checked")), nivel=nivel))
                # Solo las tareas que viven directamente en el contenedor de la sección
                # sirven como punto de inserción (las subtareas no).
                if contenedor_id == actual.contenedor_id:
                    actual.ancla_id = nodo.id
                if nodo.hijos:
                    recorrer(nodo.hijos, nodo.id, actual, nivel + 1)
                continue

            if nodo.tipo in ("unsupported", "button"):
                # Los botones de Notion: las tareas nuevas van debajo de ellos.
                if contenedor_id == actual.contenedor_id and sin_tareas_propias(actual):
                    actual.ancla_id = nodo.id
                continue

            if nodo.hijos:
                es_columna = nodo.tipo in ("column_list", "column")
                recorrer(nodo.hijos, nodo.id, actual, 0 if es_columna else nivel)

    recorrer(nodos, raiz_id, general, 0)
    if general.tareas:
        secciones.insert(0, general)
    return secciones


def puntuar_seccion(consulta: str, titulo: str) -> float:
    c, t = normalizar(consulta), normalizar(titulo)
    if not c:
        return 0.0
    if c == t:
        return 1.0
    sinonimos = {"hoy": "dia", "diario": "dia", "diarias": "dia", "semanal": "semana",
                 "semanales": "semana", "mensual": "mes", "urgente": "urgencia"}
    tokens_c = {sinonimos.get(p, p) for p in c.split() if len(p) > 2 or p in ("dia", "mes")}
    tokens_t = set(t.split())
    if not tokens_c:
        return 0.0
    base = len(tokens_c & tokens_t) / len(tokens_c)
    bonus = 0.2 if c in t else 0.0
    # Preferimos títulos cortos ante empates (más específicos).
    return base + bonus - len(tokens_t) * 0.001


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class Notion:
    def __init__(self, token: str | None = None, transporte: httpx.AsyncBaseTransport | None = None):
        self.token = token if token is not None else config.notion_token
        self.version = config.notion_version
        self._transporte = transporte
        self._cliente: httpx.AsyncClient | None = None
        self._semaforo = asyncio.Semaphore(3)
        self._cache_objetivos: tuple[float, list[Seccion]] | None = None
        self._calendario: dict[str, Any] | None = None

    @property
    def configurado(self) -> bool:
        return bool(self.token)

    def _http(self) -> httpx.AsyncClient:
        if self._cliente is None:
            self._cliente = httpx.AsyncClient(
                base_url=API, timeout=20.0, transport=self._transporte,
                headers={"Authorization": f"Bearer {self.token}", "Notion-Version": self.version,
                         "Content-Type": "application/json"})
        return self._cliente

    async def _pedir(self, metodo: str, ruta: str, **kwargs: Any) -> dict:
        if not self.configurado:
            raise NotionError("Falta NOTION_TOKEN: conecta tu integración de Notion.")
        for intento in range(4):
            async with self._semaforo:
                respuesta = await self._http().request(metodo, ruta, **kwargs)
            if respuesta.status_code in (429, 502, 503, 529) and intento < 3:
                espera = float(respuesta.headers.get("Retry-After", 1 + intento))
                await asyncio.sleep(min(espera, 5))
                continue
            if respuesta.status_code >= 400:
                try:
                    mensaje = respuesta.json().get("message", respuesta.text)
                except ValueError:
                    mensaje = respuesta.text
                if respuesta.status_code == 404:
                    mensaje += " (¿compartiste esa página con tu integración en Notion → Conexiones?)"
                raise NotionError(f"Notion {respuesta.status_code}: {mensaje}")
            return respuesta.json()
        raise NotionError("Notion está limitando las peticiones; intenta en unos segundos.")

    # ---- Bloques -----------------------------------------------------------

    async def hijos(self, bloque_id: str) -> list[dict]:
        resultados: list[dict] = []
        cursor = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            datos = await self._pedir("GET", f"/blocks/{bloque_id}/children", params=params)
            resultados.extend(datos.get("results", []))
            if not datos.get("has_more"):
                return resultados
            cursor = datos.get("next_cursor")

    async def arbol(self, bloque_id: str, profundidad: int = 4, todo: bool = False) -> list[Nodo]:
        """Descarga los bloques y baja a sus hijos en paralelo (respetando el límite de Notion)."""
        bloques = await self.hijos(bloque_id)
        nodos = [Nodo(b) for b in bloques]
        if profundidad <= 0:
            return nodos

        def debe_bajar(b: dict) -> bool:
            if not b.get("has_children") or b.get("type") in ("child_page", "child_database"):
                return False
            if todo:
                return True
            tipo = b.get("type", "")
            return tipo in CONTENEDORES or tipo == "to_do" or (
                tipo in TIPOS_HEADING and b.get(tipo, {}).get("is_toggleable"))

        pendientes = [n for n in nodos if debe_bajar(n.bloque)]
        hijos = await asyncio.gather(*(self.arbol(n.id, profundidad - 1, todo) for n in pendientes))
        for nodo, sub in zip(pendientes, hijos):
            nodo.hijos = sub
        return nodos

    async def agregar_bloques(self, padre_id: str, bloques: list[dict],
                              despues_de: str | None = None) -> tuple[list[dict], bool]:
        """Agrega bloques; devuelve (bloques creados, si quedaron en la posición pedida)."""
        creados: list[dict] = []
        en_posicion = True
        for inicio in range(0, len(bloques), 100):
            cuerpo: dict[str, Any] = {"children": bloques[inicio:inicio + 100]}
            if despues_de:
                if self.version >= "2026-03-11":
                    cuerpo["position"] = {"type": "after_block", "after_block": {"id": despues_de}}
                else:
                    cuerpo["after"] = despues_de
            try:
                datos = await self._pedir("PATCH", f"/blocks/{padre_id}/children", json=cuerpo)
            except NotionError as error:
                if not despues_de:
                    raise
                log.warning("Notion no aceptó la posición (%s). Pruebo con la API anterior.", error)
                datos = await self._agregar_con_api_anterior(padre_id, cuerpo, despues_de)
                if datos is None:
                    # Último recurso: al final del contenedor, avisando que no quedó en su lugar.
                    log.warning("Tampoco funcionó: lo agrego al final del contenedor %s", padre_id)
                    cuerpo.pop("position", None)
                    cuerpo.pop("after", None)
                    datos = await self._pedir("PATCH", f"/blocks/{padre_id}/children", json=cuerpo)
                    en_posicion = False
            nuevos = datos.get("results", [])
            creados.extend(nuevos)
            if despues_de and nuevos:
                despues_de = nuevos[-1]["id"]
        return creados, en_posicion

    async def _agregar_con_api_anterior(self, padre_id: str, cuerpo: dict, despues_de: str) -> dict | None:
        """La versión 2025-09-03 de la API usa "after" en lugar de "position"."""
        anterior = {k: v for k, v in cuerpo.items() if k != "position"}
        anterior["after"] = despues_de
        try:
            return await self._pedir("PATCH", f"/blocks/{padre_id}/children", json=anterior,
                                     headers={"Notion-Version": "2025-09-03"})
        except NotionError as error:
            log.warning("La API anterior tampoco aceptó la posición: %s", error)
            return None

    # ---- Objetivos (encabezados + checkboxes) -----------------------------

    async def secciones_objetivos(self, forzar: bool = False) -> list[Seccion]:
        if not config.notion_objetivos_id:
            raise NotionError("Falta NOTION_OBJETIVOS_PAGE_ID en la configuración.")
        if not forzar and self._cache_objetivos and time.monotonic() - self._cache_objetivos[0] < 45:
            return self._cache_objetivos[1]
        nodos = await self.arbol(config.notion_objetivos_id, profundidad=4)
        secciones = construir_secciones(config.notion_objetivos_id, nodos)
        self._cache_objetivos = (time.monotonic(), secciones)
        return secciones

    def titulos_en_cache(self) -> list[str]:
        if not self._cache_objetivos:
            return []
        return [s.titulo for s in self._cache_objetivos[1]]

    def tipos_evento_en_cache(self) -> list[str]:
        return list(self._calendario["opciones"]) if self._calendario else []

    async def precalentar(self) -> None:
        """Lee secciones y esquema del calendario por adelantado (las órdenes salen más rápido)."""
        if config.notion_objetivos_id:
            await self.secciones_objetivos()
        if config.notion_calendario_db_id or config.notion_calendario_ds_id:
            await self._info_calendario()

    def _elegir_seccion(self, secciones: list[Seccion], consulta: str) -> Seccion:
        consulta_id = _id_corto(consulta)
        for s in secciones:
            if s.id == consulta_id:
                return s
        ordenadas = sorted(secciones, key=lambda s: puntuar_seccion(consulta, s.titulo), reverse=True)
        if not ordenadas or puntuar_seccion(consulta, ordenadas[0].titulo) < 0.5:
            nombres = "; ".join(s.titulo for s in secciones)
            raise NotionError(f"No encontré la sección '{consulta}'. Secciones disponibles: {nombres}")
        return ordenadas[0]

    async def listar_objetivos(self, seccion: str | None = None, incluir_hechas: bool = False) -> dict:
        secciones = await self.secciones_objetivos()
        if seccion:
            secciones = [self._elegir_seccion(secciones, seccion)]
        salida = []
        for s in secciones:
            tareas = [t for t in s.tareas if incluir_hechas or not t.hecho]
            salida.append({
                "seccion_id": s.id, "seccion": s.titulo,
                "tareas": [{"id": t.id, "texto": t.texto[:300], "hecho": t.hecho, "subtarea": t.nivel > 0}
                           for t in tareas],
            })
        return {"secciones": salida}

    async def agregar_tarea(self, seccion: str, texto: str) -> dict:
        secciones = await self.secciones_objetivos(forzar=True)
        destino = self._elegir_seccion(secciones, seccion)
        bloque = {"type": "to_do", "to_do": {"rich_text": a_rich_text(texto), "checked": False}}
        creados, en_posicion = await self.agregar_bloques(
            destino.contenedor_id, [bloque], despues_de=destino.ancla_id or None)
        self._cache_objetivos = None
        anterior = next((t.texto for t in destino.tareas if t.id == _id_corto(destino.ancla_id)), None)
        resultado = {"ok": True, "seccion": destino.titulo.strip(),
                     "tarea_id": _id_corto(creados[0]["id"]) if creados else None,
                     "ubicacion": (f"debajo de «{anterior[:60]}»" if anterior else "al inicio de la sección")
                     if en_posicion else "al final del bloque que contiene la sección"}
        if not en_posicion:
            resultado["aviso"] = ("Notion no dejó colocarla justo en la sección; quedó al final. "
                                  "Díselo al usuario en una frase.")
        log.info("Tarea agregada en '%s' (%s)", resultado["seccion"], resultado["ubicacion"])
        return resultado

    async def marcar_tarea(self, tarea_id: str, hecho: bool = True) -> dict:
        datos = await self._pedir("PATCH", f"/blocks/{_id_corto(tarea_id)}", json={"to_do": {"checked": hecho}})
        self._cache_objetivos = None
        return {"ok": True, "texto": texto_plano(datos.get("to_do", {}).get("rich_text")), "hecho": hecho}

    async def editar_tarea(self, tarea_id: str, texto: str) -> dict:
        await self._pedir("PATCH", f"/blocks/{_id_corto(tarea_id)}",
                          json={"to_do": {"rich_text": a_rich_text(texto)}})
        self._cache_objetivos = None
        return {"ok": True, "texto": texto}

    # ---- Calendario (Actividades del mes) ---------------------------------

    async def _info_calendario(self) -> dict[str, Any]:
        if self._calendario:
            return self._calendario
        ds_id = config.notion_calendario_ds_id
        if not ds_id:
            if not config.notion_calendario_db_id:
                raise NotionError("Falta NOTION_CALENDARIO_DATABASE_ID en la configuración.")
            base = await self._pedir("GET", f"/databases/{config.notion_calendario_db_id}")
            fuentes = base.get("data_sources") or []
            if not fuentes:
                raise NotionError("La base de datos del calendario no tiene fuentes de datos.")
            ds_id = fuentes[0]["id"]
        esquema = await self._pedir("GET", f"/data_sources/{ds_id}")
        propiedades = esquema.get("properties", {})

        def buscar(tipo: str) -> str | None:
            return next((nombre for nombre, p in propiedades.items() if p.get("type") == tipo), None)

        select = buscar("select")
        self._calendario = {
            "ds_id": ds_id,
            "titulo": buscar("title") or "Name",
            "fecha": buscar("date") or "Fecha",
            "tipo": select,
            "texto": buscar("rich_text"),
            "opciones": [o["name"] for o in propiedades.get(select, {}).get("select", {}).get("options", [])]
            if select else [],
        }
        return self._calendario

    def _evento(self, pagina: dict, info: dict[str, Any]) -> dict:
        props = pagina.get("properties", {})
        fecha = (props.get(info["fecha"], {}) or {}).get("date") or {}
        tipo = ((props.get(info["tipo"], {}) or {}).get("select") or {}) if info["tipo"] else {}
        notas = texto_plano((props.get(info["texto"], {}) or {}).get("rich_text")) if info["texto"] else ""
        return {
            "id": _id_corto(pagina["id"]),
            "nombre": texto_plano(props.get(info["titulo"], {}).get("title")),
            "inicio": fecha.get("start"), "fin": fecha.get("end"),
            "tipo": tipo.get("name"), "notas": notas[:300], "url": pagina.get("url"),
        }

    async def listar_eventos(self, desde: str, hasta: str) -> dict:
        info = await self._info_calendario()
        cuerpo = {
            "filter": {"and": [
                {"property": info["fecha"], "date": {"on_or_after": desde}},
                {"property": info["fecha"], "date": {"on_or_before": hasta}},
            ]},
            "sorts": [{"property": info["fecha"], "direction": "ascending"}],
            "page_size": 100,
        }
        datos = await self._pedir("POST", f"/data_sources/{info['ds_id']}/query", json=cuerpo)
        return {"eventos": [self._evento(p, info) for p in datos.get("results", [])],
                "tipos_disponibles": info["opciones"]}

    def _propiedades_evento(self, info: dict[str, Any], nombre: str | None, inicio: str | None,
                            fin: str | None, tipo: str | None, notas: str | None) -> dict:
        props: dict[str, Any] = {}
        if nombre:
            props[info["titulo"]] = {"title": a_rich_text(nombre)}
        if inicio:
            fecha: dict[str, Any] = {"start": inicio}
            if fin:
                fecha["end"] = fin
            if "T" in inicio and not re.search(r"(Z|[+-]\d{2}:\d{2})$", inicio):
                fecha["time_zone"] = config.zona_horaria
            props[info["fecha"]] = {"date": fecha}
        if tipo and info["tipo"]:
            props[info["tipo"]] = {"select": {"name": tipo}}
        if notas is not None and info["texto"]:
            props[info["texto"]] = {"rich_text": a_rich_text(notas)}
        return props

    async def crear_evento(self, nombre: str, inicio: str, fin: str | None = None,
                           tipo: str | None = None, notas: str | None = None) -> dict:
        info = await self._info_calendario()
        cuerpo = {"parent": {"type": "data_source_id", "data_source_id": info["ds_id"]},
                  "properties": self._propiedades_evento(info, nombre, inicio, fin, tipo, notas)}
        pagina = await self._pedir("POST", "/pages", json=cuerpo)
        return {"ok": True, "evento": self._evento(pagina, info)}

    async def editar_evento(self, evento_id: str, nombre: str | None = None, inicio: str | None = None,
                            fin: str | None = None, tipo: str | None = None, notas: str | None = None) -> dict:
        info = await self._info_calendario()
        props = self._propiedades_evento(info, nombre, inicio, fin, tipo, notas)
        if not props:
            raise NotionError("No indicaste qué cambiar del evento.")
        pagina = await self._pedir("PATCH", f"/pages/{_id_corto(evento_id)}", json={"properties": props})
        return {"ok": True, "evento": self._evento(pagina, info)}

    # ---- Páginas -----------------------------------------------------------

    async def buscar(self, texto: str) -> dict:
        datos = await self._pedir("POST", "/search", json={"query": texto, "page_size": 8})
        salida = []
        for r in datos.get("results", []):
            if r.get("object") == "page":
                titulo = next((texto_plano(p.get("title")) for p in r.get("properties", {}).values()
                               if p.get("type") == "title"), "")
                salida.append({"id": _id_corto(r["id"]), "titulo": titulo, "tipo": "pagina", "url": r.get("url")})
            else:
                salida.append({"id": _id_corto(r["id"]), "titulo": texto_plano(r.get("title")),
                               "tipo": "base de datos", "url": r.get("url")})
        return {"resultados": salida}

    async def leer_pagina(self, pagina_id: str, max_caracteres: int = 12000) -> dict:
        pagina_id = _id_corto(pagina_id)
        pagina = await self._pedir("GET", f"/pages/{pagina_id}")
        titulo = next((texto_plano(p.get("title")) for p in pagina.get("properties", {}).values()
                       if p.get("type") == "title"), "")
        nodos = await self.arbol(pagina_id, profundidad=3, todo=True)
        lineas: list[str] = []

        def escribir(lista: list[Nodo], sangria: int) -> None:
            for n in lista:
                prefijo = "  " * sangria
                t = n.texto
                if n.tipo.startswith("heading_"):
                    lineas.append(f"{'#' * min(int(n.tipo[-1]), 3)} {t}")
                elif n.tipo == "to_do":
                    marca = "x" if n.bloque.get("to_do", {}).get("checked") else " "
                    lineas.append(f"{prefijo}- [{marca}] {t}")
                elif n.tipo in ("bulleted_list_item", "numbered_list_item", "toggle"):
                    lineas.append(f"{prefijo}- {t}")
                elif n.tipo == "child_page":
                    lineas.append(f"{prefijo}[Subpágina] {n.bloque.get('child_page', {}).get('title', '')}")
                elif n.tipo == "child_database":
                    lineas.append(f"{prefijo}[Base de datos] {n.bloque.get('child_database', {}).get('title', '')}")
                elif t:
                    lineas.append(f"{prefijo}{t}")
                escribir(n.hijos, sangria + 1)

        escribir(nodos, 0)
        contenido = "\n".join(lineas)
        recortado = len(contenido) > max_caracteres
        return {"titulo": titulo, "url": pagina.get("url"), "contenido": contenido[:max_caracteres],
                "recortado": recortado}

    async def crear_pagina(self, titulo: str, contenido_markdown: str, padre_id: str | None = None) -> dict:
        padre = _id_corto(padre_id) if padre_id else config.notion_notas_padre_id
        if not padre:
            raise NotionError("Falta NOTION_NOTAS_PADRE_ID: dime en qué página crear las notas nuevas.")
        bloques = markdown_a_bloques(contenido_markdown)
        cuerpo = {"parent": {"page_id": padre},
                  "properties": {"title": {"title": a_rich_text(titulo)}},
                  "children": bloques[:100]}
        pagina = await self._pedir("POST", "/pages", json=cuerpo)
        if len(bloques) > 100:
            await self.agregar_bloques(pagina["id"], bloques[100:])
        return {"ok": True, "id": _id_corto(pagina["id"]), "titulo": titulo, "url": pagina.get("url")}

    async def agregar_a_pagina(self, pagina_id: str, contenido_markdown: str) -> dict:
        bloques = markdown_a_bloques(contenido_markdown)
        await self.agregar_bloques(_id_corto(pagina_id), bloques)  # al final de la página
        if _id_corto(pagina_id) == config.notion_objetivos_id:
            self._cache_objetivos = None
        return {"ok": True, "bloques_agregados": len(bloques)}

    async def cerrar(self) -> None:
        if self._cliente:
            await self._cliente.aclose()


notion = Notion()
