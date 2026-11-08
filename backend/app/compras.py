"""Búsqueda de productos (Gemini): "búscame un pantalón así y así" → opciones con tienda, precio y enlace,
ordenadas de mayor a menor precio (o como lo pidas).

Cómo funciona (gratis): Tavily busca en tiendas en línea y Gemini lee los resultados y saca cada producto con
su precio. Los enlaces siempre son de los resultados reales (Gemini no puede inventar uno). Los precios son los
que aparecían en la web al buscar: pueden cambiar, por eso se pide confirmarlos en la tienda.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import config
from .research import buscar_tavily, generar_gemini

log = logging.getLogger("jarvis.compras")

ORDENES = {"mayor_a_menor": "de mayor a menor precio", "menor_a_mayor": "de menor a mayor precio",
           "relevancia": "por relevancia"}

ESQUEMA = {
    "type": "object",
    "properties": {"productos": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "fuente": {"type": "integer", "description": "Número [n] del resultado de donde sale el producto."},
            "nombre": {"type": "string", "description": "Nombre corto del producto (marca y modelo)."},
            "tienda": {"type": "string"},
            "precio": {"type": "number", "description": "Precio como número, sin símbolos. 0 si no aparece."},
            "moneda": {"type": "string", "description": "MXN, USD, etc."},
            "detalle": {"type": "string", "description": "Lo más relevante: material, color, talla, envío, oferta."},
        },
        "required": ["fuente", "nombre", "tienda", "precio", "moneda", "detalle"]}}},
    "required": ["productos"],
}

INSTRUCCIONES = (
    "Eres un asistente de compras. Recibes resultados de búsqueda web numerados [n]. Extrae productos concretos "
    "que se puedan comprar y que coincidan con lo que busca la persona (descarta artículos de blog, listas "
    "genéricas o productos que no coinciden). Usa solo datos que aparecen en el texto: si el precio no aparece, "
    "pon 0. Si un mismo resultado muestra varios productos que coinciden, puedes sacar hasta 3 de él. "
    "'tienda' es el nombre de la tienda (Amazon, Mercado Libre, Liverpool, la marca, etc.)."
)


def _precio_texto(precio: float, moneda: str) -> str:
    return f"${precio:,.0f} {moneda}".strip() if precio else "precio no visible"


def ordenar(productos: list[dict], orden: str) -> list[dict]:
    if orden == "relevancia":
        return productos
    con_precio = [p for p in productos if p["precio"] > 0]
    sin_precio = [p for p in productos if p["precio"] <= 0]
    con_precio.sort(key=lambda p: p["precio"], reverse=orden != "menor_a_mayor")
    return con_precio + sin_precio


def _limpiar(datos: Any, resultados: list[dict]) -> list[dict]:
    productos, vistos = [], set()
    for p in (datos or {}).get("productos") or []:
        try:
            fuente = int(p.get("fuente", 0))
            precio = float(re.sub(r"[^\d.]", "", str(p.get("precio") or 0)) or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= fuente <= len(resultados) or not str(p.get("nombre") or "").strip():
            continue
        clave = (str(p["nombre"]).lower().strip(), fuente)
        if clave in vistos:
            continue
        vistos.add(clave)
        productos.append({"nombre": str(p["nombre"]).strip()[:120], "tienda": str(p.get("tienda") or "").strip()[:40],
                          "precio": precio, "moneda": (str(p.get("moneda") or "MXN").strip().upper() or "MXN")[:4],
                          "detalle": str(p.get("detalle") or "").strip()[:160], "url": resultados[fuente - 1]["url"]})
    return productos


async def buscar_productos(descripcion: str, orden: str = "mayor_a_menor", presupuesto_max: float | None = None,
                           cantidad: int = 8) -> dict[str, Any]:
    if not config.tavily_api_key:
        return {"error": "Para buscar productos necesito la llave gratuita de Tavily (TAVILY_API_KEY)."}
    if not config.gemini_api_key:
        return {"error": "Para buscar productos necesito GEMINI_API_KEY."}
    orden = orden if orden in ORDENES else "mayor_a_menor"
    resultados = await buscar_tavily(f"{descripcion} comprar precio México tienda en línea", 10, "advanced",
                                     country="mexico")
    if not resultados:
        return {"error": "No encontré tiendas con ese producto. ¿Lo describimos de otra forma?"}
    contexto = "\n\n".join(f"[{i}] {r['titulo']} ({r['url']})\n{r['contenido']}" for i, r in enumerate(resultados, 1))
    respuesta = await generar_gemini(
        config.modelo_gemini, f"La persona busca: {descripcion}\n\nResultados:\n{contexto}",
        system_instruction=INSTRUCCIONES, response_mime_type="application/json", response_json_schema=ESQUEMA)
    try:
        datos = json.loads(respuesta.text or "{}")
    except json.JSONDecodeError:
        datos = {}
    productos = _limpiar(datos, resultados)
    if presupuesto_max:
        productos = [p for p in productos if p["precio"] <= 0 or p["precio"] <= float(presupuesto_max)]
    productos = ordenar(productos, orden)[:max(1, min(int(cantidad or 8), 12))]
    if not productos:
        return {"error": "Encontré resultados pero ninguno con un producto concreto que coincida. ¿Le doy más detalles?",
                "fuentes": [r["url"] for r in resultados[:3]]}

    items = [{"texto": p["nombre"], "detalle": f"{p['tienda']} · {_precio_texto(p['precio'], p['moneda'])}",
              "nota": p["detalle"], "url": p["url"]} for p in productos]
    con_precio = [p for p in productos if p["precio"] > 0]
    return {
        "total": len(productos), "orden": ORDENES[orden], "_experto": "Gemini",
        "mas_caro": max(con_precio, key=lambda p: p["precio"], default=None),
        "mas_barato": min(con_precio, key=lambda p: p["precio"], default=None),
        "_mostrar": {"tipo": "lista", "titulo": f"{descripcion[:70]} · {ORDENES[orden]}", "items": items,
                     "nota": "Precios tomados de la web al momento de buscar: confírmalos en la tienda antes de comprar."},
        "nota": "La lista con enlaces ya está en pantalla.",
    }
