# JARVIS — asistente personal por voz

Entras, ves el orbe, tocas el botón, hablas. JARVIS (el director, Claude) decide solo a quién darle cada cosa:

| IA | Se encarga de |
|---|---|
| **Claude** | Notion (pendientes, calendario, páginas), música (Spotify), **redactar** (correos, reportes, mensajes) y todo lo demás |
| **Gemini** | **Investigar y responder tus preguntas**, tu **Gmail, Google Calendar y Drive**, **buscar productos** con precios (de mayor a menor) y **videos** de YouTube |
| **ChatGPT** | **Analizar archivos** (PDF, Word, Excel, PowerPoint, fotos), **crear imágenes** y **guiarte paso a paso** (recetas, electrónica, armar algo) |

Contesta **con voz**. Si pides *ver* algo, el orbe sube, se encoge y aparece el panel. Arriba a la derecha ves quién trabajó (ej. `CLAUDE · GEMINI`).

```
jarvis/
├── backend/                 Servidor en Python (FastAPI)
│   ├── app/
│   │   ├── main.py          Rutas /api/comando, /api/estado, /api/archivo y sirve la página
│   │   ├── cerebro.py       El director: Claude (o Gemini gratis) + uso de herramientas
│   │   ├── tools.py         Las "manos": todas las herramientas y a qué experto van
│   │   ├── notion.py        Objetivos (encabezados + checkboxes), calendario y páginas
│   │   ├── spotify.py       Música
│   │   ├── research.py      Gemini: investigación (Tavily gratis o Google) y preguntas
│   │   ├── cuenta_google.py Gemini: Gmail, Google Calendar y Drive
│   │   ├── compras.py       Gemini: productos con precio y tienda
│   │   ├── videos.py        Videos de YouTube
│   │   ├── chatgpt.py       ChatGPT: archivos, imágenes y guías paso a paso
│   │   ├── archivos.py      Archivos que adjuntas e imágenes creadas (en memoria, 3 horas)
│   │   ├── voz.py           Voz de Charon (Gemini)
│   │   ├── prompts.py       Personalidad e instrucciones de JARVIS (reparto de trabajo)
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
| Hablar | Voz **Charon** de Gemini | Gratis |
| Investigar, preguntas y compras | Tavily (1,000 créditos/mes) + Gemini plan gratis | Gratis |
| Cerebro (tareas, Notion, redactar, decidir) | **Claude Haiku 5.5** | **De pago**: ~1–2 USD/mes con uso diario. Compra mínima de créditos: 5 USD (duran hasta 1 año) |
| Archivos, imágenes y guías | **ChatGPT** (`gpt-6-luna` + `gpt-image-2.5-flare`) | **De pago**: analizar y guiar cuesta fracciones de centavo; cada imagen ~1–2 centavos de dólar. Compra mínima: 5 USD (duran 1 año). Sin llave, Gemini analiza y guía gratis |
| Gmail, Calendar, Drive | APIs de Google | Gratis |
| Videos | YouTube Data API (100 búsquedas/día) | Gratis |
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

### ChatGPT y Google
Tienen su propia sección más abajo: **8. ChatGPT** y **9. Google y YouTube**.

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
| "¿Cómo funciona un transistor?" | Gemini responde (sin gastar búsquedas web si no hace falta) |
| "Búscame un pantalón cargo negro talla 32" | Gemini busca en tiendas y te muestra opciones con precio y enlace, **de mayor a menor precio** |
| "Muéstrame videos de cómo soldar componentes" | Lista de videos de YouTube con miniatura; tócalo para abrirlo |
| "¿Tengo correos importantes hoy?" / "¿Qué dice el último correo de mi jefe?" | Gemini revisa tu Gmail y te resume (sección 9) |
| "¿Qué tengo mañana en Google Calendar?" / "Busca en mi Drive la tesis" | Gemini revisa tu Google Calendar o Drive |
| "Escríbele un correo a mi profesor diciendo que entrego el viernes" | Claude lo redacta en pantalla (botón **Copiar**) y, si quieres, lo deja en **Borradores** de Gmail |
| 📎 adjuntas un PDF/Excel/Word/foto + "¿cuánto suma esta factura?" | ChatGPT lo lee y te responde; puedes seguir preguntando por el mismo archivo |
| 📎 foto de una pieza + "¿qué componente es este?" | ChatGPT analiza la foto |
| "Créame una imagen de un robot naranja para fondo de celular" | ChatGPT la crea; aparece con botón **Descargar** |
| "Guíame para hacer hot cakes" / "Guíame para conectar un sensor al Arduino" | Guía paso a paso: tú dices **"siguiente"**, **"anterior"**, **"repite"**, **"paso 3"**, **"¿qué necesito?"** o **"terminar guía"** |
| "Pon mi playlist de Metallica" | La busca en tu Spotify y la reproduce (ver sección 7) |

Por seguridad **no puede borrar nada** y **nunca envía correos** (solo deja borradores).

Botones: 📎 adjuntar archivo o foto · 🎤 hablar (tócalo mientras habla para interrumpirlo) · ⌨ escribir · ↻ conversación nueva (arriba a la derecha).
En la PC también puedes **arrastrar** un archivo a la ventana o **pegar** una captura con Ctrl+V.

**Guías:** cada paso se lee en voz alta y el siguiente ya viene preparado, así que "siguiente" suena casi al instante.
Si a media guía preguntas algo ("¿puedo usar mantequilla?"), JARVIS te contesta y la guía sigue en pantalla.

**Archivos:** se guardan en la memoria del servidor por 3 horas (o hasta que Render se duerma). Las imágenes creadas descárgalas con el botón. Máximo 20 MB por archivo; las fotos del celular se reducen solas antes de subir.

---

## 6. El orbe: tu Núcleo Lumen

El orbe es tu **Núcleo Lumen** en 3D (`frontend/js/lumen.js`, con Three.js r128 y resplandor).

- Sus estados los controla la app: **Reposo**, **Escuchar**, **Procesar** (mientras piensa) y **Hablar** (mientras responde con voz).
- **Toca el núcleo** para hablar. **Arrástralo** para girarlo en 360°, como en tu diseño original.
- Cuando JARVIS te muestra algo, el núcleo sube y se encoge con una transición suave.
- El modelo 3D sigue siempre la caja del elemento `#orbe`: para cambiar su tamaño o posición basta con editar `--tam-orbe` y `--orbe-y` en `css/styles.css`.
- Si un navegador no tiene WebGL, aparece un núcleo sencillo hecho con CSS para que la app siga funcionando.

