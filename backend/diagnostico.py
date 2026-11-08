"""Diagnóstico de JARVIS: prueba cada servicio por separado y muestra el error exacto.

Uso (desde la carpeta backend, con el entorno activado):
    python diagnostico.py
No muestra tus llaves completas.
"""
import asyncio
import sys
import traceback

sys.path.insert(0, ".")

from app.config import config  # noqa: E402

resultados = []


def mostrar(nombre, ok, detalle=""):
    marca = "OK   " if ok else "FALLA"
    print(f"[{marca}] {nombre}" + (f"\n         {detalle}" if detalle else ""))
    resultados.append((nombre, ok))


def error_corto(error):
    texto = f"{type(error).__name__}: {error}"
    return texto.replace("\n", " ")[:600]


def llave(valor):
    return f"configurada ({valor[:4]}…, {len(valor)} caracteres)" if valor else "VACÍA"


async def probar_gemini():
    if not config.gemini_api_key:
        mostrar("Gemini", False, "GEMINI_API_KEY está vacía en el .env")
        return
    from google.genai import types

    from app.research import gemini

    # 1. ¿La llave funciona y qué modelos ve?
    try:
        modelos = [m.name.replace("models/", "") async for m in await gemini().aio.models.list()]
        flash = [m for m in modelos if "flash" in m]
        mostrar("Gemini: la llave funciona", True, f"{len(modelos)} modelos visibles. Flash: {', '.join(flash[:12])}")
        for nombre in dict.fromkeys((config.modelo_gemini_orquestador, config.modelo_gemini, *config.modelos_gemini_respaldo)):
            existe = nombre in modelos
            mostrar(f"Gemini: el modelo '{nombre}' existe en tu cuenta", existe,
                    "" if existe else "Ese nombre no aparece en la lista de arriba")
    except Exception as error:  # noqa: BLE001
        mostrar("Gemini: la llave funciona", False, error_corto(error))
        return

    # 2. Respuesta simple, sin herramientas (principal, investigación y respaldos)
    for nombre in dict.fromkeys((config.modelo_gemini_orquestador, config.modelo_gemini, *config.modelos_gemini_respaldo)):
        try:
            r = await gemini().aio.models.generate_content(model=nombre, contents="Responde solo: hola")
            mostrar(f"Gemini '{nombre}': respuesta simple", True, f"Respondió: {(r.text or '').strip()[:60]}")
        except Exception as error:  # noqa: BLE001
            mostrar(f"Gemini '{nombre}': respuesta simple", False, error_corto(error))

    # 2b. Con reintento y cambio automático de modelo (lo que usa JARVIS)
    from app.research import generar_gemini_con_modelo
    try:
        _, usado = await generar_gemini_con_modelo(config.modelo_gemini_orquestador, "Responde solo: hola")
        mostrar("Gemini con respaldo automático", True, f"Respondió el modelo: {usado}")
    except Exception as error:  # noqa: BLE001
        mostrar("Gemini con respaldo automático", False, error_corto(error))

    # 3. Con razonamiento corto
    try:
        await gemini().aio.models.generate_content(
            model=config.modelo_gemini_orquestador, contents="Responde solo: hola",
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="LOW")))
        mostrar("Gemini: razonamiento corto", True)
    except Exception as error:  # noqa: BLE001
        mostrar("Gemini: razonamiento corto", False, error_corto(error))

    # 4. Con las herramientas de JARVIS
    from app.tools import herramientas_gemini
    try:
        await gemini().aio.models.generate_content(
            model=config.modelo_gemini_orquestador, contents="Di hola usando la herramienta responder",
            config=types.GenerateContentConfig(
                tools=herramientas_gemini(),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        mostrar("Gemini: acepta las herramientas de JARVIS", True)
    except Exception as error:  # noqa: BLE001
        mostrar("Gemini: acepta las herramientas de JARVIS", False, error_corto(error))

    # 5. El flujo completo, como cuando le hablas
    from app.cerebro import con_gemini
    from app.prompts import prompt_sistema
    try:
        r = await con_gemini("Hola, ¿me escuchas?", [], prompt_sistema([], [], bool(config.notion_token)))
        mostrar("JARVIS completo con Gemini", True, f"Voz: {r['voz'][:120]}")
    except Exception as error:  # noqa: BLE001
        mostrar("JARVIS completo con Gemini", False, error_corto(error))
        traceback.print_exc()


async def probar_voz():
    from app import voz
    if not voz.disponible():
        print(f"[ --  ] Voz de Gemini: desactivada (VOZ_MOTOR={config.voz_motor}); se usa la del navegador")
        return
    try:
        audio = await voz.sintetizar("Hola, bienvenido de nuevo.")
        mostrar(f"Voz de Gemini ({config.voz_gemini})", len(audio) > 1000, f"{len(audio) // 1024} KB de audio generados")
    except Exception as error:  # noqa: BLE001
        mostrar(f"Voz de Gemini ({config.voz_gemini})", False, error_corto(error))


async def probar_spotify():
    from app.spotify import spotify
    if not spotify.configurado:
        print("[ --  ] Spotify: sin configurar (faltan SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET)")
        return
    if not spotify.conectado:
        mostrar("Spotify: cuenta conectada", False,
                "Falta SPOTIFY_REFRESH_TOKEN: en la app toca «Conectar Spotify» (o pídele música a JARVIS)")
        return
    try:
        playlists = await spotify.mis_playlists()
        mostrar("Spotify: cuenta conectada", True, f"{len(playlists)} playlists: "
                + "; ".join(p["nombre"][:25] for p in playlists[:6]))
        datos = await spotify._pedir("GET", "/me/player/devices") or {}
        nombres = [f"{d.get('name')} ({d.get('type')})" for d in datos.get("devices") or []]
        print(f"         Dispositivos con Spotify abierto: {', '.join(nombres) or 'ninguno (abre Spotify para probar)'}")
    except Exception as error:  # noqa: BLE001
        mostrar("Spotify: cuenta conectada", False, error_corto(error))
    await spotify.cerrar()


async def probar_chatgpt():
    if not config.openai_api_key:
        print("[ --  ] ChatGPT: sin OPENAI_API_KEY (Gemini analiza archivos y arma guías mientras tanto; "
              "crear imágenes necesita la llave)")
        return
    from app.chatgpt import cliente, explicar_error_openai
    try:
        r = await cliente().responses.create(model=config.modelo_chatgpt, input="Responde solo: hola",
                                             max_output_tokens=20)
        mostrar(f"ChatGPT '{config.modelo_chatgpt}'", True, f"Respondió: {(r.output_text or '').strip()[:60]}")
    except Exception as error:  # noqa: BLE001
        mostrar(f"ChatGPT '{config.modelo_chatgpt}'", False, f"{explicar_error_openai(error)} | {error_corto(error)}")
    print(f"         Imágenes: {config.modelo_imagen}, calidad {config.calidad_imagen} "
          "(no se prueba aquí para no gastar saldo; pídele una a JARVIS)")


async def probar_google():
    from app.cuenta_google import GoogleError, google
    if not google.configurado:
        print("[ --  ] Google: sin configurar (faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET)")
        return
    if not google.conectado:
        mostrar("Google: cuenta conectada", False,
                "Falta GOOGLE_REFRESH_TOKEN: en la app abre /google/conectar (o pídele tus correos a JARVIS)")
        return
    pruebas = [("Gmail", google.gmail_buscar("in:inbox", 1)),
               ("Google Calendar", google.calendario_listar("2026-01-01", "2026-12-31")),
               ("Google Drive", google.drive_buscar("a"))]
    for nombre, prueba in pruebas:
        try:
            r = await prueba
            cuantos = len(r.get("correos") or r.get("eventos") or r.get("archivos") or [])
            mostrar(f"Google: {nombre}", True, f"{cuantos} elemento(s) leídos")
        except GoogleError as error:
            mostrar(f"Google: {nombre}", False, str(error))
        except Exception as error:  # noqa: BLE001
            mostrar(f"Google: {nombre}", False, error_corto(error))
    await google.cerrar()


async def probar_youtube():
    if not config.youtube_api_key:
        print("[ --  ] YouTube: sin YOUTUBE_API_KEY (los videos se buscan con Tavily)")
        return
    from app.videos import _con_youtube
    try:
        r = await _con_youtube("tutorial arduino", 1)
        mostrar("YouTube", bool(r), f"Primer video: {r[0]['titulo'][:60]}" if r else "Sin resultados")
    except Exception as error:  # noqa: BLE001
        detalle = getattr(getattr(error, "response", None), "text", "") or str(error)
        mostrar("YouTube", False, error_corto(Exception(detalle[:300])))


async def probar_tavily():
    if not config.tavily_api_key:
        mostrar("Tavily (búsqueda web)", False, "TAVILY_API_KEY está vacía en el .env")
        return
    from app.research import buscar_tavily
    try:
        r = await buscar_tavily("tipo de cambio dólar peso hoy", 2)
        mostrar("Tavily (búsqueda web)", bool(r), f"{len(r)} resultados. Primero: {r[0]['titulo'][:70] if r else '-'}")
    except Exception as error:  # noqa: BLE001
        mostrar("Tavily (búsqueda web)", False, error_corto(error))


async def probar_claude():
    if not config.anthropic_api_key:
        print("[ --  ] Claude: sin llave (está bien si por ahora usas Gemini)")
        return
    import anthropic
    try:
        cliente = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        r = await cliente.messages.create(model=config.modelo_claude, max_tokens=20,
                                          messages=[{"role": "user", "content": "Responde solo: hola"}])
        mostrar(f"Claude '{config.modelo_claude}'", True, f"Respondió: {r.content[0].text[:60]}")
    except Exception as error:  # noqa: BLE001
        mostrar(f"Claude '{config.modelo_claude}'", False, error_corto(error))


async def probar_notion():
    if not config.notion_token:
        print("[ --  ] Notion: sin token (aún no conectado)")
        return
    from app.notion import notion
    try:
        secciones = await notion.secciones_objetivos(forzar=True)
        mostrar("Notion: página Objetivos", True, f"{len(secciones)} secciones: " + "; ".join(s.titulo[:30] for s in secciones[:6]))
    except Exception as error:  # noqa: BLE001
        mostrar("Notion: página Objetivos", False, error_corto(error))
    try:
        r = await notion.listar_eventos("2026-01-01", "2026-12-31")
        mostrar("Notion: calendario", True, f"{len(r['eventos'])} eventos este año")
    except Exception as error:  # noqa: BLE001
        mostrar("Notion: calendario", False, error_corto(error))
    await notion.cerrar()


async def main():
    print("=" * 60)
    print("DIAGNÓSTICO DE JARVIS")
    print(f"Python {sys.version.split()[0]}")
    print(f"Cerebro elegido: {config.orquestador} -> en uso: {config.orquestador_efectivo}")
    print(f"GEMINI_API_KEY: {llave(config.gemini_api_key)}")
    print(f"TAVILY_API_KEY: {llave(config.tavily_api_key)}")
    print(f"ANTHROPIC_API_KEY: {llave(config.anthropic_api_key)}")
    print(f"NOTION_TOKEN: {llave(config.notion_token)}")
    print(f"OPENAI_API_KEY: {llave(config.openai_api_key)}")
    print(f"GOOGLE_CLIENT_ID: {llave(config.google_client_id)} | YOUTUBE_API_KEY: {llave(config.youtube_api_key)}")
    print("=" * 60)
    await probar_gemini()
    await probar_voz()
    await probar_tavily()
    await probar_claude()
    await probar_notion()
    await probar_spotify()
    await probar_chatgpt()
    await probar_google()
    await probar_youtube()
    print("=" * 60)
    fallas = [n for n, ok in resultados if not ok]
    print("Todo bien." if not fallas else f"{len(fallas)} prueba(s) fallaron. Copia todo este texto y mándaselo a Claude.")


asyncio.run(main())
