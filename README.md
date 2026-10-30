# JARVIS — asistente personal por voz

Entras, ves el orbe, tocas el botón, hablas. JARVIS decide solo qué hacer:

- **Investigar algo actual** → Gemini (busca en la web y resume).
- **Pendientes, calendario, páginas de Notion, crear cosas** → Claude.
- Contesta **con voz**. Si pides *ver* algo, el orbe sube, se encoge y aparece el panel.

```
jarvis/
├── backend/                 Servidor en Python (FastAPI)
│   ├── app/
│   │   ├── main.py          Rutas /api/comando, /api/estado y sirve la página
│   │   ├── cerebro.py       El director: Claude (o Gemini gratis) + uso de herramientas
│   │   ├── tools.py         Las "manos": herramientas de Notion e investigación
│   │   ├── notion.py        Objetivos (encabezados + checkboxes), calendario y páginas
│   │   ├── research.py      Investigación: Gemini + Tavily (gratis) o Gemini + Google
│   │   ├── prompts.py       Personalidad e instrucciones de JARVIS
│   │   ├── sesiones.py      Memoria corta de la conversación
│   │   └── config.py        Lee las variables de entorno
│   ├── tests/               Pruebas automáticas (pytest)
│   └── requirements.txt
├── frontend/                La página (HTML, CSS y JS sin frameworks)
│   ├── index.html
│   ├── css/styles.css
│   └── js/  app.js · orbe.js · voz.js · panel.js · api.js
├── .env.example             Plantilla de configuración
└── render.yaml              Despliegue en Render con un clic
```

---

## 1. Qué cuesta (y qué no)

| Pieza | Opción por defecto | Costo |
|---|---|---|
| Escuchar tu voz | Reconocimiento del navegador | Gratis |
| Hablar | Voz del navegador | Gratis |
| Investigar en la web | Tavily (1,000 búsquedas/mes) + Gemini plan gratis | Gratis |
| Cerebro (tareas, Notion, decidir) | **Claude Haiku 5.5** | **De pago**: ~1–2 USD/mes con uso diario. Compra mínima de créditos: 5 USD (duran hasta 1 año) |
| Notion | API de Notion | Gratis |
| Servidor | Render plan free | Gratis (se duerme tras 15 min sin uso) |

**Alternativa sin pagar nada:** pon `ORQUESTADOR=gemini` y JARVIS usa Gemini (plan gratis) como cerebro.
Y si eliges Claude y un día se acaban los créditos, **Gemini responde automáticamente** para que no te quedes sin asistente.

> Ojo con el plan gratis de Gemini: Google puede usar lo que le envíes para mejorar sus productos. Si activas facturación en AI Studio, eso deja de pasar (y se cobra por uso).
>
> Tu suscripción Google AI Plus **no aplica a la API**: los beneficios de los planes de Google AI solo funcionan dentro de la web de AI Studio.

Opcional de pago: `INVESTIGACION_MODO=google` hace que Gemini busque directo en Google (requiere facturación; incluye 5,000 búsquedas gratis al mes, pero los tokens se cobran).

---

## 2. Consigue tus llaves (≈15 minutos)

### Gemini (gratis)
1. Entra a https://aistudio.google.com/apikey → **Create API key**.
2. Cópiala en `GEMINI_API_KEY`.

### Tavily (gratis, sin tarjeta)
1. Regístrate en https://app.tavily.com → copia tu llave (`tvly-...`).
2. Pégala en `TAVILY_API_KEY`.

### Claude (de pago)
1. Entra a https://platform.claude.com → **Billing → Buy credits** (mínimo 5 USD).
   Recomendado: deja **apagada** la recarga automática y pon un límite de gasto mensual.
2. **API keys → Create key** → pégala en `ANTHROPIC_API_KEY`.

### Notion
1. Ve a https://www.notion.so/profile/integrations → **New integration** (tipo *Internal*), nómbrala "JARVIS".
2. En *Capabilities* activa: **Read content, Update content, Insert content**.
3. Copia el *Internal Integration Secret* (`ntn_...`) en `NOTION_TOKEN`.
4. En Notion abre tu página **¡Hola Ricardo!** → menú **•••** → **Conexiones** → agrega **JARVIS**.
   Con eso JARVIS ve todo lo que cuelga de ahí: *Objetivos* y *Actividades del mes*.
5. Crea una página llamada **JARVIS** (dentro de ¡Hola Ricardo!) para las notas que él cree.
   Copia su enlace y pégalo en `NOTION_NOTAS_PADRE_ID`.

Los IDs de *Objetivos* y del calendario ya vienen llenos en `.env.example`.

---

## 3. Correrlo en tu computadora

Necesitas Python 3.11 o superior.

