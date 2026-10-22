"use strict";
const $ = (id) => document.getElementById(id);
const form = $("analysis-form");
const svg = $("network-map");
const NS = "http://www.w3.org/2000/svg";
let catalog = null;
let lastResult = null;
let mapData = null;
let busy = false;

function node(tag, attrs = {}, text = "") {
  const element = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  if (text) element.textContent = text;
  return element;
}
function project([lon, lat]) {
  return [130 + (lon - 16.98) / 0.016 * 700, 374 - (lat - 51.1) / 0.006 * 244];
}
function pathFor(coordinates) {
  return coordinates.map((coordinate, i) => `${i ? "L" : "M"}${project(coordinate).join(",")}`).join(" ");
}
function drawLine(feature, attrs) {
  if (feature) svg.append(node("path", {d: pathFor(feature.geometry.coordinates), fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round", ...attrs}));
}
function renderMap(result, pending = false) {
  svg.replaceChildren(node("title", {id: "map-title"}, "Schemat syntetycznej sieci drogowej"), node("desc", {id: "map-description"}, pending ? "Oczekiwanie na nową analizę." : "Zielona linia: przejazd po analizie. Przerywana: trasa bez zalania. Pomarańczowe drogi: odcinki zablokowane. Błękit: zalanie syntetyczne."));
  const defs = node("defs");
  const grid = node("pattern", {id: "grid", width: 30, height: 30, patternUnits: "userSpaceOnUse"});
  grid.append(node("path", {d: "M 30 0 L 0 0 0 30", fill: "none", stroke: "#dce5d6", "stroke-width": 0.6}));
  defs.append(grid); svg.append(defs, node("rect", {width: 960, height: 510, fill: "url(#grid)"}));
  // Neutral blocks provide orientation only; all road and flood geometry comes from the API.
  for (let row = 0; row < 2; row++) for (let column = 0; column < 4; column++) {
    const x = 152 + column * 175, y = 153 + row * 122;
    svg.append(node("rect", {x, y, width: 129, height: 76, rx: 7, fill: "#e3e9da", stroke: "#d8e1d2"}));
    svg.append(node("rect", {x: x + 16, y: y + 14, width: 39, height: 27, rx: 2, fill: "#d6dfcc"}));
    svg.append(node("rect", {x: x + 66, y: y + 30, width: 45, height: 31, rx: 2, fill: "#d6dfcc"}));
  }
  if (!result) return;
  for (const road of result.roads.features) drawLine(road, {stroke: "#d0dacb", "stroke-width": 13});
  for (const road of result.roads.features) drawLine(road, {stroke: "#fafbf6", "stroke-width": 8});
  if (!pending) {
    for (const flood of result.flood.features) {
      svg.append(node("path", {d: pathFor(flood.geometry.coordinates[0]) + " Z", fill: "#b4d9df", "fill-opacity": 0.72, stroke: "#78aeb8", "stroke-width": 1.5, "stroke-dasharray": "5 4"}));
    }
    drawLine(result.baseline, {stroke: "#999b79", "stroke-width": 4, "stroke-dasharray": "8 8"});
    for (const blocked of result.blocked.features) drawLine(blocked, {stroke: "#c36b43", "stroke-width": 6});
    drawLine(result.route, {stroke: "#ffffff", "stroke-width": 11});
    drawLine(result.route, {stroke: "#286b50", "stroke-width": 6});
  }
  const chosen = [[$("origin").value, "START", "#286b50", -44], [$("destination").value, "CEL", "#a67337", 38]];
  for (const [id, title, color, offset] of chosen) {
    const point = catalog.points.find((item) => item.id === id);
    if (!point) continue;
    const [x, y] = project(point.coordinates);
    svg.append(node("circle", {cx: x, cy: y, r: 12, fill: "white", stroke: color, "stroke-width": 3}));
    svg.append(node("circle", {cx: x, cy: y, r: 4, fill: color}));
    svg.append(node("rect", {x: x - 52, y: y + offset - 15, width: 104, height: 27, rx: 4, fill: "#fcfdf8", stroke: "#d4ddcd"}));
    svg.append(node("text", {x, y: y + offset + 2, "text-anchor": "middle", fill: color, "font-family": "Segoe UI, sans-serif", "font-size": 11, "font-weight": 650, "letter-spacing": 1.2}, title));
  }
  svg.append(node("text", {x: 480, y: 466, "text-anchor": "middle", fill: "#819279", "font-size": 10, "letter-spacing": 2, "font-family": "Segoe UI, sans-serif"}, "OBSZAR SYNTETYCZNY / 15 WĘZŁÓW"));
}
function setStatus(message, style = "") {
  $("status").textContent = message;
  $("status").className = `result-status ${style}`;
}
function setBusy(value) {
  busy = value;
  for (const control of form.elements) control.disabled = value;
  $("analyze").textContent = value ? "Obliczanie przejazdu…" : "Oblicz przejazd ↗";
  $("download").disabled = value || !lastResult;
  $("status").setAttribute("aria-busy", String(value));
}
function clearMetrics() {
  for (const id of ["baseline-length", "route-length", "extra-distance", "blocked-count"]) $(id).textContent = "—";
  $("extra-percent").textContent = "względem trasy bazowej";
  $("calculation-info").textContent = "Wynik obliczany przez FastAPI · NetworkX · Shapely";
}
const distance = (metres) => metres == null ? "—" : metres >= 1000 ? `${(metres / 1000).toLocaleString("pl-PL", {maximumFractionDigits: 2})} km` : `${Math.round(metres).toLocaleString("pl-PL")} m`;
async function api(path, options = {}) {
  const response = await fetch(new URL(path.replace(/^\//,""),new URL("./",document.baseURI)), {...options, signal: AbortSignal.timeout(12000)});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Backend zwrócił błąd ${response.status}. Spróbuj ponownie.`);
  }
  return response.json();
}
async function loadCatalog() {
  catalog = await api("/api/demo/scenarios");
  $("scenarios").replaceChildren();
  for (const item of catalog.scenarios) {
    const label = document.createElement("label"); label.className = "scenario-card";
    const input = document.createElement("input"); input.type = "radio"; input.name = "scenario"; input.value = item.id; input.checked = item.id === "detour";
    const title = document.createElement("strong"); title.textContent = item.title;
    const text = document.createElement("small"); text.textContent = item.description;
    label.append(input, title, text); $("scenarios").append(label);
  }
  for (const id of ["origin", "destination"]) {
    $(id).replaceChildren();
    for (const point of catalog.points) {
      const option = document.createElement("option"); option.value = point.id; option.textContent = point.label; $(id).append(option);
    }
  }
  $("origin").value = "west"; $("destination").value = "east";
}
async function run() {
  if (busy) return;
  setBusy(true); setStatus("Obliczanie grafu, przecięć z zalaniem i najkrótszej trasy…", "pending");
  try {
    if (!catalog) await loadCatalog();
    setBusy(true);
    const request = {scenario: form.querySelector("input[name=scenario]:checked").value, origin: $("origin").value, destination: $("destination").value};
    lastResult = null; $("download").disabled = true; clearMetrics();
    const data = await api("/api/demo/analyze", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(request)});
    lastResult = data; mapData = data; renderMap(data);
    const m = data.metrics;
    $("baseline-length").textContent = distance(m.baseline_length_m);
    $("route-length").textContent = data.status === "unreachable" ? "Brak trasy" : distance(m.route_length_m);
    $("extra-distance").textContent = distance(m.extra_distance_m);
    $("extra-percent").textContent = m.extra_distance_percent == null ? "brak porównywalnej trasy" : `+${m.extra_distance_percent.toLocaleString("pl-PL")}% względem trasy bazowej`;
    $("blocked-count").textContent = `${m.blocked_segments} / ${m.total_segments}`;
    $("calculation-info").textContent = `${m.nodes} węzłów · ${m.total_segments} odcinki · ${m.calc_time_ms.toLocaleString("pl-PL")} ms na backendzie`;
    if (data.status === "unreachable") setStatus("Brak przejazdu. Zalanie odcina wybrane punkty; algorytm nie znalazł połączenia w pozostałej sieci.", "warning");
    else if (m.route_length_m === 0) setStatus("START i CEL wskazują ten sam węzeł. Długość przejazdu wynosi 0 m; nie wymaga pokonania żadnego odcinka.");
    else if (m.extra_distance_m > 1) setStatus(`Znaleziono objazd. Trasa omija zalanie i jest dłuższa o ${distance(m.extra_distance_m)} od przejazdu bez zalania.`);
    else setStatus("Przejazd jest dostępny. Zalanie nie wymusza wydłużenia trasy między wybranymi punktami.");
  } catch (error) {
    lastResult = null; clearMetrics(); renderMap(null);
    setStatus(error.name === "TimeoutError" ? "Backend nie odpowiedział w ciągu 12 sekund. Ponów obliczenie." : `Nie udało się wykonać analizy. ${error.message}`, "error");
  } finally { setBusy(false); }
}
form.addEventListener("submit", (event) => {event.preventDefault(); run();});
form.addEventListener("change", () => {
  if (mapData) renderMap(mapData, true);
  lastResult = null; clearMetrics(); $("download").disabled = true;
  setStatus("Ustawienia zmienione. Wybierz „Oblicz przejazd”, aby otrzymać nowy wynik.", "pending");
});
$("reset").addEventListener("click", () => {
  if (!catalog) {run(); return;}
  form.querySelector("input[value=detour]").checked = true;
  $("origin").value = "west"; $("destination").value = "east"; run();
});
$("download").addEventListener("click", () => {
  if (!lastResult) return;
  const data = {...lastResult.roads, features: [...lastResult.roads.features, ...lastResult.flood.features, ...lastResult.blocked.features.map((item) => ({...item, properties: {...item.properties, layer: "blocked", source: "synthetic"}})), ...[lastResult.baseline, lastResult.route].filter(Boolean).map((item, i) => ({...item, properties: {...item.properties, layer: i ? "route" : "baseline", source: "synthetic"}}))], metadata: {data_mode: "sample", scenario: lastResult.scenario, metrics: lastResult.metrics}};
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/geo+json"}));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `sentinelhub-${lastResult.scenario}-sample.geojson`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
renderMap(null); run();
