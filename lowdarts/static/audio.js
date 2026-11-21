// LowDarts audio: synthesised effects (no third-party samples), custom files,
// soundboard pads and the voice caller (Web Speech, offline Windows voices).
"use strict";

const Audio = (() => {
  let ctx = null, master = null;
  let volume = 0.8;
  const bufferCache = new Map();

  function ac() {
    if (!ctx) {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain();
      master.gain.value = volume;
      master.connect(ctx.destination);
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }
  function setVolume(v) { volume = v; if (master) master.gain.value = v; }

  // ---- building blocks ----------------------------------------------------
  function env(g, t, a, d, peak = 1, end = 0.0001) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + a);
    g.gain.exponentialRampToValueAtTime(end, t + a + d);
  }
  function osc(type, freq, t, dur, peak = 0.3, dest = master) {
    const c = ac(), o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    env(g, t, 0.01, dur, peak);
    o.connect(g).connect(dest); o.start(t); o.stop(t + dur + 0.05);
    return o;
  }
  function noise(t, dur, peak = 0.3, filter = "lowpass", freq = 1200, q = 0.7) {
    const c = ac();
    const len = Math.max(1, Math.floor(c.sampleRate * (dur + 0.1)));
    const buf = c.createBuffer(1, len, c.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    const s = c.createBufferSource(); s.buffer = buf;
    const f = c.createBiquadFilter(); f.type = filter; f.frequency.value = freq; f.Q.value = q;
    const g = c.createGain(); env(g, t, 0.005, dur, peak);
    s.connect(f).connect(g).connect(master); s.start(t); s.stop(t + dur + 0.1);
    return { src: s, filter: f, gain: g };
  }

  // ---- effects --------------------------------------------------------------
  const FX = {
    thunk() { const t = ac().currentTime; noise(t, 0.08, 0.6, "lowpass", 900); osc("sine", 140, t, 0.09, 0.35); },
    tick() { const t = ac().currentTime; osc("square", 1800, t, 0.03, 0.08); },
    miss() { // boing
      const c = ac(), t = c.currentTime, o = c.createOscillator(), g = c.createGain();
      o.type = "sine"; o.frequency.setValueAtTime(620, t); o.frequency.exponentialRampToValueAtTime(90, t + 0.45);
      const lfo = c.createOscillator(), lg = c.createGain(); lfo.frequency.value = 18; lg.gain.value = 40;
      lfo.connect(lg).connect(o.frequency); lfo.start(t); lfo.stop(t + 0.5);
      env(g, t, 0.01, 0.45, 0.35); o.connect(g).connect(master); o.start(t); o.stop(t + 0.5);
    },
    airhorn(len = 1.1) {
      const c = ac(), t = c.currentTime;
      [233, 293, 349, 466].forEach((f, k) => {
        const o = c.createOscillator(), g = c.createGain(), fl = c.createBiquadFilter();
        o.type = "sawtooth"; o.frequency.setValueAtTime(f * 0.94, t); o.frequency.linearRampToValueAtTime(f, t + 0.08);
        fl.type = "lowpass"; fl.frequency.value = 2600;
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.13, t + 0.03);
        g.gain.setValueAtTime(0.13, t + len - 0.1); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
        o.connect(fl).connect(g).connect(master); o.start(t + k * 0.004); o.stop(t + len + 0.05);
      });
    },
    triplehorn() { FX.airhorn(0.25); setTimeout(() => FX.airhorn(0.25), 300); setTimeout(() => FX.airhorn(1.0), 600); },
    cheer(len = 2.2, peak = 0.35) {
      const t = ac().currentTime, n = noise(t, len, peak, "bandpass", 1500, 0.5);
      n.gain.gain.cancelScheduledValues(t);
      n.gain.gain.setValueAtTime(0.0001, t); n.gain.gain.exponentialRampToValueAtTime(peak, t + 0.35);
      n.gain.gain.exponentialRampToValueAtTime(0.0001, t + len);
      for (let k = 0; k < 10; k++) osc("triangle", 900 + Math.random() * 900, t + 0.2 + Math.random() * len * 0.7, 0.18, 0.03);
    },
    applause(len = 2.8) {
      const c = ac(), t = c.currentTime;
      for (let k = 0; k < 90; k++) {
        const tt = t + Math.random() * len, s = noise(tt, 0.04, 0.12 + Math.random() * 0.1, "bandpass", 1800 + Math.random() * 1500, 1.2);
      }
    },
    sadTrombone() {
      const c = ac(), t = c.currentTime;
      [[392, 0], [370, 0.45], [349, 0.9], [330, 1.35]].forEach(([f, dt], k) => {
        const o = c.createOscillator(), g = c.createGain(), fl = c.createBiquadFilter();
        o.type = "sawtooth"; fl.type = "lowpass"; fl.frequency.value = 1100;
        const st = t + dt, dur = k === 3 ? 1.3 : 0.42;
        o.frequency.setValueAtTime(f, st);
        if (k === 3) { const l = c.createOscillator(), lg = c.createGain(); l.frequency.value = 6; lg.gain.value = 9; l.connect(lg).connect(o.frequency); l.start(st); l.stop(st + dur); o.frequency.linearRampToValueAtTime(f * 0.94, st + dur); }
        env(g, st, 0.03, dur, 0.22); o.connect(fl).connect(g).connect(master); o.start(st); o.stop(st + dur + 0.05);
      });
    },
    buzzer() { const t = ac().currentTime; osc("square", 110, t, 0.7, 0.18); osc("square", 116, t, 0.7, 0.18); },
    fanfare() {
      const t = ac().currentTime;
      [[523, 0, .14], [523, .15, .14], [523, .3, .14], [659, .45, .5], [587, .95, .14], [659, 1.1, .14], [784, 1.25, .9]]
        .forEach(([f, dt, d]) => { osc("square", f, t + dt, d, 0.09); osc("triangle", f / 2, t + dt, d, 0.12); });
    },
    drumroll(len = 2.0) {
      const t = ac().currentTime;
      for (let k = 0; k < len * 28; k++) noise(t + k / 28, 0.05, 0.12 + 0.25 * k / (len * 28), "bandpass", 2400, 0.8);
      setTimeout(() => FX.crash(), len * 1000);
    },
    crash() { const t = ac().currentTime; noise(t, 1.4, 0.4, "highpass", 4000); },
    rimshot() {
      const t = ac().currentTime;
      noise(t, 0.08, 0.4, "bandpass", 1800, 3); noise(t + 0.18, 0.08, 0.4, "bandpass", 1800, 3);
      setTimeout(() => noise(ac().currentTime, 0.9, 0.25, "highpass", 6000), 380);
    },
    crickets(len = 2.4) {
      const t = ac().currentTime;
      for (let k = 0; k < len * 3; k++) for (let j = 0; j < 4; j++) osc("sine", 4300, t + k / 3 + j * 0.035, 0.02, 0.05);
    },
    ding() { const t = ac().currentTime; osc("sine", 1568, t, 1.1, 0.25); osc("sine", 2093, t + 0.12, 1.2, 0.18); },
    whoosh() { const t = ac().currentTime, n = noise(t, 0.5, 0.3, "bandpass", 400, 1.5); n.filter.frequency.exponentialRampToValueAtTime(4000, t + 0.45); },
    countdown() { const t = ac().currentTime; [0, 1, 2].forEach(k => osc("sine", 880, t + k, 0.15, 0.25)); osc("sine", 1760, t + 3, 0.5, 0.3); },
    laugh() {
      const t = ac().currentTime;
      for (let k = 0; k < 7; k++) { const o = osc("sawtooth", 260 - k * 8, t + k * 0.16, 0.12, 0.08); }
      noise(t, 1.2, 0.05, "bandpass", 900, 1);
    },
    powerup() { const t = ac().currentTime; [523, 659, 784, 1047, 1319].forEach((f, k) => osc("square", f, t + k * 0.07, 0.12, 0.08)); },
  };

  // ---- custom files ---------------------------------------------------------
  async function playFile(name) {
    const c = ac();
    let buf = bufferCache.get(name);
    if (!buf) {
      const r = await fetch("/sounds/" + encodeURIComponent(name));
      if (!r.ok) return;
      buf = await c.decodeAudioData(await r.arrayBuffer());
      bufferCache.set(name, buf);
    }
    const s = c.createBufferSource(); s.buffer = buf; s.connect(master); s.start();
    return s;
  }

  // ---- event map: game event -> default effect ---------------------------------
  const EVENT_FX = {
    dart: "thunk", miss: "miss", bull: "ding", "180": "triplehorn", ton40: "cheer", ton: "applause",
    bust: "sadTrombone", zero: "crickets", low: "laugh", checkout: "fanfare", leg_won: "applause",
    match_won: "drumroll", closed: "powerup", shanghai: "triplehorn", white_horse: "triplehorn",
    hit: "tick", knocked_out: "buzzer", bed_and_breakfast: "rimshot",
  };
  const EVENT_LABELS = {
    dart: "Dart trifft", miss: "Daneben", bull: "Bullseye", "180": "180!", ton40: "140+", ton: "100+",
    bust: "Bust", zero: "Null Punkte", low: "Unter 20", checkout: "Checkout", leg_won: "Leg gewonnen",
    match_won: "Match gewonnen", closed: "Feld geschlossen (Cricket)", shanghai: "Shanghai",
    white_horse: "White Horse / 9 Marks", hit: "Ziel getroffen (Training)", knocked_out: "Ausgeschieden",
    bed_and_breakfast: "26 (Bed & Breakfast)",
  };
  const PADS = [
    ["airhorn", "Airhorn", "📯"], ["applause", "Applaus", "👏"], ["drumroll", "Trommelwirbel", "🥁"],
    ["sadTrombone", "Sad Trombone", "🎺"], ["buzzer", "Buzzer", "❌"], ["miss", "Boing", "🌀"],
    ["crickets", "Grillen", "🦗"], ["fanfare", "Fanfare", "🏆"], ["rimshot", "Ba-dum-tss", "🥁"],
    ["laugh", "Auslachen", "😂"], ["ding", "Ding", "🔔"], ["countdown", "Countdown", "⏱"],
  ];

  function playEvent(ev, custom) {
    if (custom && custom[ev]) return playFile(custom[ev]);
    const fx = EVENT_FX[ev];
    if (fx && FX[fx]) FX[fx]();
  }

  // ---- caller ---------------------------------------------------------------------
  const Caller = {
    cfg: { enabled: true, lang: "de-DE", voice: "", rate: 1, pitch: 1, volume: 1 },
    voices() { return (window.speechSynthesis ? speechSynthesis.getVoices() : []); },
    say(text, { priority = false } = {}) {
      if (!this.cfg.enabled || !window.speechSynthesis || !text) return;
      if (priority) speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = this.cfg.lang; u.rate = this.cfg.rate; u.pitch = this.cfg.pitch; u.volume = this.cfg.volume;
      const v = this.voices().find(v => v.name === this.cfg.voice) ||
                this.voices().find(v => v.lang && v.lang.startsWith(this.cfg.lang.slice(0, 2)));
      if (v) u.voice = v;
      speechSynthesis.speak(u);
    },
  };

  return { FX, PADS, EVENT_FX, EVENT_LABELS, playEvent, playFile, setVolume, Caller, unlock: ac };
})();
