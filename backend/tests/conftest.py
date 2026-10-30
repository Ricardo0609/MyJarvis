import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.update({
    "APP_CLAVE": "secreto",
    "ENTORNO": "produccion",
    "NOTION_TOKEN": "ntn_prueba",
    "NOTION_OBJETIVOS_PAGE_ID": "cdcf919711ba419891bc4634a9eab0a6",
    "NOTION_CALENDARIO_DATABASE_ID": "b7b1b527efef42929021415ecbc00347",
    "NOTION_NOTAS_PADRE_ID": "127614d58632410cb07466f7783bab11",
    "ANTHROPIC_API_KEY": "sk-prueba",
    "GEMINI_API_KEY": "gemini-prueba",
    "TAVILY_API_KEY": "tvly-prueba",
})
