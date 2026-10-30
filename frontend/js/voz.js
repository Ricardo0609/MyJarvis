// Voz: escuchar (reconocimiento del navegador) y hablar (voz de Gemini, con la del navegador de respaldo).

import { desbloquearAudio, detenerAudio, reproducirAudio } from "./audio.js";

const Reconocimiento = window.SpeechRecognition || window.webkitSpeechRecognition;

export const escucha = {
  soportada: Boolean(Reconocimiento),
  activa: false,
  ultimoError: "",
  _rec: null,
  _vigilante: null,

  iniciar({ alParcial, alTerminar, alError } = {}) {
    if (!Reconocimiento) {
      alError?.("no-soportado");
      return;
    }
    // Si quedó un reconocimiento anterior abierto, se cierra antes de abrir otro.
    if (this._rec) {
      try { this._rec.abort(); } catch { /* ya estaba cerrado */ }
      this._rec = null;
    }
    // Que no esté sonando nada mientras se abre el micrófono.
    detenerAudio();

    const rec = new Reconocimiento();
    rec.lang = "es-MX";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let textoFinal = "";
    let ultimoParcial = "";
    let terminado = false;
    this.ultimoError = "";

    const terminar = () => {
      if (terminado) return;
      terminado = true;
      clearTimeout(this._vigilante);
      this.activa = false;
      if (this._rec === rec) this._rec = null;
      // Algunos navegadores cortan antes de marcar el último resultado como final.
      alTerminar?.((textoFinal || ultimoParcial).trim());
    };

    rec.onresult = (evento) => {
      let parcial = "";
      for (let i = evento.resultIndex; i < evento.results.length; i++) {
        const resultado = evento.results[i];
        if (resultado.isFinal) textoFinal += resultado[0].transcript;
        else parcial += resultado[0].transcript;
      }
      ultimoParcial = parcial;
      alParcial?.((textoFinal + " " + parcial).trim());
    };
    rec.onerror = (evento) => {
      this.ultimoError = evento.error || "desconocido";
      if (evento.error !== "no-speech" && evento.error !== "aborted") alError?.(evento.error);
    };
    rec.onend = terminar;

    this._rec = rec;
    this.activa = true;
    // Respaldo: si en 15 s el navegador no cierra el micrófono, lo cerramos nosotros.
    this._vigilante = setTimeout(() => {
      try { rec.stop(); } catch { /* nada */ }
      setTimeout(terminar, 1500);
    }, 15000);
    try {
      rec.start();
    } catch (error) {
      this.ultimoError = error.name || "no se pudo iniciar";
      terminado = true;
      clearTimeout(this._vigilante);
      this.activa = false;
      this._rec = null;
      alError?.("ocupado");
    }
  },

  detener() {
    try { this._rec?.stop(); } catch { /* ya estaba cerrado */ }
  },
};

// ---------------------------------------------------------------------------

function puntuarVoz(voz) {
  const idioma = voz.lang.toLowerCase().replace("_", "-");
  if (!idioma.startsWith("es")) return -1;
  let puntos = 1;
  if (idioma === "es-mx") puntos += 4;
  else if (idioma === "es-us" || idioma === "es-419") puntos += 3;
  if (/google|natural|neural|online|premium|enhanced|paulina|sabina|dalia|jorge/i.test(voz.name)) puntos += 2;
  if (voz.localService === false) puntos += 1;
  return puntos;
}

function trocear(texto, maximo = 180) {
  const frases = texto.match(/[^.!?¡¿;:]+[.!?;:]*\s*/g) || [texto];
  const trozos = [];
  let actual = "";
  for (const frase of frases) {
    if ((actual + frase).length > maximo && actual) {
      trozos.push(actual.trim());
      actual = "";
    }
    actual += frase;
  }
  if (actual.trim()) trozos.push(actual.trim());
  return trozos;
}

