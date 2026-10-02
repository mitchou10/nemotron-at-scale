"use strict";

const API = new URL("../api/v1/asr/", location.href);
const REFRESH_MS = 10000;

let range = { hours: 24, buckets: 96 };
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

async function getJson(path) {
  const response = await fetch(new URL(path, API), { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

const fmtMs = (v) => (v == null ? "-" : `${Math.round(v)} ms`);
const fmtPct = (v) => (v == null ? "-" : `${v.toFixed(v === 100 ? 0 : 2)} %`);

function fmtDate(iso, withDay) {
  const d = new Date(iso);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return withDay ? `${d.toLocaleDateString([], { day: "2-digit", month: "short" })} ${time}` : time;
}

function barClass(ratio) {
  if (ratio == null) return "";
  if (ratio >= 0.99) return "ok";
  return ratio >= 0.5 ? "warn" : "bad";
}

// ---- tooltip ----
const tip = $("tip");
function showTip(event, text) {
  tip.textContent = text;
  tip.hidden = false;
  const x = Math.min(event.clientX + 12, innerWidth - tip.offsetWidth - 8);
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${event.clientY + 16}px`;
}
const hideTip = () => { tip.hidden = true; };

// ---- rendering ----
function renderBanner(live) {
  const banner = $("banner");
  const up = live.filter((w) => w.healthy).length;
  let state, text;
  if (!live.length) [state, text] = ["none", "Aucun worker déclaré"];
  else if (up === live.length) [state, text] = ["ok", "Tous les workers sont opérationnels"];
  else if (up > 0) [state, text] = ["warn", `Service dégradé : ${live.length - up} worker(s) hors service sur ${live.length}`];
  else [state, text] = ["bad", "Panne : aucun worker disponible"];
  banner.className = `banner ${state}`;
  banner.textContent = text;
}

function card(label, value, sub) {
  return el("div", { class: "card" },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: String(value) }),
    el("div", { class: "sub", text: sub || " " }));
}

function renderCards(live, history) {
  const up = live.filter((w) => w.healthy).length;
  const active = live.reduce((n, w) => n + w.active_streams, 0);
  const capacity = live.filter((w) => w.healthy).reduce((n, w) => n + w.max_streams, 0);
  const streams = history.streams;
  const label = range.hours >= 168 ? "7 derniers jours" : `${range.hours} dernière(s) heure(s)`;
  $("cards").replaceChildren(
    card("Workers disponibles", `${up} / ${live.length}`),
    card("Flux en cours", active, capacity ? `capacité ${capacity}` : ""),
    card("Flux démarrés", streams.started, label),
    card("Échecs / reprises", `${streams.failed} / ${streams.failovers}`, "flux en échec / reprises"),
  );
}

function renderWorker(live, hist) {
  const key = live ? live.instance : hist.instance;
  const healthy = live ? live.healthy : false;
  const max = live ? live.max_streams : hist.max_streams;
  const active = live ? live.active_streams : 0;

  const bars = el("div", { class: "bars" });
  for (const bucket of hist ? hist.buckets : []) {
    const bar = el("i", { class: barClass(bucket.up_ratio) });
    const when = fmtDate(bucket.start, range.hours > 24);
    const detail = bucket.samples
      ? `${when}\nDisponibilité ${Math.round(bucket.up_ratio * 100)} %\nLatence ${fmtMs(bucket.avg_latency_ms)}\nPic ${bucket.max_active_streams} flux`
      : `${when}\nPas de donnée`;
    bar.addEventListener("mousemove", (e) => showTip(e, detail));
    bar.addEventListener("mouseleave", hideTip);
    bars.append(bar);
  }

  const pct = max ? Math.min(100, (active / max) * 100) : 0;
  const meter = el("div", { class: "meter" },
    el("div", { class: pct >= 100 ? "full" : pct >= 80 ? "high" : "", style: `width:${pct}%` }));

  const stateClass = live ? (healthy ? "up" : "down") : "";
  const stateText = live ? (healthy ? "Opérationnel" : "Hors service") : "Retiré";

  return el("article", { class: "worker" },
    el("div", { class: "top" },
      el("span", { class: "name", text: key }),
      live && live.kind ? el("span", { class: "badge", text: live.kind }) : null,
      el("span", { class: `pill ${stateClass}` }, el("span", { class: "dot" }), stateText)),
    bars,
    el("div", { class: "axis" },
      el("span", { text: hist && hist.buckets.length ? fmtDate(hist.buckets[0].start, range.hours > 24) : "" }),
      el("span", { text: "maintenant" })),
    meter,
    el("div", { class: "stats" },
      el("span", {}, "Flux ", el("b", { text: max ? `${active} / ${max}` : String(active) })),
      el("span", {}, "Latence ", el("b", { text: fmtMs(live ? live.latency_ms : null) })),
      el("span", {}, "Disponibilité ", el("b", { text: fmtPct(hist ? hist.uptime_pct : null) })),
      el("span", {}, "Latence moyenne ", el("b", { text: fmtMs(hist ? hist.avg_latency_ms : null) })),
      el("span", {}, "Pic ", el("b", { text: hist ? String(hist.peak_streams) : "-" }))));
}

function renderWorkers(live, history) {
  const histByKey = new Map(history.instances.map((h) => [h.instance, h]));
  const liveKeys = new Set(live.map((w) => w.instance));
  const cards = live.map((w) => renderWorker(w, histByKey.get(w.instance)));
  // Instances seen in the history but no longer discovered.
  for (const h of history.instances) if (!liveKeys.has(h.instance)) cards.push(renderWorker(null, h));
  $("workers").replaceChildren(...(cards.length ? cards : [el("div", { class: "empty", text: "Aucun worker. La transcription est peut-être désactivée (ASR_ENABLED)." })]));
}

async function refresh() {
  try {
    const [live, history] = await Promise.all([
      getJson("instances"),
      getJson(`history?hours=${range.hours}&buckets=${range.buckets}`),
    ]);
    renderBanner(live);
    renderCards(live, history);
    renderWorkers(live, history);
    $("updated").textContent = `Mis à jour à ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    const banner = $("banner");
    banner.className = "banner bad";
    banner.textContent = "Impossible de joindre l'API";
    $("updated").textContent = String(error.message || error);
  }
}

$("ranges").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  range = { hours: Number(button.dataset.hours), buckets: Number(button.dataset.buckets) };
  for (const b of $("ranges").children) b.classList.toggle("active", b === button);
  refresh();
});

refresh();
setInterval(refresh, REFRESH_MS);
