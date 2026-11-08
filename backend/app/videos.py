"""Búsqueda de videos de YouTube: devuelve los enlaces con miniatura, canal y duración.

Es parte del área de Gemini, pero no necesita IA: busca directo en YouTube (más rápido y sin costo).

Con YOUTUBE_API_KEY (gratis, 100 búsquedas al día) usa la búsqueda oficial de YouTube. Sin ella, busca con
Tavily dentro de youtube.com.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx

from .config import config
from .research import buscar_tavily

log = logging.getLogger("jarvis.videos")
YOUTUBE = "https://www.googleapis.com/youtube/v3"


def duracion_legible(iso: str) -> str:
    """'PT1H2M3S' → '1:02:03'; 'PT4M5S' → '4:05'."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return ""
    dias, horas, minutos, segundos = (int(x or 0) for x in m.groups())
    horas += dias * 24
    return f"{horas}:{minutos:02d}:{segundos:02d}" if horas else f"{minutos}:{segundos:02d}"


def id_de_youtube(url: str) -> str | None:
    m = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else None


async def _con_youtube(consulta: str, cantidad: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15.0) as http:
        r = await http.get(f"{YOUTUBE}/search", params={
            "part": "snippet", "type": "video", "q": consulta, "maxResults": cantidad, "regionCode": "MX",
            "relevanceLanguage": "es", "safeSearch": "moderate", "key": config.youtube_api_key})
        r.raise_for_status()
        elementos = [e for e in r.json().get("items") or [] if (e.get("id") or {}).get("videoId")]
        ids = [e["id"]["videoId"] for e in elementos]
        duraciones: dict[str, str] = {}
        if ids:
            d = await http.get(f"{YOUTUBE}/videos", params={"part": "contentDetails", "id": ",".join(ids),
                                                            "key": config.youtube_api_key})
            if d.status_code == 200:
                duraciones = {v["id"]: duracion_legible((v.get("contentDetails") or {}).get("duration", ""))
                              for v in d.json().get("items") or []}
    videos = []
    for e in elementos:
        s, vid = e.get("snippet") or {}, e["id"]["videoId"]
        miniatura = ((s.get("thumbnails") or {}).get("medium") or {}).get("url") or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
        videos.append({"titulo": _limpiar_titulo(s.get("title", "")), "canal": s.get("channelTitle", ""),
                       "duracion": duraciones.get(vid, ""), "publicado": (s.get("publishedAt") or "")[:10],
                       "url": f"https://www.youtube.com/watch?v={vid}", "miniatura": miniatura})
    return videos


def _limpiar_titulo(titulo: str) -> str:
    return html.unescape(titulo).strip()


async def _con_tavily(consulta: str, cantidad: int) -> list[dict[str, Any]]:
    resultados = await buscar_tavily(f"{consulta} video", 10, include_domains=["youtube.com"])
    videos, vistos = [], set()
    for r in resultados:
        vid = id_de_youtube(r["url"])
        if not vid or vid in vistos:
            continue
        vistos.add(vid)
        titulo = re.sub(r"\s*-\s*YouTube\s*$", "", r["titulo"]).strip()
        videos.append({"titulo": titulo, "canal": "", "duracion": "", "publicado": "",
                       "url": f"https://www.youtube.com/watch?v={vid}",
                       "miniatura": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
    return videos[:cantidad]


async def buscar_videos(consulta: str, cantidad: int = 6) -> dict[str, Any]:
    cantidad = max(1, min(int(cantidad or 6), 10))
    videos, motor, aviso = [], "", None
    if config.youtube_api_key:
        try:
            videos, motor = await _con_youtube(consulta, cantidad), "youtube"
        except httpx.HTTPStatusError as error:
            texto = error.response.text.lower()
            aviso = ("Se acabó la cuota diaria de YouTube (se reinicia mañana)" if "quota" in texto else
                     "Activa la YouTube Data API v3 en Google Cloud" if "has not been used" in texto or "disabled" in texto
                     else f"YouTube respondió {error.response.status_code}")
            log.warning("YouTube: %s", aviso)
        except httpx.HTTPError as error:
            aviso = f"No pude conectar con YouTube ({type(error).__name__})"
    if not videos and config.tavily_api_key:
        videos, motor = await _con_tavily(consulta, cantidad), "tavily"
    if not videos:
        if aviso:
            return {"error": aviso + "."}
        if not (config.youtube_api_key or config.tavily_api_key):
            return {"error": "Para buscar videos necesito YOUTUBE_API_KEY o TAVILY_API_KEY."}
        return {"error": "No encontré videos sobre eso. ¿Lo busco con otras palabras?"}
    items = [{"texto": v["titulo"], "detalle": " · ".join(x for x in (v["canal"], v["duracion"]) if x) or "YouTube",
              "url": v["url"], "imagen": v["miniatura"]} for v in videos]
    resultado: dict[str, Any] = {
        "total": len(videos), "motor": motor, "_experto": "YouTube",
        "videos": [{"titulo": v["titulo"], "canal": v["canal"], "duracion": v["duracion"]} for v in videos],
        "_mostrar": {"tipo": "lista", "titulo": f"Videos · {consulta[:70]}", "items": items},
        "nota": "Los videos ya están en pantalla; él toca uno para abrirlo."}
    if aviso:
        resultado["_aviso"] = aviso + "; usé la búsqueda web."
    return resultado
