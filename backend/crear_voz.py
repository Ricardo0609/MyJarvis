"""Diseña una voz propia para JARVIS con Gemini (voice design) a partir de una descripción.

Es una voz ORIGINAL con el carácter que buscamos (mayordomo artificial, sereno y elegante);
no imita a ninguna persona real.

Uso (desde la carpeta backend, con el entorno activado):
    python crear_voz.py
Al terminar:
    1. Escucha la muestra en backend/voz_muestra.wav
    2. Si te gusta, copia el ID que aparece (voice_...) en tu .env y en Render:  VOZ_GEMINI=voice_...
Puedes cambiar la DESCRIPCION de abajo y volver a ejecutarlo para crear otra versión.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.config import config  # noqa: E402

DESCRIPCION = (
    "Un asistente artificial con voz masculina de unos 45 años: grave, serena y elegante, "
    "con dicción impecable y ritmo pausado. Cortés y seguro como un mayordomo refinado, "
    "con un humor seco muy sutil y un leve matiz sintético, como si hablara a través de un "
    "sistema de audio de alta gama. Habla español neutro de México."
)


def main():
    if not config.gemini_api_key:
        print("Falta GEMINI_API_KEY en tu .env")
        return
    from google import genai
    from google.genai import types

    from app.research import VERSION_API_GEMINI

    cliente = genai.Client(api_key=config.gemini_api_key,
                           http_options=types.HttpOptions(api_version=VERSION_API_GEMINI))
    print("Diseñando la voz (tarda unos segundos)...")
    try:
        voz = cliente.voices.create(
            store=True,
            voice={
                "model": config.modelo_tts,
                "type": "prompted",
                "display_name": "JARVIS mayordomo",
                "gender": "male",
                "language_code": "es-MX",
                "prompted": {"input": DESCRIPCION},
            },
        )
    except Exception as error:  # noqa: BLE001
        print(f"No se pudo crear la voz: {type(error).__name__}: {error}")
        print("Mientras tanto puedes usar las voces prediseñadas desde el selector de la app.")
        return

    muestra = getattr(getattr(voz, "sample_audio", None), "data", None)
    if muestra:
        archivo = Path("voz_muestra.wav")
        archivo.write_bytes(base64.b64decode(muestra) if isinstance(muestra, str) else bytes(muestra))
        print(f"Muestra guardada en backend/{archivo}")
    print()
    print(f"ID de la voz: {voz.id}")
    print(f"Para usarla, pon esto en tu .env y en Render:  VOZ_GEMINI={voz.id}")


main()
