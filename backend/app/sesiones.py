"""Memoria corta de la conversación (para que entienda "márcala como hecha" o "¿y la segunda?").
Vive en memoria del servidor: se borra tras 30 minutos sin hablar o si el servidor se reinicia."""
import time
from collections import OrderedDict

MAX_TURNOS = 8
EXPIRA_SEGUNDOS = 30 * 60
MAX_SESIONES = 50

_sesiones: "OrderedDict[str, tuple[float, list[dict]]]" = OrderedDict()


def historial(sesion_id: str) -> list[dict]:
    entrada = _sesiones.get(sesion_id)
    if not entrada or time.time() - entrada[0] > EXPIRA_SEGUNDOS:
        _sesiones.pop(sesion_id, None)
        return []
    return list(entrada[1])


def guardar_turno(sesion_id: str, usuario: str, asistente: str) -> None:
    mensajes = historial(sesion_id)
    mensajes += [{"role": "user", "content": usuario}, {"role": "assistant", "content": asistente}]
    _sesiones[sesion_id] = (time.time(), mensajes[-MAX_TURNOS * 2:])
    _sesiones.move_to_end(sesion_id)
    while len(_sesiones) > MAX_SESIONES:
        _sesiones.popitem(last=False)


def olvidar(sesion_id: str) -> None:
    _sesiones.pop(sesion_id, None)
    _archivos.pop(sesion_id, None)


# Archivos adjuntos en la conversación (para "¿y qué dice la página 3?" después de mandar un PDF).
MAX_ARCHIVOS = 8
_archivos: dict[str, tuple[float, list[dict]]] = {}


def archivos(sesion_id: str) -> list[dict]:
    entrada = _archivos.get(sesion_id)
    if not entrada or time.time() - entrada[0] > EXPIRA_SEGUNDOS:
        _archivos.pop(sesion_id, None)
        return []
    return list(entrada[1])


def agregar_archivos(sesion_id: str, nuevos: list[dict]) -> None:
    actuales = [a for a in archivos(sesion_id) if a["archivo_id"] not in {n["archivo_id"] for n in nuevos}]
    _archivos[sesion_id] = (time.time(), (actuales + nuevos)[-MAX_ARCHIVOS:])
    while len(_archivos) > MAX_SESIONES:
        _archivos.pop(next(iter(_archivos)))


def tocar_archivos(sesion_id: str) -> None:
    """Mantiene vivos los archivos mientras sigas hablando."""
    entrada = _archivos.get(sesion_id)
    if entrada:
        _archivos[sesion_id] = (time.time(), entrada[1])
