"""Archivos de la conversación: los que adjuntas (PDF, Word, Excel, fotos) y las imágenes que crea ChatGPT.

Viven en la memoria del servidor por unas horas (se borran solos o si el servidor se reinicia), así que
para guardar una imagen usa el botón «Descargar». Cada archivo tiene un id imposible de adivinar.
"""
from __future__ import annotations

import html
import io
import mimetypes
import re
import secrets
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_BYTES_ARCHIVO = 20 * 1024 * 1024   # 20 MB por archivo
MAX_BYTES_TOTAL = 120 * 1024 * 1024    # el plan gratis de Render tiene 512 MB de memoria
EXPIRA_SEGUNDOS = 3 * 60 * 60          # 3 horas
MAX_CARACTERES_TEXTO = 60_000

IMAGENES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif"}
IMAGENES_SEGURAS = {"image/png", "image/jpeg", "image/webp", "image/gif"}  # se pueden ver dentro de la página
TEXTO_PLANO = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".py", ".js", ".css", ".log"}
EXTENSIONES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv", ".md": "text/markdown", ".txt": "text/plain", ".json": "application/json",
    ".heic": "image/heic", ".heif": "image/heif", ".webp": "image/webp",
}


class ArchivoError(Exception):
    pass


@dataclass
class Archivo:
    id: str
    nombre: str
    tipo: str
    datos: bytes
    origen: str = "adjunto"  # "adjunto" | "creado" | "drive"
    creado: float = field(default_factory=time.time)

    @property
    def extension(self) -> str:
        return ("." + self.nombre.rsplit(".", 1)[-1].lower()) if "." in self.nombre else ""

    @property
    def es_imagen(self) -> bool:
        return self.tipo in IMAGENES

    @property
    def es_pdf(self) -> bool:
        return self.tipo == "application/pdf" or self.extension == ".pdf"

    @property
    def url(self) -> str:
        return f"/api/archivo/{self.id}"

    def resumen(self) -> dict:
        return {"archivo_id": self.id, "nombre": self.nombre, "tipo": self.tipo, "kb": len(self.datos) // 1024}


def tipo_de(nombre: str, tipo_declarado: str = "") -> str:
    """Tipo MIME confiable: primero por extensión (el navegador a veces manda 'application/octet-stream')."""
    extension = ("." + nombre.rsplit(".", 1)[-1].lower()) if "." in nombre else ""
    return (EXTENSIONES.get(extension) or mimetypes.guess_type(nombre)[0] or tipo_declarado
            or "application/octet-stream").lower()


def limpiar_nombre(nombre: str) -> str:
    nombre = (nombre or "archivo").replace("\\", "/").split("/")[-1].strip()
    nombre = re.sub(r"[\x00-\x1f\"<>|:*?]", "", nombre)[:120]
    return nombre or "archivo"


class Almacen:
    def __init__(self) -> None:
        self._archivos: "OrderedDict[str, Archivo]" = OrderedDict()

    def _limpiar(self) -> None:
        ahora = time.time()
        for id_ in [i for i, a in self._archivos.items() if ahora - a.creado > EXPIRA_SEGUNDOS]:
            self._archivos.pop(id_, None)
        while self._archivos and sum(len(a.datos) for a in self._archivos.values()) > MAX_BYTES_TOTAL:
            self._archivos.popitem(last=False)

    def guardar(self, nombre: str, datos: bytes, tipo: str = "", origen: str = "adjunto") -> Archivo:
        if not datos:
            raise ArchivoError("El archivo llegó vacío.")
        if len(datos) > MAX_BYTES_ARCHIVO:
            raise ArchivoError(f"El archivo pesa {len(datos) // (1024 * 1024)} MB; el máximo es 20 MB.")
        nombre = limpiar_nombre(nombre)
        archivo = Archivo(id=secrets.token_urlsafe(18), nombre=nombre, tipo=tipo_de(nombre, tipo), datos=datos,
                          origen=origen)
        self._archivos[archivo.id] = archivo
        self._limpiar()
        return archivo

    def obtener(self, archivo_id: str) -> Archivo | None:
        self._limpiar()
        return self._archivos.get(str(archivo_id or "").strip())

    def varios(self, ids: list[str]) -> list[Archivo]:
        encontrados = [self.obtener(i) for i in ids or []]
        return [a for a in encontrados if a]


almacen = Almacen()


# ---------------------------------------------------------------------------
# Texto de documentos de Office (para dárselo a la IA como texto: más barato y confiable)
# ---------------------------------------------------------------------------

def _texto_xml(xml: str, fin_parrafo: str) -> str:
    xml = re.sub(r"<w:tab/>|<a:tab/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>|<a:br[^>]*/>", "\n", xml)
    xml = xml.replace(fin_parrafo, "\n")
    texto = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _docx(datos: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        return _texto_xml(z.read("word/document.xml").decode("utf-8", "replace"), "</w:p>")


def _pptx(datos: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        diapositivas = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                              key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
        partes = [f"--- Diapositiva {i} ---\n" + _texto_xml(z.read(n).decode("utf-8", "replace"), "</a:p>")
                  for i, n in enumerate(diapositivas, 1)]
    return "\n\n".join(partes)


def _xlsx(datos: bytes, max_filas: int = 1500) -> str:
    from openpyxl import load_workbook

    libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    partes = []
    for hoja in libro.worksheets:
        filas = []
        for numero, fila in enumerate(hoja.iter_rows(values_only=True), 1):
            if numero > max_filas:
                filas.append(f"… (hay más filas; solo se leyeron {max_filas})")
                break
            if any(c is not None and str(c).strip() for c in fila):
                filas.append("\t".join("" if c is None else str(c) for c in fila).rstrip())
        partes.append(f"--- Hoja «{hoja.title}» ---\n" + "\n".join(filas))
    libro.close()
    return "\n\n".join(partes)


def extraer_texto(archivo: Archivo) -> str | None:
    """Texto del documento, o None si es PDF/imagen (esos la IA los lee directo) o un formato que no se puede leer."""
    extension = archivo.extension
    try:
        if extension == ".docx":
            texto = _docx(archivo.datos)
        elif extension == ".pptx":
            texto = _pptx(archivo.datos)
        elif extension in (".xlsx", ".xlsm"):
            texto = _xlsx(archivo.datos)
        elif extension in TEXTO_PLANO or archivo.tipo.startswith("text/"):
            texto = archivo.datos.decode("utf-8-sig", "replace")
        else:
            return None
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as error:
        raise ArchivoError(f"No pude abrir «{archivo.nombre}»: parece dañado o no es un {extension}.") from error
    if len(texto) > MAX_CARACTERES_TEXTO:
        texto = texto[:MAX_CARACTERES_TEXTO] + "\n… (documento recortado: es muy largo)"
    return texto


def formato_no_soportado(archivo: Archivo) -> str | None:
    if archivo.extension in (".doc", ".xls", ".ppt"):
        return (f"«{archivo.nombre}» está en un formato antiguo de Office. Guárdalo como "
                f"{archivo.extension}x (Archivo → Guardar como) y vuelve a adjuntarlo.")
    return None
