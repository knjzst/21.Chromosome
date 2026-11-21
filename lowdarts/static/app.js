// LowDarts desktop UI
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SECT = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5];

const S = {
  state: null, settings: null, lastSeq: null, view: "home", sounds: [],
  setup: null, mult: 1, input: "board", correctIdx: null, settingsTab: "cameras",
  winnerShownSeq: null,
};

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.error || "Fehler"); throw new Error(j.error); }
  return j;
}
function toast(msg, ms = 2600) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), ms);
}

// ------------------------------------------------------------------ modes
const LEGS = [1, 2, 3, 4, 5, 6, 7];
const MODES = {
  x01: { title: "X01", glyph: "501", group: "Match", desc: "Der Klassiker: 301, 501 & Co. mit Double-Out, Legs und Sets.", options: [
    { key: "start", label: "Startpunkte", values: [121, 170, 301, 501, 701, 901], def: 501 },
    { key: "in_mode", label: "Check-in", values: [["straight", "Straight"], ["double", "Double"], ["master", "Master"]], def: "straight" },
    { key: "out_mode", label: "Check-out", values: [["straight", "Straight"], ["double", "Double"], ["master", "Master"]], def: "double" },
    { key: "legs", label: "First to … Legs", values: LEGS, def: 1 },
    { key: "sets", label: "First to … Sets", values: [1, 2, 3, 4, 5], def: 1 },
    { key: "max_rounds", label: "Max. Runden", values: [[0, "Aus"], 15, 20, 50, 80], def: 0 },
  ] },
  cricket: { title: "Cricket", glyph: "15–20", group: "Match", desc: "Felder 15–20 und Bull schließen, Punkte sammeln. Mit Tactics und Cut-Throat.", options: [
    { key: "variant", label: "Variante", values: [["cricket", "Cricket 15–20"], ["tactics", "Tactics 10–20"]], def: "cricket" },
    { key: "scoring", label: "Punkte", values: [["standard", "Standard"], ["cutthroat", "Cut-Throat"], ["noscore", "Ohne Punkte"]], def: "standard" },
    { key: "max_rounds", label: "Max. Runden", values: [15, 20, 50, 80], def: 20 },
  ] },
  atc: { title: "Around the Clock", glyph: "1→20", group: "Training", desc: "Von 1 bis 20 und Bull – so schnell wie möglich.", options: [
    { key: "ring", label: "Zählt", values: [["any", "Ganzes Feld"], ["single", "Nur Single"], ["double", "Nur Double"], ["triple", "Nur Triple"]], def: "any" },
    { key: "order", label: "Reihenfolge", values: [["up", "1 → 20"], ["down", "20 → 1"], ["random", "Zufällig"]], def: "up" },
    { key: "hits_needed", label: "Treffer pro Feld", values: [1, 2, 3], def: 1 },
  ] },
  bobs27: { title: "Bob's 27", glyph: "D", group: "Training", desc: "Doppel-Training: Start mit 27, jedes Doppel bringt Punkte, Fehlrunden kosten.", options: [
    { key: "allow_negative", label: "Unter Null weiterspielen", values: [[false, "Nein"], [true, "Ja"]], def: false },
  ] },
  countup: { title: "Count Up", glyph: "Σ", group: "Training", desc: "Möglichst viele Punkte in festen Runden – ideal zum Scoring-Training.", options: [
    { key: "rounds", label: "Runden", values: [7, 8, 10, 15], def: 8 },
  ] },
  shanghai: { title: "Shanghai", glyph: "S·D·T", group: "Party", desc: "Runde für Runde ein neues Ziel. Single, Double und Triple in einer Aufnahme = Sofortsieg.", options: [
    { key: "rounds", label: "Runden", values: [[7, "1–7"], [20, "1–20"]], def: 7 },
  ] },
};