```bash
cd jarvis
cp .env.example .env          # en Windows: copy .env.example .env
# abre .env y pega tus llaves

cd backend
python -m venv .venv
source .venv/bin/activate     # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abre **http://localhost:8000** en Chrome. Toca el núcleo o presiona la **barra espaciadora** para hablar.
Con `ENTORNO=local` y `APP_CLAVE` vacía no te pide clave. Si llenas `APP_CLAVE`, la app te pedirá exactamente ese texto.

> En el celular el micrófono solo funciona con **https**, así que para probar en el teléfono usa la versión publicada en Render.

---

## 4. Publicarlo en Render (para usarlo en PC y celular)

1. Sube la carpeta `jarvis` a un repositorio **privado** de GitHub **con git** (no arrastrando archivos en la web: así se respeta el `.gitignore` y tu `.env` no se sube).
2. En Render: **New → Web Service** → conecta el repositorio y configura:
   - **Language:** Python 3 · **Branch:** main · **Root Directory:** vacío (importante: el servidor necesita ver `backend` y `frontend`)
   - **Build Command:** `pip install -r backend/requirements.txt`
   - **Start Command:** `uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free
   - **Environment Variables:** las mismas de tu `.env`, pero con `ENTORNO=produccion` y una `APP_CLAVE` larga (obligatoria).
   - **Health Check Path** (en Advanced): `/salud`
3. Al terminar tendrás una URL tipo `https://jarvis-xxxx.onrender.com`. La primera vez te pide la `APP_CLAVE` (se guarda en ese dispositivo).
4. En el celular: ábrela en **Safari** (iPhone) o **Chrome** (Android) → **Agregar a pantalla de inicio**. Se abre a pantalla completa, como app.

Alternativa: **New → Blueprint** usa `render.yaml` con esta misma configuración.

**La clave es importante:** sin ella cualquiera con la URL podría leer tu Notion y gastar tus créditos.

**Plan gratis de Render:** si no lo usas en 15 minutos se duerme y la primera orden tarda ~30–60 s (verás "Despertando el servidor…"). Las siguientes son rápidas.

---

## 5. Qué le puedes pedir

| Dices | Qué hace |
|---|---|
| "¿Qué tengo pendiente hoy?" | Lee *Tareas más importantes del día* y te lo dice |
| "Muéstrame mis pendientes de la semana" | Igual, pero además lo pone en pantalla |
| "Agrega 'comprar audífonos' a pendientes de la semana" | Crea el checkbox debajo del último de esa sección |
| "Marca como hecha la de investigar agentes" | Busca la tarea y la palomea |
| "¿Qué tengo en el calendario esta semana?" | Lee *Actividades del mes* |
| "Agenda el partido de Lakers el sábado a las 7 de la noche" | Crea el evento con tipo *Partido* |
| "Resume mi página de Hábitos atómicos y guárdalo en una página nueva" | Lee, resume y crea la página en *JARVIS* |
| "¿Cuándo sale el próximo juego de…?" / "¿Cómo está el dólar hoy?" | Investiga con Gemini y te responde |
| "Investiga los mejores audífonos de 1,500 pesos y guárdalo en Notion" | Investiga **y** guarda (combina expertos) |

Por seguridad **no puede borrar nada** (no tiene esa herramienta).

Botones: ⌨ escribir en vez de hablar · 🎤 hablar (tócalo mientras habla para interrumpirlo) · ↻ conversación nueva.

---

## 6. El orbe: tu Núcleo Lumen

El orbe es tu **Núcleo Lumen** en 3D (`frontend/js/lumen.js`, con Three.js r128 y resplandor).

- Sus estados los controla la app: **Reposo**, **Escuchar**, **Procesar** (mientras piensa) y **Hablar** (mientras responde con voz).
- **Toca el núcleo** para hablar. **Arrástralo** para girarlo en 360°, como en tu diseño original.
- Cuando JARVIS te muestra algo, el núcleo sube y se encoge con una transición suave.
- El modelo 3D sigue siempre la caja del elemento `#orbe`: para cambiar su tamaño o posición basta con editar `--tam-orbe` y `--orbe-y` en `css/styles.css`.
- Si un navegador no tiene WebGL, aparece un núcleo sencillo hecho con CSS para que la app siga funcionando.

## 7. Pruebas

```bash
cd backend
pip install pytest
python -m pytest -q
```

Prueban, sin conectarse a internet: cómo se leen las secciones de tu página de Objetivos, dónde se insertan las tareas nuevas, el ciclo de herramientas de Claude y de Gemini, el respaldo cuando Claude falla y la clave de acceso.

---

## 8. Problemas comunes

| Síntoma | Solución |
|---|---|
| "Notion 404 … ¿compartiste esa página?" | Agrega la conexión JARVIS a *¡Hola Ricardo!* (paso 2 de Notion). |
| No escucha en el iPhone | Usa Safari y permite el micrófono. Revisa que **Dictado** esté activado en Ajustes → General → Teclado. |
| No habla en el iPhone | Toca el micrófono una vez (iOS exige un toque antes de reproducir voz) y quita el modo silencio. |
| "Claude no respondió: se acabaron los créditos" | Recarga créditos o cambia a `ORQUESTADOR=gemini`. |
| La investigación dice "sin búsqueda web" | Falta `TAVILY_API_KEY`. |
| La voz suena robótica | Normal con la voz del navegador; después elegimos una voz que te guste. |
