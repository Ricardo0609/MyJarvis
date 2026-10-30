// Controlador del orbe. La app solo usa:
//   orbe.estado("reposo" | "escuchando" | "pensando" | "hablando" | "error")
//   orbe.nivel(0..1)          → intensidad de la voz mientras habla
//   orbe.mostrar(true/false)  → sube y se encoge cuando hay contenido en pantalla
//
// El orbe es tu Núcleo Lumen (js/lumen.js). Si el navegador no tiene WebGL,
// se usa un orbe sencillo hecho con CSS para que la app siga funcionando.

import { crearLumen } from "./lumen.js";

const MODO_LUMEN = {
  reposo: "idle",
  escuchando: "listen",
  pensando: "think",
  hablando: "speak",
  error: "idle",
};

export function crearOrbe({ alTocar } = {}) {
  const lumen = crearLumen(document.getElementById("lienzo"), {
    objetivo: document.getElementById("orbe"),
    alTocar,
  });
  document.body.classList.toggle("con-lumen", lumen.ok);

  return {
    estado(nuevo) {
      document.body.dataset.estado = nuevo;
      lumen.modo(MODO_LUMEN[nuevo] || "idle");
      if (nuevo !== "hablando") this.nivel(0);
    },
    nivel(valor) {
      const v = Math.max(0, Math.min(1, valor || 0));
      lumen.nivel(v);
      document.documentElement.style.setProperty("--nivel", v.toFixed(3));
    },
    mostrar(activo) {
      document.body.classList.toggle("mostrando", activo);
    },
  };
}