// ------------------------------------------------------------------ routing
function go(view) { location.hash = view; }
function route() {
  const h = location.hash.slice(1) || "home";
  const [view, arg] = h.split("-");
  S.view = view;
  $$("nav.top a").forEach(a => a.classList.toggle("on", a.dataset.nav === view || (view === "setup" && a.dataset.nav === "home")));
  if (view === "setup") renderSetup(arg);
  else if (view === "match") renderMatch();
  else if (view === "stats") renderStats();
  else if (view === "settings") renderSettings();
  else renderHome();
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ home
function renderHome() {
  const groups = { Match: "Matches", Training: "Training", Party: "Party" };
  let html = `<section class="screen"><div class="hero"><div><h1>Bereit für die <em>Oche</em>?</h1>
    <p class="sub">Wähle einen Spielmodus. Kamera-Erkennung, virtuelles Board oder Tastenfeld – alles geht.</p></div>
    ${S.state && S.state.players && !S.state.winner && S.state.players.some(p => p.darts) ? `<button class="btn primary big" onclick="go('match')">Laufendes Match fortsetzen ▸</button>` : ""}</div>`;
  for (const [g, label] of Object.entries(groups)) {
    html += `<div class="group"><h3>${label}</h3><div class="tiles">`;
    for (const [k, m] of Object.entries(MODES)) if (m.group === g)
      html += `<button class="tile" onclick="go('setup-${k}')"><span class="glyph">${esc(m.glyph)}</span><span class="t">${esc(m.title)}</span><span class="d">${esc(m.desc)}</span></button>`;
    html += `</div></div>`;
  }
  $("#main").innerHTML = html + `</section>`;
}

// ------------------------------------------------------------------ setup
function renderSetup(mode) {
  const m = MODES[mode] || MODES.x01;
  mode = MODES[mode] ? mode : "x01";
  if (!S.setup || S.setup.mode !== mode) {
    const opts = {};
    m.options.forEach(o => opts[o.key] = o.def);
    const prev = S.state && S.state.config && S.state.config.mode === mode ? S.state.config.options : {};
    const names = (S.settings && S.settings.players) || ["Spieler 1", "Spieler 2"];
    const players = (S.state && S.state.config && S.state.config.players) || names.map(n => ({ name: n, bot: 0 }));
    S.setup = { mode, options: { ...opts, ...prev }, players: players.map(p => ({ ...p })) };
  }
  const su = S.setup;
  const optHtml = m.options.map(o => `<div class="opt"><span>${esc(o.label)}</span><div class="seg">${
    o.values.map(v => { const [val, lab] = Array.isArray(v) ? v : [v, v];
      return `<button class="${su.options[o.key] === val ? "on" : ""}" data-k="${o.key}" data-v='${JSON.stringify(val)}'>${esc(lab)}</button>`; }).join("")}</div></div>`).join("");
  const botOpts = lvl => `<option value="0" ${!lvl ? "selected" : ""}>Mensch</option>` +
    Array.from({ length: 11 }, (_, i) => `<option value="${i + 1}" ${+lvl === i + 1 ? "selected" : ""}>Bot ${i + 1} (Ø ~${(i + 2) * 10})</option>`).join("");
  $("#main").innerHTML = `<section class="screen">
    <div class="hero"><div><h3>Neues Spiel</h3><h1>${esc(m.title)}</h1><p class="sub">${esc(m.desc)}</p></div>
    <button class="btn primary big" id="start">Spiel starten ▸</button></div>
    <div class="setup">
      <div class="card"><h3>Spieler</h3><div id="plist" class="rows">${su.players.map((p, i) => `
        <div class="prow"><span class="num">${i + 1}</span>
          <input type="text" id="pn${i}" value="${esc(p.name)}" data-i="${i}" maxlength="24" aria-label="Name Spieler ${i + 1}">
          <select data-i="${i}" id="pb${i}" aria-label="Typ Spieler ${i + 1}">${botOpts(p.bot)}</select>
          <button class="btn ghost danger" data-del="${i}" title="Entfernen" ${su.players.length < 2 ? "disabled" : ""}>✕</button></div>`).join("")}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="addp" ${su.players.length >= 8 ? "disabled" : ""}>+ Spieler</button>
        <button class="btn" id="addbot" ${su.players.length >= 8 ? "disabled" : ""}>+ Computer-Gegner</button>
        <button class="btn ghost" id="shuffle">🔀 Reihenfolge mischen</button></div></div>
      <div class="card"><h3>Optionen</h3><div class="opts">${optHtml || '<p class="sub">Keine Optionen.</p>'}</div></div>
    </div></section>`;
  $$(".seg button").forEach(b => b.onclick = () => { su.options[b.dataset.k] = JSON.parse(b.dataset.v); renderSetup(mode); });
  $$("#plist input").forEach(inp => inp.oninput = () => su.players[+inp.dataset.i].name = inp.value);
  $$("#plist select").forEach(sel => sel.onchange = () => {
    const p = su.players[+sel.dataset.i]; p.bot = +sel.value;
    if (p.bot && !/^Bot/.test(p.name)) p.name = `Bot ${p.bot}`;
    renderSetup(mode);
  });
  $$("[data-del]").forEach(b => b.onclick = () => { su.players.splice(+b.dataset.del, 1); renderSetup(mode); });
  $("#addp").onclick = () => { su.players.push({ name: `Spieler ${su.players.length + 1}`, bot: 0 }); renderSetup(mode); };
  $("#addbot").onclick = () => { su.players.push({ name: "Bot 5", bot: 5 }); renderSetup(mode); };
  $("#shuffle").onclick = () => { su.players.sort(() => Math.random() - .5); renderSetup(mode); };
  $("#start").onclick = async () => {
    Audio.unlock();
    await api("/api/new_game", { mode, options: su.options, players: su.players });
    go("match");
  };
}

// ------------------------------------------------------------------ board svg
function boardSvg(interactive) {
  const pt = (r, a) => [r * Math.cos(a), -r * Math.sin(a)];
  const seg = (r1, r2, a0, a1, c, label) => {
    const [x1, y1] = pt(r2, a0), [x2, y2] = pt(r2, a1), [x3, y3] = pt(r1, a1), [x4, y4] = pt(r1, a0);
    return `<path class="${interactive ? "seg-hover" : ""}" data-l="${label}" d="M${x1} ${y1}A${r2} ${r2} 0 0 0 ${x2} ${y2}L${x3} ${y3}A${r1} ${r1} 0 0 1 ${x4} ${y4}Z" fill="${c}"/>`;
  };
  let h = `<circle r="198" fill="#0a0d14"/><circle r="172" fill="#c9ccd3" opacity=".25"/>`;
  for (let k = 0; k < 20; k++) {
    const c = (90 - k * 18) * Math.PI / 180, a0 = c - Math.PI / 20, a1 = c + Math.PI / 20, e = k % 2 === 0, n = SECT[k];
    const dk = e ? "var(--board-black)" : "var(--board-cream)", rg = e ? "var(--board-red)" : "var(--board-green)";
    h += seg(15.9, 99, a0, a1, dk, "S" + n) + seg(99, 107, a0, a1, rg, "T" + n) + seg(107, 162, a0, a1, dk, "S" + n) + seg(162, 170, a0, a1, rg, "D" + n);
    const [tx, ty] = pt(185, c);
    h += `<text x="${tx}" y="${ty + 6}" font-size="17" font-family="Bahnschrift, sans-serif" font-weight="700" fill="#c3cad8" text-anchor="middle">${n}</text>`;
  }
  h += `<circle class="${interactive ? "seg-hover" : ""}" data-l="25" r="15.9" fill="var(--board-green)"/><circle class="${interactive ? "seg-hover" : ""}" data-l="BULL" r="6.35" fill="var(--board-red)"/>`;
  h += `<g fill="none" stroke="#9aa3b2" stroke-width=".6" opacity=".7">${[6.35, 15.9, 99, 107, 162, 170].map(r => `<circle r="${r}"/>`).join("")}</g><g id="hits"></g>`;
  return `<svg id="board" viewBox="-200 -200 400 400" role="img" aria-label="Dartboard">${h}</svg>`;
}
function labelPos(d) {
  if (d.x || d.y) return [d.x, d.y];
  if (d.multiplier === 0) return null;
  if (d.sector === 25) return d.multiplier === 2 ? [0, 0] : [0, 11];
  const r = { 1: 134, 2: 166, 3: 103 }[d.multiplier], a = (90 - SECT.indexOf(d.sector) * 18) * Math.PI / 180;
  return [r * Math.cos(a), r * Math.sin(a)];
}

// ------------------------------------------------------------------ match
function renderMatch() {
  const s = S.state;
  if (!s) { $("#main").innerHTML = ""; return; }
  const isX = s.mode === "x01";
  const cur = s.players[s.current];
  const legsDots = (n, w) => `<span class="legs">${Array.from({ length: n }, (_, i) => `<i class="${i < w ? "w" : ""}"></i>`).join("")}</span>`;
  const cards = s.players.map((p, i) => {
    let body = "";
    if (isX) body = `<div class="sc">${p.score}</div><div class="co">${esc(i === s.current ? p.checkout : p.checkout ? p.checkout : "")}</div>
        <div class="meta"><span>Ø ${p.avg.toFixed(1)}</span><span>F9 ${p.first9.toFixed(1)}</span><span>${p.darts} Darts</span>
        ${s.legs_to_win > 1 || s.sets_to_win > 1 ? legsDots(s.legs_to_win, p.legs) : ""}${s.sets_to_win > 1 ? ` Sets ${p.sets}` : ""}</div>`;
    else if (s.mode === "cricket") body = `<div class="sc">${p.score}</div><div class="meta"><span>MPR ${p.mpr.toFixed(2)}</span><span>${p.darts} Darts</span></div>`;
    else if (s.mode === "atc") body = `<div class="sc">${p.target === 25 ? "Bull" : p.target ?? "✓"}</div><div class="bar"><i style="width:${100 * p.progress / p.total}%"></i></div>
        <div class="meta"><span>${p.progress}/${p.total}</span><span>Quote ${p.hit_rate}%</span></div>`;
    else body = `<div class="sc">${p.score}</div><div class="meta"><span>${p.darts} Darts</span>${p.avg !== undefined ? `<span>Ø ${p.avg}</span>` : ""}${p.out ? "<span>ausgeschieden</span>" : ""}</div>`;
    const bot = s.bots[String(i)];
    return `<div class="pc ${i === s.current ? "cur" : ""} ${p.out ? "out" : ""}"><div class="nm"><span>${esc(p.name)}</span><small>${bot ? `🤖 ${bot}` : ""}</small></div>${body}</div>`;
  }).join("");

  const darts = [0, 1, 2].map(k => { const d = s.turn[k];
    return d ? `<div class="dart filled" data-k="${k}" title="Korrigieren"><b>${esc(d.label)}</b><small>${d.score}</small></div>` : `<div class="dart empty"><b>·</b><small>&nbsp;</small></div>`; }).join("");
  const turnSum = s.turn.reduce((a, d) => a + d.score, 0);
  let totalLabel = "Aufnahme", totalVal = isX ? s.turn_total : turnSum;
  if (s.bust) { totalLabel = "Überworfen"; totalVal = "BUST"; }
  let target = "";
  if (s.mode === "bobs27") target = `Ziel: ${s.target_label}`;
  else if (s.mode === "shanghai") target = `Ziel: ${s.target}`;
  else if (s.mode === "atc" && cur.target) target = `Ziel: ${cur.target === 25 ? "Bull" : cur.target}`;

  const mid = s.mode === "cricket" ? cricketTable(s) : "";
  const keypad = `<div class="keypad">
      ${[["1", "Single"], ["2", "Double"], ["3", "Triple"]].map(([m, l]) => `<button class="mod ${S.mult == m ? "on" : ""}" data-m="${m}">${l}</button>`).join("")}
      <button data-l="MISS">Miss</button>
      ${Array.from({ length: 20 }, (_, i) => `<button data-n="${i + 1}">${i + 1}</button>`).join("")}
      <button data-l="25" class="wide">25</button><button data-l="BULL" class="wide">Bull</button><button data-l="MISS" class="wide">0</button></div>`;
  const roundInfo = s.max_rounds ? `Runde ${s.round}/${s.max_rounds}` : `Runde ${s.round}`;
  $("#main").innerHTML = `<section class="screen match">
    <div class="mbar"><span class="title">${esc(s.title)}</span>
      ${isX ? `<span>${s.in_mode === "straight" ? "SI" : s.in_mode === "double" ? "DI" : "MI"}-${s.out_mode === "straight" ? "SO" : s.out_mode === "double" ? "DO" : "MO"}</span>
        ${s.legs_to_win > 1 ? `<span>First to ${s.legs_to_win} Legs</span>` : ""}${s.sets_to_win > 1 ? `<span>First to ${s.sets_to_win} Sets</span>` : ""}` : ""}
      <span>${roundInfo}</span>${target ? `<span class="pill wait">${esc(target)}</span>` : ""}<span class="status">${esc(s.status || "")}</span></div>
    <div class="players">${cards}</div>
    <div class="arena">
      <div class="boardwrap">${mid || boardSvg(true)}</div>
      <div class="side">
        <div class="turn">${darts}</div>
        <div class="total ${s.bust ? "bust" : ""}"><span class="sub">${totalLabel}</span><span class="v">${totalVal}</span></div>
        <div class="card" style="padding:12px"><div class="seg" style="justify-content:space-between">
          <span class="sub">${S.correctIdx !== null ? `Dart ${S.correctIdx + 1} korrigieren:` : "Eingabe"}</span>
          ${s.mode === "cricket" ? "" : `<div class="seg"><button class="${S.input === "board" ? "on" : ""}" data-in="board">Board</button><button class="${S.input === "keys" ? "on" : ""}" data-in="keys">Tastenfeld</button></div>`}</div>
          ${S.input === "keys" || s.mode === "cricket" || S.correctIdx !== null ? keypad : '<p class="sub" style="margin:0">Klick aufs Board trägt den Dart genau dort ein. Mit Kameras läuft alles automatisch.</p>'}</div>
      </div>
    </div>
    <div class="toolbar">
      <button class="btn" id="undo" title="Rückgängig (Backspace)">↶ Rückgängig</button>
      <button class="btn primary" id="next" title="Weiter (Enter)">Nächster Spieler ▸</button>
      ${S.correctIdx !== null ? `<button class="btn" id="cancel-correct">Korrektur abbrechen</button>` : ""}
      <span class="spacer"></span>
      ${s.cameras ? `<button class="btn ghost" id="rearm" title="Referenzbild neu setzen">⟲ Kamera-Reset</button>` : ""}
      <button class="btn ghost" onclick="go('setup-${s.mode}')">Neues Spiel</button>
    </div></section>`;

  drawHits();
  const svg = $("#board");
  if (svg) svg.addEventListener("click", e => {
    if (S.correctIdx !== null) return;
    const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse());
    Audio.unlock();
    api("/api/throw", { x: q.x, y: -q.y });
  });
  $$(".keypad .mod").forEach(b => b.onclick = () => { S.mult = +b.dataset.m; renderMatch(); });
  $$(".keypad [data-n]").forEach(b => b.onclick = () => keyThrow(["", "S", "D", "T"][S.mult] + b.dataset.n));
  $$(".keypad [data-l]").forEach(b => b.onclick = () => keyThrow(b.dataset.l));
  $$("[data-in]").forEach(b => b.onclick = () => { S.input = b.dataset.in; renderMatch(); });
  $$(".dart.filled").forEach(d => d.onclick = () => { S.correctIdx = +d.dataset.k; renderMatch(); });
  $("#undo").onclick = () => api("/api/undo", {});
  $("#next").onclick = () => api("/api/next", {});
  const cc = $("#cancel-correct"); if (cc) cc.onclick = () => { S.correctIdx = null; renderMatch(); };
  const ra = $("#rearm"); if (ra) ra.onclick = () => api("/api/rearm", {}).then(() => toast("Kamera-Referenz neu gesetzt"));
  showWinner();
}
function keyThrow(label) {
  Audio.unlock();
  if (S.correctIdx !== null) {
    const idx = S.correctIdx; S.correctIdx = null;
    api("/api/correct", { index: idx, label });
  } else api("/api/throw", { label });
  S.mult = 1;
}
function cricketTable(s) {
  const marks = m => m >= 3 ? "Ⓧ" : m === 2 ? "✕" : m === 1 ? "╱" : "";
  return `<table class="cricket"><thead><tr>${s.players.map((p, i) => `<th style="color:${i === s.current ? "var(--brass)" : "inherit"}">${esc(p.name)}</th>`).join("")}<th></th></tr></thead><tbody>
    ${s.targets.slice().reverse().map(t => `<tr>${s.players.map(p => `<td class="mk">${marks(p.marks[String(t)])}</td>`).join("")}<td class="t ${s.open_targets.includes(t) ? "" : "dead"}">${t === 25 ? "B" : t}</td></tr>`).join("")}
    </tbody></table>`;
}
function drawHits() {
  const g = $("#hits"); if (!g || !S.state) return;
  g.innerHTML = S.state.turn.map((d, n) => { const p = labelPos(d); if (!p) return "";
    const [x, y] = p;
    return `<circle cx="${x}" cy="${-y}" r="7" fill="var(--sky)" stroke="#0b1020" stroke-width="2.5"/><text x="${x + 10}" y="${-y - 9}" font-size="15" font-weight="700" fill="#fff" stroke="#0b1020" stroke-width="3" paint-order="stroke">${n + 1}</text>`; }).join("");
}
function showWinner() {
  const s = S.state; const old = $(".win");
  if (s.winner === null || s.winner === undefined) { if (old) old.remove(); return; }
  if (old) return;
  const p = s.players[s.winner];
  const stat = s.mode === "x01" ? [["Ø 3 Darts", p.avg.toFixed(1)], ["First 9", p.first9.toFixed(1)], ["Checkout %", p.checkout_pct], ["Bestes Finish", p.best_finish], ["Höchste Aufnahme", p.high], ["180er", p.tons["180"]]]
    : s.mode === "cricket" ? [["Punkte", p.score], ["MPR", p.mpr]] : [["Punkte", p.score ?? p.progress], ["Darts", p.darts]];
  const w = document.createElement("div"); w.className = "win";
  w.innerHTML = `<div class="box"><h3>Gewinner</h3><h2>${esc(p.name)}</h2><div class="statgrid">${stat.map(([k, v]) => `<div><b>${esc(v)}</b><span>${k}</span></div>`).join("")}</div>
    <div class="toolbar"><button class="btn primary big" id="rematch">Revanche</button><button class="btn" id="w-new">Neues Spiel</button><button class="btn ghost" id="w-undo">Letzten Dart zurück</button></div></div>`;
  document.body.appendChild(w);
  $("#rematch").onclick = () => { w.remove(); api("/api/rematch", {}); };
  $("#w-new").onclick = () => { w.remove(); go("setup-" + s.mode); };
  $("#w-undo").onclick = () => { w.remove(); api("/api/undo", {}); };
}

