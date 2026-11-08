"""Configuración leída de variables de entorno (.env en local, panel de Render en producción)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")
load_dotenv(RAIZ / "backend" / ".env")


def _env(nombre: str, defecto: str = "") -> str:
    return (os.getenv(nombre) or defecto).strip()


def _limpiar_id(valor: str) -> str:
    """Acepta un ID de Notion con o sin guiones, o una URL completa, y devuelve solo el ID."""
    valor = valor.strip()
    if not valor:
        return ""
    valor = valor.split("?")[0].rstrip("/").split("/")[-1]
    hexa = "".join(c for c in valor.split("-")[-1] if c in "0123456789abcdefABCDEF")
    if len(hexa) == 32:
        return hexa.lower()
    solo_hexa = "".join(c for c in valor if c in "0123456789abcdefABCDEF")
    return solo_hexa[-32:].lower() if len(solo_hexa) >= 32 else valor


@dataclass(frozen=True)
class Config:
    # Acceso a la app
    clave_app: str
    entorno: str
    zona_horaria: str
    nombre_usuario: str

    # Cerebro (orquestador)
    orquestador: str  # "claude" | "gemini"
    anthropic_api_key: str
    modelo_claude: str

    # Gemini
    gemini_api_key: str
    modelo_gemini: str
    modelo_gemini_orquestador: str
    modelos_gemini_respaldo: tuple[str, ...]

    # Voz (texto a voz)
    voz_motor: str  # "gemini" | "navegador"
    modelo_tts: str
    modelos_tts_respaldo: tuple[str, ...]
    voz_gemini: str
    voz_estilo: str

    # Investigación
    investigacion_modo: str  # "gratis" | "google"
    tavily_api_key: str

    # Notion
    notion_token: str
    notion_version: str
    notion_objetivos_id: str
    notion_calendario_db_id: str
    notion_calendario_ds_id: str
    notion_notas_padre_id: str

    # Spotify (requiere Premium)
    spotify_client_id: str
    spotify_client_secret: str
    spotify_refresh_token: str
    spotify_redirect_uri: str

    # ChatGPT (OpenAI): archivos, imágenes y guías paso a paso
    openai_api_key: str
    modelo_chatgpt: str
    modelo_imagen: str
    calidad_imagen: str
    limite_imagenes_dia: int

    # Google (Gmail, Calendar, Drive) y YouTube: los maneja Gemini
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    google_redirect_uri: str
    youtube_api_key: str
    experto_google: str  # "gemini" (resume Gemini) | "claude" (Claude lee directo; más privado)

    @property
    def orquestador_efectivo(self) -> str:
        """Si eliges Claude pero no hay llave, cae a Gemini (gratis) para no dejarte sin asistente."""
        if self.orquestador == "claude" and self.anthropic_api_key:
            return "claude"
        if self.gemini_api_key:
            return "gemini"
        return "ninguno"


def cargar_config() -> Config:
    return Config(
        clave_app=_env("APP_CLAVE"),
        entorno=_env("ENTORNO", "produccion").lower(),
        zona_horaria=_env("ZONA_HORARIA", "America/Mexico_City"),
        nombre_usuario=_env("NOMBRE_USUARIO", "Ricardo"),
        orquestador=_env("ORQUESTADOR", "claude").lower(),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        modelo_claude=_env("MODELO_CLAUDE", "claude-haiku-5-5"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        modelo_gemini=_env("MODELO_GEMINI", "gemini-3.5-flash-lite"),
        modelo_gemini_orquestador=_env("MODELO_GEMINI_ORQUESTADOR", "gemini-3.8-flash"),
        modelos_gemini_respaldo=tuple(m.strip() for m in _env(
            "MODELOS_GEMINI_RESPALDO", "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",")
            if m.strip()),
        voz_motor=_env("VOZ_MOTOR", "gemini").lower(),
        modelo_tts=_env("MODELO_TTS", "gemini-3.8-flash-lite-tts"),  # el más rápido primero
        modelos_tts_respaldo=tuple(m.strip() for m in _env(
            "MODELOS_TTS_RESPALDO", "gemini-3.8-flash-tts").split(",") if m.strip()),
        voz_gemini=_env("VOZ_GEMINI", "Charon"),
        voz_estilo=_env("VOZ_ESTILO", "sereno, elegante y preciso, como un mayordomo refinado"),
        investigacion_modo=_env("INVESTIGACION_MODO", "gratis").lower(),
        tavily_api_key=_env("TAVILY_API_KEY"),
        notion_token=_env("NOTION_TOKEN"),
        notion_version=_env("NOTION_VERSION", "2026-03-11"),
        # IDs de tus páginas (no son secretos): así funciona aunque falten en el .env o en Render.
        notion_objetivos_id=_limpiar_id(_env("NOTION_OBJETIVOS_PAGE_ID", "cdcf919711ba419891bc4634a9eab0a6")),
        notion_calendario_db_id=_limpiar_id(_env("NOTION_CALENDARIO_DATABASE_ID", "b7b1b527efef42929021415ecbc00347")),
        notion_calendario_ds_id=_env("NOTION_CALENDARIO_DATA_SOURCE_ID"),
        notion_notas_padre_id=_limpiar_id(_env("NOTION_NOTAS_PADRE_ID", "40a7aa605b5b81e585e0d43c39b8f57d")),
        spotify_client_id=_env("SPOTIFY_CLIENT_ID"),
        spotify_client_secret=_env("SPOTIFY_CLIENT_SECRET"),
        spotify_refresh_token=_env("SPOTIFY_REFRESH_TOKEN"),
        spotify_redirect_uri=_env("SPOTIFY_REDIRECT_URI"),  # opcional: se calcula solo
        openai_api_key=_env("OPENAI_API_KEY"),
        modelo_chatgpt=_env("MODELO_CHATGPT", "gpt-6-luna"),
        modelo_imagen=_env("MODELO_IMAGEN", "gpt-image-2.5-flare"),
        calidad_imagen=_env("CALIDAD_IMAGEN", "medium").lower(),
        limite_imagenes_dia=_entero(_env("LIMITE_IMAGENES_DIA", "15"), 15),
        google_client_id=_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=_env("GOOGLE_REFRESH_TOKEN"),
        google_redirect_uri=_env("GOOGLE_REDIRECT_URI"),  # opcional: se calcula solo
        youtube_api_key=_env("YOUTUBE_API_KEY"),
        experto_google=_env("EXPERTO_GOOGLE", "gemini").lower(),
    )


def _entero(valor: str, defecto: int) -> int:
    try:
        return int(valor)
    except ValueError:
        return defecto


config = cargar_config()