## 7. Spotify (requiere Premium)

JARVIS busca tu playlist por su nombre y la reproduce en el dispositivo donde tengas Spotify abierto
(celular, PC o bocina). También: *"pausa"*, *"siguiente"*, *"sube el volumen"*, *"pon aleatorio"*, *"¿qué está sonando?"*.

**Configurarlo (una sola vez, ≈10 minutos):**

1. Entra a https://developer.spotify.com/dashboard con tu cuenta Premium → **Create app**.
2. Llena: **App name** `JARVIS`, **App description** `Asistente personal`, y en **Redirect URIs** agrega estas dos
   (escríbelas exactas, cada una con **Add**):
   - `https://TU-APP.onrender.com/spotify/callback` (con tu dirección real de Render)
   - `http://127.0.0.1:8000/spotify/callback`
   Si pregunta qué API usarás, marca **Web API**. Acepta los términos → **Save**.
3. En **Settings** copia el **Client ID** y, con **View client secret**, el **Client secret**.
4. Pégalos como `SPOTIFY_CLIENT_ID` y `SPOTIFY_CLIENT_SECRET` en tu `.env` y en Render (Environment).
5. Abre JARVIS y dile *"pon mi playlist de Metallica"*. Aparecerá el botón **Conectar Spotify**: inicia sesión y acepta.
6. Al terminar verás un código. Cópialo y guárdalo como `SPOTIFY_REFRESH_TOKEN` en Render y en tu `.env`
   (así no tienes que volver a conectar cuando el servidor se reinicie).