// ------------------------------------------------------------------ events: sound, caller, banners
const PRIORITY = ["match_won", "leg_won", "checkout", "180", "shanghai", "white_horse", "nine_marks", "bust", "ton40", "ton", "knocked_out", "zero", "low", "bed_and_breakfast", "closed", "bull", "hit", "miss", "dart"];
function handleEvents(prev, s) {
  const ev = s.events || [];
  const st = S.settings || {};
  const custom = (st.sounds && st.sounds.events) || {};
  const soundsOn = !st.sounds || st.sounds.enabled;
  if (ev.includes("game_start")) {
    const name = s.players[s.current].name, walk = st.walkon && st.walkon[name];
    if (walk && soundsOn) Audio.playFile(walk);
    Audio.Caller.say(`Game on! ${name}, du beginnst.`, { priority: true });
    return;
  }
  if (ev.includes("undo") || ev.includes("correct")) return;
  const main = PRIORITY.find(e => ev.includes(e));
  if (soundsOn && main) {
    if (ev.includes("dart") && main !== "miss" && main !== "dart" && main !== "hit") Audio.playEvent("dart", custom);
    Audio.playEvent(main, custom);
  }
  // banners
  const anim = st.animations !== false;
  if (anim) {
    if (ev.includes("match_won")) { banner("SIEG!", "good", s.players[s.winner].name); confetti(); }
    else if (ev.includes("leg_won")) { banner("GAME SHOT", "good", `Leg an ${s.players[s.current].name}`); confetti(1200); }
    else if (ev.includes("180")) banner("180", "", "ONE HUNDRED AND EIGHTY");
    else if (ev.includes("shanghai")) banner("SHANGHAI!", "good");
    else if (ev.includes("white_horse") || ev.includes("nine_marks")) banner("9 MARKS", "good");
    else if (ev.includes("bust")) banner("BUST", "bad");
    else if (ev.includes("ton40") || ev.includes("ton")) banner(String(s.mode === "x01" ? s.turn_total : ""), "");
  }
  caller(prev, s, ev);
}
function caller(prev, s, ev) {
  const C = Audio.Caller, st = S.settings || {};
  if (ev.includes("bust")) return C.say("Überworfen!", { priority: true });
  if (ev.includes("match_won")) return C.say(`Game shot, and the match! ${s.players[s.winner].name}!`, { priority: true });
  if (ev.includes("leg_won")) return C.say(`Game shot! Leg an ${s.players[s.current].name}.`, { priority: true });
  if (ev.includes("leg_start")) return C.say(`${s.players[s.current].name}, du beginnst das Leg.`);
  if (s.mode === "x01" && s.turn_done && s.turn.length === 3 && ev.includes("dart")) {
    const t = s.turn_total;
    return C.say(t === 180 ? "Einhundertachtzig!" : t === 0 ? "Kein Score" : String(t), { priority: true });
  }
  if (s.mode === "cricket" && s.turn_done && ev.includes("dart")) {
    const marks = s.turn.reduce((a, d) => a + (s.targets.includes(d.sector) ? d.multiplier : 0), 0);
    if (marks) return C.say(`${marks} Marks`);
  }
  if (ev.includes("next") || (prev && prev.current !== s.current)) {
    const p = s.players[s.current];
    if (s.mode === "x01" && (st.caller || {}).call_checkout !== false && p.checkout) return C.say(`${p.name}, du brauchst ${p.score}`);
    if (s.mode === "x01") return C.say(`${p.name}, ${p.score}`);
    if (s.mode === "atc" && p.target) return C.say(`${p.name}, ${p.target === 25 ? "Bull" : p.target}`);
    return C.say(p.name);
  }
}
function banner(text, cls, small = "") {
  $$(".banner").forEach(b => b.remove());
  const b = document.createElement("div"); b.className = "banner " + cls;
  b.innerHTML = `<span>${esc(text)}${small ? `<small>${esc(small)}</small>` : ""}</span>`;
  document.body.appendChild(b); setTimeout(() => b.remove(), 1800);
}
function confetti(ms = 3000) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const c = $("#confetti"), x = c.getContext("2d");
  c.width = innerWidth; c.height = innerHeight;
  const cols = ["#f2b13c", "#34d89a", "#59c2ff", "#ff5d4f", "#eef1f6"];
  const P = Array.from({ length: 160 }, () => ({ x: Math.random() * c.width, y: -20 - Math.random() * c.height * .5, vx: (Math.random() - .5) * 4, vy: 2 + Math.random() * 4, r: Math.random() * 6.28, s: 5 + Math.random() * 6, c: cols[Math.floor(Math.random() * cols.length)] }));
  const end = performance.now() + ms;
  (function f(t) {
    x.clearRect(0, 0, c.width, c.height);
    P.forEach(p => { p.x += p.vx; p.y += p.vy; p.vy += .05; p.r += .1; x.save(); x.translate(p.x, p.y); x.rotate(p.r); x.fillStyle = p.c; x.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2); x.restore(); });
    if (t < end) requestAnimationFrame(f); else x.clearRect(0, 0, c.width, c.height);
  })(performance.now());
}