export const voz = {
  soportada: "speechSynthesis" in window, // voz del navegador (respaldo)
  _voz: null,
  _hablando: false,
  // Voz de Gemini: la app conecta aquí una función async (texto) => ArrayBuffer con el audio.
  motorRemoto: null,
  // Si la voz de Gemini falla, ¿usar la del navegador? Ricardo prefiere solo Charon: apagado.
  respaldoNavegador: false,
  ultimoMotor: "",
  ultimoError: "",

  elegir() {
    if (!this.soportada) return null;
    const voces = speechSynthesis.getVoices();
    this._voz = voces
      .map((v) => ({ v, puntos: puntuarVoz(v) }))
      .filter((x) => x.puntos > 0)
      .sort((a, b) => b.puntos - a.puntos)[0]?.v || null;
    return this._voz;
  },

  // iPhone y algunos Android solo dejan hablar si la PRIMERA frase se pide directo dentro de un toque.
  // Se llama al tocar el micrófono, el núcleo o el teclado, para que la respuesta (que llega después) sí suene.
  desbloquear() {
    desbloquearAudio();
    if (!this.soportada || this._desbloqueada) return;
    const silencio = new SpeechSynthesisUtterance(" ");
    silencio.volume = 0;
    silencio.lang = this._voz?.lang || "es-MX";
    speechSynthesis.resume();
    speechSynthesis.speak(silencio);
    this._desbloqueada = true;
  },

  callar() {
    detenerAudio();
    this._hablando = false;
    if (this.soportada) speechSynthesis.cancel();
  },

  // Habla con la voz de Gemini; si no está disponible o falla, usa la voz del navegador.
  // Devuelve true si algo sonó.
  async hablar(texto, opciones = {}) {
    if (!texto) return false;
    this.ultimoError = "";
    if (this.motorRemoto) {
      try {
        const audio = await this.motorRemoto(texto);
        if (audio && await reproducirAudio(audio, opciones)) {
          this.ultimoMotor = "gemini";
          return true;
        }
        this.ultimoError = "el navegador no dejó reproducir el audio";
      } catch (error) {
        this.ultimoError = error.message || "falló la voz de Gemini";
      }
      if (!this.respaldoNavegador) {
        this.ultimoMotor = "";
        return false;
      }
    }
    this.ultimoMotor = "navegador";
    return this.hablarNavegador(texto, opciones);
  },

  nombre() {
    if (!this.soportada) return "sin voz";
    if (!this._voz) this.elegir();
    const total = speechSynthesis.getVoices().length;
    return this._voz ? `${this._voz.name} (${this._voz.lang})` : `predeterminada del sistema, ${total} voces instaladas`;
  },

  // Voz del navegador. Devuelve true si realmente empezó a hablar.
  hablarNavegador(texto, { alNivel, alEmpezar } = {}) {
    return new Promise((resolver) => {
      if (!this.soportada || !texto) return resolver(false);
      // Chrome a veces "pierde" la frase si se habla justo después de cancel(): esperamos un momento.
      const ocupada = speechSynthesis.speaking || speechSynthesis.pending;
      if (ocupada) speechSynthesis.cancel();
      if (!this._voz) this.elegir();
      this._hablando = true;

      const trozos = trocear(texto);
      let indice = 0;
      let pulso = 0;
      let seEscucho = false;
      let terminado = false;
      const animar = () => {
        if (!this._hablando) return alNivel?.(0);
        pulso = Math.max(0.25, pulso * 0.86);
        alNivel?.(pulso + Math.random() * 0.15);
        requestAnimationFrame(animar);
      };

      const terminar = () => {
        if (terminado) return;
        terminado = true;
        this._hablando = false;
        alNivel?.(0);
        resolver(seEscucho);
      };

      // Si a los 3 segundos no ha empezado a sonar, el navegador no está reproduciendo voz.
      setTimeout(() => {
        if (!seEscucho && !speechSynthesis.speaking) {
          speechSynthesis.cancel();
          terminar();
        }
      }, 3000);

      const siguiente = () => {
        if (!this._hablando) return terminar();
        if (indice >= trozos.length) return terminar();
        const frase = new SpeechSynthesisUtterance(trozos[indice++]);
        if (this._voz) frase.voice = this._voz;
        frase.lang = this._voz?.lang || "es-MX";
        frase.rate = 1.03;
        frase.pitch = 0.95;
        frase.volume = 1;
        frase.onstart = () => {
          if (!seEscucho) alEmpezar?.();
          seEscucho = true;
        };
        frase.onboundary = () => { seEscucho = true; pulso = 1; };
        let avanzado = false;
        const avanzar = () => {
          if (avanzado) return;
          avanzado = true;
          clearTimeout(respaldo);
          siguiente();
        };
        // Respaldo: algunos navegadores nunca disparan "onend".
        const respaldo = setTimeout(avanzar, 2500 + frase.text.length * 90);
        frase.onend = avanzar;
        frase.onerror = avanzar;
        speechSynthesis.resume(); // Chrome a veces deja la voz "en pausa" sin avisar
        speechSynthesis.speak(frase);
      };

      requestAnimationFrame(animar);
      // Si no había otra voz sonando, hablamos de inmediato: así, cuando viene de un toque
      // (como "Probar voz"), el teléfono lo cuenta como acción del usuario y sí lo deja sonar.
      if (ocupada) setTimeout(siguiente, 150);
      else {
        this._desbloqueada = true;
        siguiente();
      }
    });
  },
};

if (voz.soportada) {
  voz.elegir();
  speechSynthesis.addEventListener?.("voiceschanged", () => voz.elegir());
}