**Cómo funciona en el día a día:**
- Si Spotify ya está abierto en algún dispositivo, la música empieza sola.
- Si está cerrado, aparece el botón **Abrir Spotify**: tócalo y, en cuanto Spotify abra, empieza a sonar tu playlist.
- Busca primero en tus playlists; si no encuentra una con ese nombre, busca en todo Spotify y te lo dice.

**Si algo falla:**
- *"Tu cuenta no está registrada en la app de Spotify"* → en el Dashboard abre tu app → **User Management** →
  agrega tu nombre y el correo de tu cuenta de Spotify.
- *"INVALID_CLIENT: Invalid redirect URI"* al conectar → la dirección de Render en el paso 2 no coincide exacta.
- *"La conexión con Spotify expiró"* → vuelve a tocar **Conectar Spotify** y actualiza `SPOTIFY_REFRESH_TOKEN`.

## 8. ChatGPT (archivos, imágenes y guías)

Sin llave de OpenAI **todo funciona menos crear imágenes**: Gemini analiza los archivos y arma las guías gratis.
Cuando pongas la llave, ChatGPT toma esas tareas (y si un día falla o se acaba el saldo, Gemini lo cubre solo).

1. Entra a https://platform.openai.com → **Settings → Billing → Add payment method** y compra créditos
   (mínimo **5 USD**; duran 1 año). Deja **apagada** la recarga automática (*auto recharge*).
   Tu suscripción de ChatGPT Plus **no** sirve para la API: son cuentas de cobro separadas.
2. **API keys → Create new secret key** → pégala como `OPENAI_API_KEY` en tu `.env` y en Render (Environment).
3. Si al crear una imagen dice que falta **verificar tu organización**: Settings → **Organization → General → Verify Organization**
   (es una verificación de identidad; tarda unos minutos).

Cuánto gasta, más o menos: analizar un PDF de 10 páginas o armar una guía, **menos de 1 centavo de dólar**;
cada imagen en calidad media, **~1–2 centavos**. Para cuidar tu saldo hay un tope de `LIMITE_IMAGENES_DIA=15` imágenes por día.
`CALIDAD_IMAGEN` puede ser `low` (más barata), `medium` o `high` (más cara).

## 9. Google (Gmail, Calendar, Drive) y YouTube

Todo es **gratis**. Se configura una vez (≈15 minutos) en Google Cloud con tu cuenta de Gmail.

1. Entra a https://console.cloud.google.com → arriba, **Seleccionar proyecto → Proyecto nuevo** → nombre `JARVIS` → **Crear**.
2. **APIs y servicios → Biblioteca**: busca y presiona **Habilitar** en cada una:
   **Gmail API**, **Google Calendar API**, **Google Drive API** y **YouTube Data API v3**.
3. **Google Auth Platform** (en el menú; antes se llamaba *Pantalla de consentimiento de OAuth*) → **Comenzar**:
   - Nombre de la app `JARVIS`, tu correo de asistencia → **Público: Externo** → tu correo de contacto → acepta → **Crear**.
4. **Público (Audience)** → **Publicar app** → confirma. Debe decir **En producción**.
   *Importante:* si la dejas en "Prueba", Google desconecta a JARVIS cada 7 días.
   No hace falta mandarla a verificación: es solo para ti.
5. **Clientes → Crear cliente** → tipo **Aplicación web** → nombre `JARVIS` → en **URI de redireccionamiento autorizados** agrega:
   - `https://TU-APP.onrender.com/google/callback` (tu dirección real de Render)
   - `http://127.0.0.1:8000/google/callback`
   → **Crear**. Copia el **ID de cliente** y el **Secreto del cliente** como `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`
   (en tu `.env` y en Render).
6. **APIs y servicios → Credenciales → Crear credenciales → Clave de API**. Edítala → *Restricciones de API* →
   **YouTube Data API v3** → Guardar. Pégala como `YOUTUBE_API_KEY`.
