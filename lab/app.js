"use strict";

const state = {
  data: null,
  activeIndex: 0,
  decisions: new Map(),
};

const byId = (id) => document.getElementById(id);
const formatPercent = (value) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
const formatMoney = (value) => `$${Number(value).toFixed(2)}`;

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderFunnel(rows) {
  const host = byId("hero-funnel");
  host.replaceChildren();
  const max = Math.max(...rows.map((row) => row.count));
  rows.forEach((row, index) => {
    const item = makeElement("div", "funnel-row");
    item.append(makeElement("span", "", row.label));
    const track = makeElement("div", "funnel-track");
    const bar = document.createElement("i");
    track.append(bar);
    item.append(track, makeElement("strong", "", String(row.count)));
    host.append(item);
    requestAnimationFrame(() => {
      window.setTimeout(() => {
        bar.style.width = `${Math.max(6, (row.count / max) * 100)}%`;
      }, 160 + index * 170);
    });
  });
}

function chartGeometry(values) {
  const width = 760;
  const height = 290;
  const pad = 18;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => ({
    x: pad + (index / (values.length - 1)) * (width - pad * 2),
    y: pad + ((max - value) / range) * (height - pad * 2),
  }));
  const line = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const area = `${line} L${points.at(-1).x.toFixed(2)},${height} L${points[0].x.toFixed(2)},${height} Z`;
  return { line, area, last: points.at(-1) };
}

function renderChart(candidate) {
  const geometry = chartGeometry(candidate.prices);
  byId("line-path").setAttribute("d", geometry.line);
  byId("area-path").setAttribute("d", geometry.area);
  byId("last-point").setAttribute("cx", geometry.last.x);
  byId("last-point").setAttribute("cy", geometry.last.y);
  const grid = byId("chart-grid");
  grid.replaceChildren();
  [54, 112, 170, 228].forEach((y) => {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", "18");
    line.setAttribute("x2", "742");
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("class", "chart-grid-line");
    grid.append(line);
  });
}

function renderTabs() {
  const host = byId("case-tabs");
  host.replaceChildren();
  state.data.cases.forEach((candidate, index) => {
    const button = makeElement("button", "case-tab");
    button.type = "button";
    button.role = "tab";
    button.setAttribute("aria-selected", String(index === state.activeIndex));
    button.append(makeElement("span", "", `CASE 0${index + 1}`));
    button.append(document.createTextNode(candidate.symbol));
    button.addEventListener("click", () => {
      state.activeIndex = index;
      renderActiveCase();
    });
    host.append(button);
  });
}

function resetAudit() {
  const candidate = state.data.cases[state.activeIndex];
  const previous = state.decisions.get(candidate.symbol);
  document.querySelectorAll(".decision-buttons button").forEach((button) => {
    button.classList.toggle("selected", button.dataset.action === previous);
  });
  byId("audit-locked").hidden = Boolean(previous);
  byId("audit-reveal").hidden = !previous;
  if (previous) renderAudit(candidate, previous);
}

function renderActiveCase() {
  renderTabs();
  const candidate = state.data.cases[state.activeIndex];
  byId("case-archetype").textContent = candidate.archetype.toUpperCase();
  byId("case-symbol").textContent = candidate.symbol;
  byId("case-title").textContent = candidate.title;
  byId("metric-close").textContent = formatMoney(candidate.close);
  byId("metric-return").textContent = formatPercent(candidate.return_63d);
  byId("metric-rsi").textContent = Number(candidate.rsi14).toFixed(1);
  byId("metric-stage").textContent = `${candidate.stage} / ${candidate.stage_name.replaceAll("_", " ")}`;
  byId("metric-atr").textContent = `${(candidate.atr14_pct * 100).toFixed(1)}%`;
  renderChart(candidate);
  resetAudit();
}

function renderAudit(candidate, action) {
  const matched = action === candidate.correct_action;
  const banner = byId("verdict-banner");
  banner.classList.toggle("miss", !matched);
  byId("verdict-match").textContent = matched ? "YOUR CALL MATCHED THE GATE" : "YOUR CALL EXPOSED A DISAGREEMENT";
  byId("verdict-status").textContent = candidate.status;
  byId("case-thesis").textContent = candidate.thesis;
  byId("case-red-team").textContent = candidate.red_team;

  const gateList = byId("gate-list");
  gateList.replaceChildren();
  candidate.gates.forEach((gate) => {
    const row = makeElement("div", `gate ${gate.state}`);
    row.append(document.createElement("i"));
    const copy = document.createElement("div");
    copy.append(makeElement("strong", "", gate.name), makeElement("p", "", gate.detail));
    row.append(copy);
    gateList.append(row);
  });
  renderPassportPreview(candidate);
  const challengeTitle = `[Challenge]: ${candidate.symbol} — ${candidate.title}`;
  const challengeUrl = new URL(`${state.data.repository_url}/issues/new`);
  challengeUrl.searchParams.set("template", "counterexample.yml");
  challengeUrl.searchParams.set("title", challengeTitle);
  byId("challenge-case-link").href = challengeUrl.toString();
}

