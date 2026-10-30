// Dibuja lo que JARVIS quiere mostrar: listas (tareas, eventos) o texto (resúmenes, investigaciones).

const titulo = document.getElementById("panel-titulo");
const cuerpo = document.getElementById("panel-cuerpo");
const panel = document.getElementById("panel");

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

function dibujarLista(items) {
  const ul = document.createElement("ul");
  ul.className = "lista";
  for (const item of items) {
    const li = document.createElement("li");
    if (item.hecho) li.className = "hecho";
    const icono = document.createElement("span");
    icono.className = "material-symbols-rounded";
    icono.setAttribute("aria-hidden", "true");
    icono.textContent = item.hecho ? "check_circle" : "radio_button_unchecked";
    const texto = document.createElement("span");
    texto.textContent = item.texto;
    if (item.detalle) {
      const detalle = document.createElement("small");
      detalle.textContent = item.detalle;
      texto.prepend(detalle);
    }
    li.append(icono, texto);
    ul.append(li);
  }
  if (!items.length) {
    const vacio = document.createElement("p");
    vacio.textContent = "No hay nada aquí por ahora.";
    return vacio;
  }
  return ul;
}

function dibujarFuentes(fuentes) {
  const bloque = document.createElement("div");
  bloque.className = "fuentes";
  bloque.innerHTML = "<h3>Fuentes</h3>";
  const ol = document.createElement("ol");
  for (const fuente of fuentes) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = fuente.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = fuente.titulo || fuente.url;
    li.append(a);
    ol.append(li);
  }
  bloque.append(ol);
  return bloque;
}

export function mostrarEnPanel(mostrar) {
  titulo.textContent = mostrar.titulo || "";
  cuerpo.replaceChildren();
  if (mostrar.tipo === "lista") {
    cuerpo.append(dibujarLista(mostrar.items || []));
  } else {
    const texto = document.createElement("div");
    texto.className = "texto";
    texto.innerHTML = markdownAHtml(mostrar.contenido);
    cuerpo.append(texto);
  }
  if (mostrar.fuentes?.length) cuerpo.append(dibujarFuentes(mostrar.fuentes));
  cuerpo.scrollTop = 0;
  panel.hidden = false;
}

export function ocultarPanel() {
  panel.hidden = true;
}