7. Abre JARVIS y pregúntale *"¿tengo correos nuevos?"*. Aparece el botón **Conectar Google** (o abre `/google/conectar`):
   - Elige tu cuenta. Saldrá **"Google no verificó esta app"** → **Configuración avanzada → Ir a JARVIS (no seguro)**.
     Es normal: la app es tuya y nadie más la usa.
   - **Marca todas las casillas** de permisos → **Continuar**.
8. Copia el código que aparece y guárdalo como `GOOGLE_REFRESH_TOKEN` en Render y en tu `.env`.

Permisos que pide: leer tus correos y **crear borradores** (nunca envía nada), ver y crear eventos de Calendar,
y **solo leer** Drive. Puedes quitarle el acceso cuando quieras en https://myaccount.google.com/permissions.

**Calendario:** si dices "calendario" o "agenda" a secas usa tu calendario de **Notion**; si dices "Google Calendar", el de Google.

**Privacidad (importante):** con el plan **gratis** de Gemini, Google puede usar lo que le envías para mejorar sus productos
y personas de Google pueden revisarlo; sus propios términos piden no mandar información personal o confidencial.
Tus correos son justo eso. Tienes dos opciones:
- `EXPERTO_GOOGLE=claude` → Claude lee tu Gmail, Calendar y Drive directamente y Gemini ya no recibe tus correos
  (solo la frase corta que JARVIS dice en voz alta). Anthropic no usa lo que mandas por la API para entrenar.
  Cuesta unos centavos de tus créditos de Claude.
- Dejar `EXPERTO_GOOGLE=gemini` (como lo pediste) y **activar facturación** en tu proyecto de Google AI Studio:
  con eso Google ya no usa tus datos, pero la voz y la investigación también empiezan a cobrarse (poco, pero ya no es $0).

**Videos sin `YOUTUBE_API_KEY`:** también funciona (busca con Tavily dentro de YouTube), pero sin duración ni canal.

## 10. Pruebas

```bash
cd backend
pip install pytest
python -m pytest -q
```

Prueban, sin conectarse a internet: cómo se leen las secciones de tu página de Objetivos, dónde se insertan las tareas nuevas, el ciclo de herramientas de Claude y de Gemini, el respaldo cuando Claude falla, la clave de acceso, el reparto a cada experto, la lectura de Word/Excel, el orden de precios, los videos, Gmail, subir y ver archivos de forma segura y el panel de guías.

Para revisar las llaves reales: `python diagnostico.py` (desde la carpeta `backend`).

---

## 11. Problemas comunes

| Síntoma | Solución |
|---|---|
| "Notion 404 … ¿compartiste esa página?" | Agrega la conexión JARVIS a *¡Hola Ricardo!* (paso 2 de Notion). |
| No escucha en el iPhone | Usa Safari y permite el micrófono. Revisa que **Dictado** esté activado en Ajustes → General → Teclado. |
| No habla en el iPhone | Toca el micrófono una vez (iOS exige un toque antes de reproducir voz) y quita el modo silencio. |
| "Claude no respondió: se acabaron los créditos" | Recarga créditos o cambia a `ORQUESTADOR=gemini`. |
| La investigación dice "sin búsqueda web" | Falta `TAVILY_API_KEY`. |
| "Para crear imágenes falta la llave de ChatGPT" | Pon `OPENAI_API_KEY` (sección 8). |
| "Se acabó el saldo de OpenAI" | Recarga en platform.openai.com → Billing. Mientras, Gemini analiza archivos y arma guías. |
| "Activa la Gmail API en Google Cloud" (o Calendar/Drive/YouTube) | Paso 2 de la sección 9. |
| "El permiso de Google expiró" | Revisa que la app esté **En producción** (paso 4) y vuelve a conectar Google. |
| `Error 400: redirect_uri_mismatch` al conectar Google | La dirección del paso 5 no coincide exacta con la de tu app en Render. |
| "Ese archivo ya expiró" | Los archivos duran 3 horas o hasta que Render se duerme: vuelve a adjuntarlo. |
| La voz suena robótica | Normal con la voz del navegador; después elegimos una voz que te guste. |