// ------------------------------------------------------------------ soundboard
const PAD_KEYS = "1234567890QWERTZUIOP";
function renderSoundboard() {
  const st = S.settings || {};
  const pads = Audio.PADS.map(([fx, name, e]) => ({ fx, name, e })).concat((st.pads || []).map(p => ({ file: p.file, name: p.name, e: "🎵" })));
  const d = $("#soundboard");
  d.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><h3>Soundboard</h3>
      <button class="btn ghost" onclick="toggleSoundboard(false)" aria-label="Schließen">✕</button></div>
    <div class="pads">${pads.map((p, i) => `<button class="pad" data-i="${i}">${i < PAD_KEYS.length ? `<kbd>${PAD_KEYS[i]}</kbd>` : ""}<span class="e">${p.e}</span>${esc(p.name)}</button>`).join("")}</div>
    <p class="note" style="margin:0">Eigene Sounds hinzufügen: Einstellungen → Soundboard. Tasten ${PAD_KEYS.slice(0, 10)} spielen die Pads, solange das Soundboard offen ist.</p>`;
  d._pads = pads;
  $$(".pad", d).forEach(b => b.onclick = () => playPad(+b.dataset.i));
}
function playPad(i) {
  const p = $("#soundboard")._pads[i]; if (!p) return;
  Audio.unlock();
  if (p.file) Audio.playFile(p.file); else Audio.FX[p.fx]();
  const b = $(`.pad[data-i="${i}"]`); if (b) { b.classList.add("hit"); setTimeout(() => b.classList.remove("hit"), 150); }
}
function toggleSoundboard(force) {
  const d = $("#soundboard"), show = force ?? d.classList.contains("hidden");
  if (show) renderSoundboard();
  d.classList.toggle("hidden", !show);
}
$("#sb-toggle").onclick = () => toggleSoundboard();

document.addEventListener("keydown", e => {
  if (e.target.matches("input, select, textarea")) return;
  const sbOpen = !$("#soundboard").classList.contains("hidden");
  if (sbOpen) { const i = PAD_KEYS.indexOf(e.key.toUpperCase()); if (i >= 0) { playPad(i); e.preventDefault(); return; } }
  if (e.key === "s" || e.key === "S") { toggleSoundboard(); return; }
  if (S.view !== "match") return;
  if (e.key === "Backspace") { api("/api/undo", {}); e.preventDefault(); }
  else if (e.key === "Enter") { api("/api/next", {}); e.preventDefault(); }
  else if (e.key === "Escape" && S.correctIdx !== null) { S.correctIdx = null; renderMatch(); }
});

// ------------------------------------------------------------------ stats
async function renderStats() {
  const rows = await api("/api/matches");
  const per = {};
  rows.forEach(m => m.players.forEach((p, i) => {
    if (m.bots && m.bots[String(i)]) return;
    const a = per[p.name] = per[p.name] || { games: 0, wins: 0, x01: 0, avgSum: 0, best: 0, f180: 0, high: 0 };
    a.games++; if (m.winner === p.name) a.wins++;
    if (m.mode === "x01" && p.darts) { a.x01++; a.avgSum += p.avg; a.best = Math.max(a.best, p.best_finish || 0); a.f180 += (p.tons || {})["180"] || 0; a.high = Math.max(a.high, p.high || 0); }
  }));
  const ps = Object.entries(per).sort((a, b) => b[1].games - a[1].games);
  $("#main").innerHTML = `<section class="screen"><div class="hero"><div><h3>Statistik</h3><h1>Spieler & Matches</h1>
    <p class="sub">Alles wird lokal auf diesem PC gespeichert.</p></div></div>
    <div class="card"><h3>Spieler</h3><div class="scroll-x"><table class="list"><thead><tr><th>Spieler</th><th>Matches</th><th>Siege</th><th>Ø X01</th><th>Höchste Aufnahme</th><th>Bestes Finish</th><th>180er</th></tr></thead><tbody>
    ${ps.map(([n, a]) => `<tr><td>${esc(n)}</td><td>${a.games}</td><td>${a.wins}</td><td>${a.x01 ? (a.avgSum / a.x01).toFixed(1) : "–"}</td><td>${a.high || "–"}</td><td>${a.best || "–"}</td><td>${a.f180}</td></tr>`).join("") || `<tr><td colspan="7" class="sub">Noch keine Matches gespielt.</td></tr>`}
    </tbody></table></div></div>
    <div class="card" style="margin-top:14px"><h3>Letzte Matches</h3><div class="scroll-x"><table class="list"><thead><tr><th>Datum</th><th>Modus</th><th>Spieler</th><th>Sieger</th></tr></thead><tbody>
    ${rows.slice(0, 60).map(m => `<tr><td>${esc(m.ts)}</td><td>${esc(m.title)}</td><td>${m.players.map(p => esc(p.name) + (p.avg !== undefined ? ` <span class="sub">(Ø ${p.avg})</span>` : "")).join(", ")}</td><td>${esc(m.winner || "–")}</td></tr>`).join("") || `<tr><td colspan="4" class="sub">–</td></tr>`}
    </tbody></table></div></div></section>`;
}

// ------------------------------------------------------------------ settings
async function saveSettings(patch) {
  S.settings = await api("/api/settings", patch);
  applySettings();
}
function applySettings() {
  const st = S.settings; if (!st) return;
  Audio.setVolume(st.sounds.enabled ? st.sounds.volume : 0);
  Object.assign(Audio.Caller.cfg, st.caller);
}
async function uploadFile(file) {
  const r = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
  const j = await r.json();
  if (!r.ok) { toast(j.error || "Upload fehlgeschlagen"); throw new Error(j.error); }
  S.sounds = await api("/api/sounds");
  return j.file;
}
function fileSelect(id, current, withDefault = "Standard") {
  return `<select id="${id}"><option value="">${withDefault}</option>${S.sounds.map(f => `<option ${f === current ? "selected" : ""}>${esc(f)}</option>`).join("")}</select>`;
}
async function renderSettings() {
  S.settings = await api("/api/settings");
  S.sounds = await api("/api/sounds");
  const tab = S.settingsTab, st = S.settings;
  const tabs = [["cameras", "Kameras"], ["sound", "Sounds"], ["caller", "Sprecher"], ["pads", "Soundboard"], ["players", "Einlaufmusik"], ["display", "Anzeige"]];
  let body = "";
  if (tab === "cameras") body = await camerasTab();
  if (tab === "sound") body = `<div class="card"><div class="rows">
      <div class="row"><span>Soundeffekte</span><label class="chk"><input type="checkbox" id="s-on" ${st.sounds.enabled ? "checked" : ""}> an</label></div>
      <div class="row"><span>Lautstärke</span><input type="range" id="s-vol" min="0" max="1" step="0.05" value="${st.sounds.volume}"></div>
      <div class="row"><span>Eigene Datei hochladen</span><input type="file" id="s-up" accept="audio/*"></div></div></div>
    <div class="card" style="margin-top:12px"><h3>Sound pro Ereignis</h3><p class="note" style="margin:0">„Standard“ nutzt die eingebauten Effekte (Airhorn bei 180, Sad Trombone beim Bust, Grillen bei 0 Punkten …). Oder wähle eine eigene Datei.</p>
      <div class="rows">${Object.entries(Audio.EVENT_LABELS).map(([k, l]) => `<div class="row"><span>${esc(l)}</span>${fileSelect("ev-" + k, st.sounds.events[k])}<button class="btn ghost" data-test="${k}">▶</button></div>`).join("")}</div></div>`;
  if (tab === "caller") {
    const voices = Audio.Caller.voices();
    body = `<div class="card"><div class="rows">
      <div class="row"><span>Sprecher (Caller)</span><label class="chk"><input type="checkbox" id="c-on" ${st.caller.enabled ? "checked" : ""}> an</label></div>
      <div class="row"><span>Sprache</span><select id="c-lang"><option value="de-DE" ${st.caller.lang === "de-DE" ? "selected" : ""}>Deutsch</option><option value="en-GB" ${st.caller.lang === "en-GB" ? "selected" : ""}>Englisch</option></select></div>
      <div class="row"><span>Stimme</span><select id="c-voice"><option value="">Automatisch</option>${voices.map(v => `<option ${v.name === st.caller.voice ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></div>
      <div class="row"><span>Tempo</span><input type="range" id="c-rate" min="0.6" max="1.6" step="0.05" value="${st.caller.rate}"></div>
      <div class="row"><span>Tonhöhe</span><input type="range" id="c-pitch" min="0.5" max="1.5" step="0.05" value="${st.caller.pitch}"></div>
      <div class="row"><span>Restpunkte ansagen („du brauchst 40“)</span><label class="chk"><input type="checkbox" id="c-co" ${st.caller.call_checkout ? "checked" : ""}> an</label></div>
      <div class="row"><span>Test</span><button class="btn" id="c-test">▶ „Einhundertachtzig!“</button></div></div>
      <p class="note">Die Stimmen kommen von Windows (offline). Weitere deutsche Stimmen: Windows-Einstellungen → Zeit und Sprache → Sprache → Deutsch → Sprachausgabe.</p></div>`;
  }
  if (tab === "pads") body = `<div class="card"><h3>Eigene Pads</h3><div class="rows">${(st.pads || []).map((p, i) => `<div class="row"><span>${esc(p.name)} <span class="sub">(${esc(p.file)})</span></span><button class="btn ghost" data-play="${esc(p.file)}">▶</button><button class="btn ghost danger" data-delpad="${i}">✕</button></div>`).join("") || '<p class="sub">Noch keine eigenen Pads.</p>'}</div>
      <div class="row"><input type="text" id="pad-name" placeholder="Name, z. B. „Jubel Ben“" maxlength="20"><input type="file" id="pad-file" accept="audio/*"><button class="btn primary" id="pad-add">Pad hinzufügen</button></div>
      <p class="note">Die 12 eingebauten Pads (Airhorn, Applaus, Trommelwirbel, Sad Trombone, Grillen …) sind immer da. Soundboard öffnen: Taste S oder 🔊 oben rechts.</p></div>`;
  if (tab === "players") {
    const names = [...new Set([...(st.players || []), ...Object.keys(st.walkon || {})])];
    body = `<div class="card"><h3>Einlaufmusik</h3><p class="note" style="margin:0">Läuft beim Spielstart für den Spieler, der beginnt.</p><div class="rows">
      ${names.map((n, i) => `<div class="row"><span>${esc(n)}</span>${fileSelect("wk-" + i, (st.walkon || {})[n], "Keine")}<button class="btn ghost" data-wkplay="${i}">▶</button></div>`).join("")}</div>
      <div class="row"><span>Musik hochladen</span><input type="file" id="wk-up" accept="audio/*"></div></div>`;
    S._walkNames = names;
  }
  if (tab === "display") body = `<div class="card"><div class="rows">
      <div class="row"><span>Animationen (180, Bust, Konfetti)</span><label class="chk"><input type="checkbox" id="d-anim" ${st.animations !== false ? "checked" : ""}> an</label></div>
      <div class="row"><span>Vollbild</span><button class="btn" id="d-full">Vollbild umschalten (F11)</button></div></div></div>`;

  $("#main").innerHTML = `<section class="screen"><h3>Einstellungen</h3><h1>Dein Setup</h1>
    <div class="tabs">${tabs.map(([k, l]) => `<button class="${k === tab ? "on" : ""}" data-tab="${k}">${l}</button>`).join("")}</div>${body}</section>`;
  $$("[data-tab]").forEach(b => b.onclick = () => { S.settingsTab = b.dataset.tab; renderSettings(); });
  bindSettings(tab);
}
function bindSettings(tab) {
  const st = S.settings, on = (id, ev, fn) => { const el = $("#" + id); if (el) el.addEventListener(ev, fn); };
  if (tab === "sound") {
    on("s-on", "change", e => saveSettings({ sounds: { enabled: e.target.checked } }));
    on("s-vol", "change", e => saveSettings({ sounds: { volume: +e.target.value } }));
    on("s-up", "change", async e => { if (e.target.files[0]) { await uploadFile(e.target.files[0]); toast("Hochgeladen"); renderSettings(); } });
    Object.keys(Audio.EVENT_LABELS).forEach(k => on("ev-" + k, "change", e => saveSettings({ sounds: { events: { [k]: e.target.value } } })));
    $$("[data-test]").forEach(b => b.onclick = () => { Audio.unlock(); Audio.playEvent(b.dataset.test, st.sounds.events); });
  }
  if (tab === "caller") {
    on("c-on", "change", e => saveSettings({ caller: { enabled: e.target.checked } }));
    on("c-lang", "change", e => saveSettings({ caller: { lang: e.target.value } }));
    on("c-voice", "change", e => saveSettings({ caller: { voice: e.target.value } }));
    on("c-rate", "change", e => saveSettings({ caller: { rate: +e.target.value } }));
    on("c-pitch", "change", e => saveSettings({ caller: { pitch: +e.target.value } }));
    on("c-co", "change", e => saveSettings({ caller: { call_checkout: e.target.checked } }));
    on("c-test", "click", () => Audio.Caller.say("Einhundertachtzig!", { priority: true }));
  }
  if (tab === "pads") {
    on("pad-add", "click", async () => {
      const f = $("#pad-file").files[0], name = $("#pad-name").value.trim();
      if (!f || !name) return toast("Name und Datei angeben");
      const file = await uploadFile(f);
      await saveSettings({ pads: [...(st.pads || []), { name, file }] }); renderSettings();
    });
    $$("[data-delpad]").forEach(b => b.onclick = async () => { const pads = [...st.pads]; pads.splice(+b.dataset.delpad, 1); await saveSettings({ pads }); renderSettings(); });
    $$("[data-play]").forEach(b => b.onclick = () => { Audio.unlock(); Audio.playFile(b.dataset.play); });
  }
  if (tab === "players") {
    (S._walkNames || []).forEach((n, i) => on("wk-" + i, "change", e => saveSettings({ walkon: { [n]: e.target.value } })));
    $$("[data-wkplay]").forEach(b => b.onclick = () => { const f = $("#wk-" + b.dataset.wkplay).value; if (f) { Audio.unlock(); Audio.playFile(f); } });
    on("wk-up", "change", async e => { if (e.target.files[0]) { await uploadFile(e.target.files[0]); toast("Hochgeladen"); renderSettings(); } });
  }
  if (tab === "display") {
    on("d-anim", "change", e => saveSettings({ animations: e.target.checked }));
    on("d-full", "click", () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => toast("Vollbild hier nicht möglich – F11 drücken")));
  }
  if (tab === "cameras") bindCameras();
}

