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