function passportPayload(candidate) {
  return {
    ...candidate.passport,
    symbol: candidate.symbol,
    archetype: candidate.archetype,
    technical_score: candidate.technical_score,
    score_is_probability: false,
    stage: candidate.stage,
    invalidation_reference: candidate.invalidation_reference,
    red_team: candidate.red_team,
    gates: candidate.gates,
    disclaimer: state.data.disclaimer,
  };
}

function renderPassportPreview(candidate) {
  byId("passport-json").textContent = JSON.stringify(passportPayload(candidate), null, 2);
  byId("download-passport").disabled = false;
}

function chooseDecision(action) {
  const candidate = state.data.cases[state.activeIndex];
  state.decisions.set(candidate.symbol, action);
  resetAudit();
}

function showPassport() {
  const candidate = state.data.cases[state.activeIndex];
  if (!state.decisions.has(candidate.symbol)) return;
  const payload = passportPayload(candidate);
  const host = byId("passport-content");
  host.replaceChildren();
  const grid = makeElement("div", "passport-grid");
  [
    ["Observation", payload.observation_id],
    ["Decision posture", payload.decision_status],
    ["Source posture", payload.source_posture],
    ["Evidence quality", `${payload.evidence_quality} / 100`],
    ["Technical rank", `${Number(payload.technical_score).toFixed(1)} / 100`],
    ["Order created", String(payload.order_created).toUpperCase()],
  ].forEach(([label, value]) => {
    const field = makeElement("div", "passport-field");
    field.append(makeElement("span", "", label), makeElement("strong", "", value));
    grid.append(field);
  });
  host.append(grid);
  const missing = makeElement("div", "passport-missing");
  missing.append(makeElement("span", "", "MISSING EVIDENCE"));
  const list = document.createElement("ul");
  payload.missing_evidence.forEach((item) => list.append(makeElement("li", "", item)));
  missing.append(list);
  host.append(missing);
  byId("passport-dialog").showModal();
}

function downloadPassport() {
  const candidate = state.data.cases[state.activeIndex];
  if (!state.decisions.has(candidate.symbol)) return;
  const blob = new Blob([`${JSON.stringify(passportPayload(candidate), null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${candidate.symbol.toLowerCase()}-evidence-passport.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderQuests(quests) {
  const host = byId("quest-board");
  host.replaceChildren();
  quests.forEach((quest, index) => {
    const link = makeElement("a", "quest");
    link.href = quest.href;
    link.append(makeElement("span", "quest-index", `Q0${index + 1}`));
    const body = document.createElement("div");
    body.append(
      makeElement("span", "quest-track", quest.track),
      makeElement("h3", "", quest.title),
      makeElement("p", "", quest.description),
    );
    const meta = makeElement("span", "quest-meta", quest.difficulty);
    meta.append(makeElement("span", "", `${quest.label} ↗`));
    link.append(body, meta);
    host.append(link);
  });
}

function wireEvents() {
  document.querySelectorAll(".decision-buttons button").forEach((button) => {
    button.addEventListener("click", () => chooseDecision(button.dataset.action));
  });
  byId("passport-button").addEventListener("click", showPassport);
  byId("download-passport").addEventListener("click", downloadPassport);
  byId("dialog-download").addEventListener("click", downloadPassport);
  ["close-passport", "dialog-close-secondary"].forEach((id) => {
    byId(id).addEventListener("click", () => byId("passport-dialog").close());
  });
  byId("passport-dialog").addEventListener("click", (event) => {
    if (event.target === byId("passport-dialog")) byId("passport-dialog").close();
  });
}

async function boot() {
  wireEvents();
  try {
    const response = await fetch("data/replay.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Replay data returned ${response.status}`);
    state.data = await response.json();
    renderFunnel(state.data.universe_funnel);
    renderQuests(state.data.contributor_quests);
    renderActiveCase();
  } catch (error) {
    byId("case-archetype").textContent = "REPLAY DATA UNAVAILABLE";
    byId("case-title").textContent = "Run `make lab-build` and serve this directory over HTTP.";
    console.error(error);
  }
}

boot();