async function camerasTab() {
  const info = await api("/api/cameras");
  S._camInfo = info;
  const active = info.count > 0;
  return `<div class="card"><h3>Kamera-Quellen</h3>
    <p class="note" style="margin:0">Entweder <b>3 USB-Kameras</b> rund ums Board (beste Genauigkeit) oder <b>eine Kamera</b>, z. B. dein iPhone:
    Mit einer Webcam-App wie <b>Camo</b> oder <b>Iriun</b> erscheint das iPhone hier als normale Kamera. Alternativ eine Stream-URL eintragen (z. B. aus einer IP-Kamera-App).
    Bei nur einer Kamera können sich Darts gegenseitig verdecken – dann kurz per Tipp korrigieren.</p>
    <div class="row"><span>Angeschlossene Kameras <span class="sub" id="cam-found"></span></span><button class="btn" id="cam-scan">Kameras suchen</button></div>
    <div id="cam-list" class="rows"></div>
    <div class="row"><input type="url" id="cam-url" placeholder="Stream-URL, z. B. http://192.168.1.20:8080/video" style="flex:1;min-width:240px"><button class="btn" id="cam-addurl">URL hinzufügen</button></div>
    <div class="row"><span>Auflösung / FPS</span><select id="cam-res">${["640x480", "800x600", "1280x720"].map(r => `<option ${r === S.settings.cam_res ? "selected" : ""}>${r}</option>`).join("")}</select>
      <select id="cam-fps">${[5, 10, 15, 30].map(f => `<option ${+f === +S.settings.cam_fps ? "selected" : ""}>${f}</option>`).join("")}</select></div>
    <div class="toolbar"><button class="btn primary" id="cam-start">Erkennung starten</button>${active ? `<button class="btn danger" id="cam-stop">Erkennung stoppen</button>` : ""}</div></div>
    ${active ? `<div class="card" style="margin-top:12px"><h3>Kalibrierung</h3>
      <p class="note" style="margin:0">Pro Kamera die <b>Außenkante des Doppelrings</b> an 4 Stellen anklicken: ${info.points.map(esc).join(", ")}. Danach richtet sich die Kalibrierung automatisch genau aus – die gelben Ringe müssen auf dem Board liegen.</p>
      <div class="camgrid">${Array.from({ length: info.count }, (_, i) => `<div><div class="row"><b>Kamera ${i + 1}</b><span class="pill ${info.calibrated[i] ? "throw" : "wait"}">${info.calibrated[i] ? "kalibriert" : "nicht kalibriert"}</span><span class="sub" id="hint${i}"></span></div>
        <div class="camwrap" id="cw${i}"><img id="ci${i}" src="/cam/${i}_overlay.jpg?${Date.now()}" alt="Kamera ${i + 1}"></div>
        <div class="toolbar" style="margin-top:6px"><button class="btn ghost" data-refresh="${i}">Bild aktualisieren</button></div></div>`).join("")}</div></div>` : ""}`;
}
function bindCameras() {
  const chosen = new Set((S.settings.cameras || []).map(String));
  const list = $("#cam-list");
  const drawList = items => {
    list.innerHTML = items.map(c => `<label class="row chk"><input type="checkbox" value="${esc(c.source)}" ${chosen.has(c.source) ? "checked" : ""}> ${esc(c.label)}</label>`).join("");
    $$("input", list).forEach(i => i.onchange = () => i.checked ? chosen.add(i.value) : chosen.delete(i.value));
  };
  let items = [...chosen].map(s => ({ source: s, label: /^\d+$/.test(s) ? `Kamera ${+s + 1}` : s }));
  drawList(items);
  $("#cam-scan").onclick = async () => {
    $("#cam-found").textContent = "Suche …";
    const found = await api("/api/cameras/scan");
    $("#cam-found").textContent = `${found.length} gefunden`;
    items = [...found, ...items.filter(i => !/^\d+$/.test(i.source))];
    drawList(items);
  };
  $("#cam-addurl").onclick = () => { const u = $("#cam-url").value.trim(); if (!u) return; items.push({ source: u, label: u }); chosen.add(u); drawList(items); };
  $("#cam-start").onclick = async () => {
    if (!chosen.size) return toast("Mindestens eine Kamera auswählen");
    await saveSettings({ cam_res: $("#cam-res").value, cam_fps: +$("#cam-fps").value });
    try { await api("/api/cameras/start", { sources: [...chosen] }); toast("Erkennung läuft"); renderSettings(); } catch (e) { }
  };
  const stop = $("#cam-stop"); if (stop) stop.onclick = async () => { await api("/api/cameras/stop", {}); renderSettings(); };
  $$("[data-refresh]").forEach(b => b.onclick = () => { $("#ci" + b.dataset.refresh).src = `/cam/${b.dataset.refresh}_overlay.jpg?${Date.now()}`; });
  const info = S._camInfo;
  for (let i = 0; i < (info ? info.count : 0); i++) {
    const img = $("#ci" + i), wrap = $("#cw" + i), hint = $("#hint" + i);
    let pts = [];
    const upd = () => hint.textContent = pts.length < 4 ? `Klick ${pts.length + 1}/4: ${info.points[pts.length]}` : "Berechne …";
    upd();
    img.onclick = async e => {
      if (pts.length >= 4) return;
      if (pts.length === 0) img.src = `/cam/${i}.jpg?${Date.now()}`;
      const r = img.getBoundingClientRect();
      pts.push([(e.clientX - r.left) * img.naturalWidth / r.width, (e.clientY - r.top) * img.naturalHeight / r.height]);
      const d = document.createElement("div"); d.className = "dot"; d.style.left = (e.clientX - r.left) + "px"; d.style.top = (e.clientY - r.top) + "px"; wrap.appendChild(d);
      upd();
      if (pts.length === 4) {
        const out = await api("/api/calibrate/" + i, { points: pts });
        toast(`Kamera ${i + 1} kalibriert (Ausrichtung ${out.ecc})`);
        renderSettings();
      }
    };
  }
}

