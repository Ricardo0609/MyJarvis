// Dibuja lo que JARVIS quiere mostrar: listas (tareas, productos, videos), texto (resúmenes, redacciones),
// imágenes creadas por ChatGPT y guías paso a paso.

const titulo = document.getElementById("panel-titulo");
const cuerpo = document.getElementById("panel-cuerpo");
const panel = document.getElementById("panel");
const acciones = document.getElementById("panel-acciones");
const pie = document.getElementById("panel-pie");

function escapar(texto) {
  return String(texto).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function enLinea(texto) {
  return escapar(texto)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

// Markdown sencillo → HTML seguro (todo el texto se escapa antes de dar formato).
export function markdownAHtml(markdown) {
  const lineas = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let lista = null;
  let parrafo = [];

  const cerrarParrafo = () => {
    if (parrafo.length) html.push(`<p>${parrafo.map(enLinea).join("<br>")}</p>`);
    parrafo = [];
  };
  const cerrarLista = () => {
    if (lista) html.push(`</${lista}>`);
    lista = null;
  };
  const abrirLista = (tipo) => {
    cerrarParrafo();
    if (lista !== tipo) {
      cerrarLista();
      html.push(`<${tipo}>`);
      lista = tipo;
    }
  };

  for (let i = 0; i < lineas.length; i++) {
    const linea = lineas[i].trim();
    let m;
    if (linea.startsWith("```")) {
      cerrarParrafo(); cerrarLista();
      const codigo = [];
      while (++i < lineas.length && !lineas[i].trim().startsWith("```")) codigo.push(lineas[i]);
      html.push(`<pre><code>${escapar(codigo.join("\n"))}</code></pre>`);
    } else if (!linea) {
      cerrarParrafo(); cerrarLista();
    } else if ((m = linea.match(/^(#{1,4})\s+(.*)/))) {
      cerrarParrafo(); cerrarLista();
      const nivel = Math.min(m[1].length + 1, 4);
      html.push(`<h${nivel}>${enLinea(m[2])}</h${nivel}>`);
    } else if ((m = linea.match(/^[-*]\s+\[( |x|X)\]\s+(.*)/))) {
      abrirLista("ul");
      html.push(`<li>${m[1].trim() ? "☑" : "☐"} ${enLinea(m[2])}</li>`);
    } else if ((m = linea.match(/^[-*•]\s+(.*)/))) {
      abrirLista("ul");
      html.push(`<li>${enLinea(m[1])}</li>`);
    } else if ((m = linea.match(/^\d+[.)]\s+(.*)/))) {
      abrirLista("ol");
      html.push(`<li>${enLinea(m[1])}</li>`);
    } else if (linea.startsWith(">")) {
      cerrarParrafo(); cerrarLista();
      html.push(`<blockquote>${enLinea(linea.replace(/^>\s?/, ""))}</blockquote>`);
    } else if (linea === "---") {
      cerrarParrafo(); cerrarLista();
      html.push("<hr>");
    } else {
      cerrarLista();
      parrafo.push(linea);
    }
  }
  cerrarParrafo(); cerrarLista();
  return html.join("");
}

// ---------------------------------------------------------------------------
// Piezas
// ---------------------------------------------------------------------------

function crear(etiqueta, clase, texto) {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

function icono(nombre) {
  const span = crear("span", "material-symbols-rounded", nombre);
  span.setAttribute("aria-hidden", "true");
  return span;
}

const enlaceSeguro = (url) => (/^(https?:\/\/|\/api\/archivo\/)/.test(url || "") ? url : "");

function boton(texto, nombreIcono, alTocar, clase = "boton-panel", iconoAlFinal = false) {
  const b = crear("button", clase);
  b.type = "button";
  if (iconoAlFinal) b.append(crear("span", "", texto), icono(nombreIcono));
  else b.append(icono(nombreIcono), crear("span", "", texto));
  b.setAttribute("aria-label", texto);
  b.addEventListener("click", alTocar);
  return b;
}

async function copiar(texto, b) {
  try {
    await navigator.clipboard.writeText(texto);
  } catch {
    const area = crear("textarea");
    area.value = texto;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  const etiqueta = b.querySelector("span:last-child");
  etiqueta.textContent = "Copiado";
  setTimeout(() => { etiqueta.textContent = "Copiar"; }, 1800);
}

function dibujarLista(items) {
  if (!items.length) return crear("p", "", "No hay nada aquí por ahora.");
  const ul = crear("ul", "lista");
  for (const item of items) {
    const li = crear("li");
    const url = enlaceSeguro(item.url);
    const imagen = enlaceSeguro(item.imagen);
    if (item.hecho) li.classList.add("hecho");
    const contenedor = url ? crear("a", "lista__enlace") : li;
    if (url) {
      contenedor.href = url;
      contenedor.target = "_blank";
      contenedor.rel = "noopener noreferrer";
      li.classList.add("con-enlace");
      li.append(contenedor);
    }
    if (imagen) {
      const mini = crear("img", "miniatura");
      mini.src = imagen;
      mini.alt = "";
      mini.loading = "lazy";
      mini.referrerPolicy = "no-referrer";
      contenedor.append(mini);
      li.classList.add("con-miniatura");
    } else {
      contenedor.append(icono(url ? "arrow_outward" : item.hecho ? "check_circle" : "radio_button_unchecked"));
    }
    const texto = crear("span", "lista__texto");
    if (item.detalle) texto.append(crear("small", "", item.detalle));
    texto.append(crear("span", "", item.texto));
    if (item.nota) texto.append(crear("em", "lista__nota", item.nota));
    contenedor.append(texto);
    ul.append(li);
  }
  return ul;
}

function dibujarFuentes(fuentes) {
  const bloque = crear("div", "fuentes");
  bloque.append(crear("h3", "", "Fuentes"));
  const ol = crear("ol");
  for (const fuente of fuentes) {
    if (!enlaceSeguro(fuente.url)) continue;
    const a = crear("a", "", fuente.titulo || fuente.url);
    a.href = fuente.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    const li = crear("li");
    li.append(a);
    ol.append(li);
  }
  bloque.append(ol);
  return bloque;
}

function dibujarImagen(mostrar) {
  const figura = crear("figure", "imagen-creada");
  const img = crear("img");
  img.src = mostrar.imagen;
  img.alt = mostrar.contenido || mostrar.titulo || "Imagen creada";
  figura.append(img);
  if (mostrar.contenido) figura.append(crear("figcaption", "", mostrar.contenido));
  const descargar = crear("a", "boton-panel");
  descargar.href = `${mostrar.imagen}?descargar=1`;
  descargar.download = mostrar.nombre || "imagen.jpg";
  descargar.append(icono("download"), crear("span", "", "Descargar"));
  acciones.append(descargar);
  return figura;
}

// ---------------------------------------------------------------------------
// Guía paso a paso: se recorre con botones o diciendo "siguiente", "anterior", "repite"
// ---------------------------------------------------------------------------

export const guia = {
  datos: null,
  indice: -1, // -1 = vista general (materiales y lista de pasos); pasos.length = terminada
  alCambiar: null, // app.js lo usa para leer el paso en voz alta

  get activa() { return Boolean(this.datos) && document.body.classList.contains("mostrando"); },
  get total() { return this.datos?.pasos.length || 0; },

  textoPaso(i = this.indice) {
    const paso = this.datos?.pasos[i];
    if (!paso) return "";
    return `Paso ${i + 1} de ${this.total}. ${paso.titulo}. ${paso.detalle}`;
  },
  textoActual() {
    if (this.indice < 0) return this.textoMateriales();
    if (this.indice >= this.total) return this.textoFinal();
    return this.textoPaso();
  },
  textoMateriales() {
    const m = this.datos?.materiales || [];
    return m.length ? `Necesita: ${m.join(", ")}.` : "No necesita nada especial. Diga siguiente para empezar.";
  },
  textoFinal() {
    const consejo = this.datos?.consejos?.[0];
    return `Ese fue el último paso. Listo, señor.${consejo ? ` Un consejo: ${consejo}` : ""}`;
  },

  ir(i, { hablar = true } = {}) {
    if (!this.datos) return;
    this.indice = Math.max(-1, Math.min(i, this.total));
    dibujarGuia();
    if (hablar) this.alCambiar?.(this.textoActual(), this.indice);
  },
  siguiente() { this.ir(this.indice + 1); },
  anterior() { this.ir(this.indice - 1); },
  repetir() { this.ir(this.indice); },
};

function dibujarGuia() {
  const d = guia.datos;
  cuerpo.replaceChildren();
  const contenedor = crear("div", "guia");
  const i = guia.indice;

  const progreso = crear("div", "guia__progreso");
  const barra = crear("span");
  barra.style.width = `${Math.max(0, Math.min(i + 1, guia.total)) / guia.total * 100}%`;
  progreso.append(barra);
  contenedor.append(progreso);

  if (i < 0) {
    const resumen = crear("p", "guia__resumen", [d.tiempo, `${guia.total} pasos`].filter(Boolean).join(" · "));
    contenedor.append(resumen);
    if (d.materiales.length) {
      contenedor.append(crear("h3", "guia__subtitulo", "Necesitas"));
      const ul = crear("ul", "guia__materiales");
      d.materiales.forEach((m) => ul.append(crear("li", "", m)));
      contenedor.append(ul);
    }
    contenedor.append(crear("h3", "guia__subtitulo", "Pasos"));
    const ol = crear("ol", "guia__indice");
    d.pasos.forEach((p, n) => {
      const li = crear("li");
      const b = crear("button", "", p.titulo);
      b.type = "button";
      b.addEventListener("click", () => guia.ir(n));
      li.append(b);
      ol.append(li);
    });
    contenedor.append(ol);
  } else if (i >= guia.total) {
    contenedor.append(crear("p", "guia__numero", "Terminado"));
    contenedor.append(crear("h2", "guia__titulo", "¡Listo!"));
    if (d.consejos.length) {
      contenedor.append(crear("h3", "guia__subtitulo", "Consejos"));
      const ul = crear("ul", "guia__materiales");
      d.consejos.forEach((c) => ul.append(crear("li", "", c)));
      contenedor.append(ul);
    }
  } else {
    const paso = d.pasos[i];
    contenedor.append(crear("p", "guia__numero", `Paso ${i + 1} / ${guia.total}`));
    contenedor.append(crear("h2", "guia__titulo", paso.titulo));
    contenedor.append(crear("p", "guia__detalle", paso.detalle));
    if (d.materiales.length) {
      const detalles = crear("details", "guia__plegable");
      detalles.append(crear("summary", "", "Lo que necesitas"));
      const ul = crear("ul", "guia__materiales");
      d.materiales.forEach((m) => ul.append(crear("li", "", m)));
      detalles.append(ul);
      contenedor.append(detalles);
    }
  }
  contenedor.append(crear("p", "guia__ayuda", "Di «siguiente», «anterior», «repite» o «paso 3». Toca el núcleo para hablar."));
  cuerpo.append(contenedor);

  const nav = crear("div", "guia__nav");
  const anterior = boton("Anterior", "arrow_back", () => guia.anterior());
  anterior.disabled = i < 0;
  const repetir = boton("Repetir", "replay", () => guia.repetir(), "boton-panel boton-panel--repetir");
  const siguiente = boton(i < 0 ? "Empezar" : i >= guia.total - 1 ? "Terminar" : "Siguiente", "arrow_forward",
    () => guia.siguiente(), "boton-panel boton-panel--principal", true);
  siguiente.disabled = i >= guia.total;
  nav.append(anterior, repetir, siguiente);
  pie.replaceChildren(nav);
  pie.hidden = false;
  cuerpo.scrollTop = 0;
}

// ---------------------------------------------------------------------------
// Entrada
// ---------------------------------------------------------------------------

export function mostrarEnPanel(mostrar) {
  titulo.textContent = mostrar.titulo || "";
  cuerpo.replaceChildren();
  acciones.replaceChildren();
  pie.replaceChildren();
  pie.hidden = true;
  guia.datos = null;
  panel.dataset.tipo = mostrar.tipo;

  if (mostrar.tipo === "pasos") {
    guia.datos = { materiales: [], consejos: [], tiempo: "", ...mostrar };
    guia.indice = -1;
    dibujarGuia();
  } else if (mostrar.tipo === "lista") {
    cuerpo.append(dibujarLista(mostrar.items || []));
  } else if (mostrar.tipo === "imagen" && enlaceSeguro(mostrar.imagen)) {
    cuerpo.append(dibujarImagen(mostrar));
  } else {
    const texto = crear("div", "texto");
    texto.innerHTML = markdownAHtml(mostrar.contenido);
    cuerpo.append(texto);
    const b = boton("Copiar", "content_copy", () => copiar(mostrar.contenido || "", b));
    acciones.append(b);
  }
  if (mostrar.nota) cuerpo.append(crear("p", "nota-panel", mostrar.nota));
  if (mostrar.fuentes?.length) cuerpo.append(dibujarFuentes(mostrar.fuentes));
  cuerpo.scrollTop = 0;
  panel.hidden = false;
}

export function ocultarPanel() {
  panel.hidden = true;
  guia.datos = null;
}