// ------------------------------------------------------------------ live state
function updatePill(s) {
  const p = $("#engine-pill");
  if (!s.cameras) { p.textContent = "Manuelle Eingabe"; p.className = "pill"; return; }
  const txt = { idle: "Werfen", motion: "Bewegung …", init: "Startet …" }[s.engine] || s.engine;
  p.textContent = `📷 ${s.cameras} · ${s.turn_done ? "Darts ziehen" : txt}`;
  p.className = "pill " + (s.turn_done ? "wait" : "throw");
}
function connect() {
  const es = new EventSource("/events");
  es.onmessage = e => {
    const s = JSON.parse(e.data), prev = S.state;
    S.state = s;
    updatePill(s);
    if (S.lastSeq !== null && s.seq !== S.lastSeq) handleEvents(prev, s);
    S.lastSeq = s.seq;
    if (S.view === "match") { if (S.correctIdx !== null && S.correctIdx >= s.turn.length) S.correctIdx = null; renderMatch(); }
  };
  es.onerror = () => { es.close(); setTimeout(connect, 1500); };
}

(async function init() {
  try { S.settings = await api("/api/settings"); applySettings(); } catch (e) { }
  if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => { if (S.view === "settings" && S.settingsTab === "caller") renderSettings(); };
  document.addEventListener("pointerdown", () => Audio.unlock(), { once: true });
  connect();
  route();
})();
