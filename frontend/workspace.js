"use strict";
const byId = id => document.getElementById(id);
const svg = byId("workspace-map");
const applicationBase = new URL("./", document.baseURI);
const NS = "http://www.w3.org/2000/svg";
let credentials = null, workspace = null, currentResult = null, busy = false;
let bounds = [0, 0, 1, 1], scale = 1, offset = [0, 0];
const metres = value => value == null ? "—" : value >= 1000 ? `${(value/1000).toLocaleString("pl-PL", {maximumFractionDigits:2})} km` : `${Math.round(value)} m`;
function element(tag, attrs={}, text="") {
  const el = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
  if (text) el.textContent = text;
  return el;
}
function status(text, type="pending", id="workspace-status") {
  byId(id).textContent = text; byId(id).className = `result-status ${type}`;
}
function project([lon, lat]) {return [offset[0] + (lon-bounds[0])*scale, offset[1] - (lat-bounds[1])*scale];}
function paths(geometry) {
  let lines;
  if (geometry.type === "LineString") lines = [geometry.coordinates];
  else if (geometry.type === "MultiLineString" || geometry.type === "Polygon") lines = geometry.coordinates;
  else lines = geometry.coordinates.flat();
  return lines.map(line => line.map((point,index) => `${index ? "L" : "M"}${project(point).join(",")}`).join(" ") + (geometry.type.includes("Polygon") ? " Z" : "")).join(" ");
}
function roadPoints(data) {
  return (data?.roads?.features || []).flatMap(feature => feature.geometry.type === "LineString" ? feature.geometry.coordinates : feature.geometry.coordinates.flat());
}
function drawMap(data, result=null) {
  svg.replaceChildren(element("title", {id:"workspace-map-title"}, "Sieć i strefy z danych przestrzeni"));
  svg.append(element("rect", {width:960,height:510,fill:"#edf2e7"}));
  const points = roadPoints(data);
  if (!points.length) {svg.append(element("text", {x:480,y:250,"text-anchor":"middle",fill:"#728570","font-size":18}, "Wczytaj własne drogi i zalanie w GeoJSON")); return;}
  bounds = [Math.min(...points.map(p=>p[0])), Math.min(...points.map(p=>p[1])), Math.max(...points.map(p=>p[0])), Math.max(...points.map(p=>p[1]))];
  const width = Math.max(bounds[2]-bounds[0], 0.00001), height = Math.max(bounds[3]-bounds[1], 0.00001);
  scale = Math.min(760/width, 320/height); offset = [(960-width*scale)/2, (510+height*scale)/2];
  const add = (feature, attrs) => svg.append(element("path", {d:paths(feature.geometry), fill:"none", "stroke-linecap":"round", "stroke-linejoin":"round", ...attrs}));
  for (const feature of data.roads.features) {add(feature,{stroke:"#cad5c4","stroke-width":12}); add(feature,{stroke:"#fcfdf8","stroke-width":7});}
  for (const feature of data.flood?.features || []) add(feature,{fill:"#acd4dc","fill-opacity":0.6,"fill-rule":"evenodd",stroke:"#78aeb8","stroke-width":1});
  if (result?.baseline) add(result.baseline,{stroke:"#989c79","stroke-width":4,"stroke-dasharray":"8 7"});
  for (const feature of result?.blocked.features || []) add(feature,{stroke:"#bf6c42","stroke-width":6});
  if (result?.route) {add(result.route,{stroke:"white","stroke-width":10});add(result.route,{stroke:"#286b50","stroke-width":5});}
  for (const [id,label,color] of [["route-start","START","#286b50"],["route-end","CEL","#a67337"]]) {
    try {const [lat,lon]=parseCoordinate(byId(id).value); const [x,y]=project([lon,lat]);
      svg.append(element("circle",{cx:x,cy:y,r:8,fill:"white",stroke:color,"stroke-width":3}));
      svg.append(element("text",{x,y:y-18,"text-anchor":"middle",fill:color,"font-size":13,"font-weight":650},label));
    } catch { /* Empty coordinates do not create markers. */ }
  }
}
function setBusy(value) {
  busy = value;
  for (const el of document.querySelectorAll("input,button,fieldset")) el.disabled=value;
  if (!value) {
    const connected=Boolean(credentials && workspace);
    byId("dataset-fields").disabled=!connected;
    byId("route-fields").disabled=!(connected && workspace.datasets?.roads && workspace.datasets?.flood);
    byId("save-access").disabled=!connected;
    byId("rotate-access").disabled=!connected;
    byId("close-workspace").disabled=!connected;
    byId("delete-workspace").disabled=!connected;
    byId("refresh-history").disabled=!connected;
    byId("download-analysis").disabled=!currentResult;
  }
  byId("workspace-status").setAttribute("aria-busy", String(value));
}
async function request(path, options={}, authenticated=true) {
  const headers={"Content-Type":"application/json",...(options.headers || {})};
  if (authenticated && credentials) headers.Authorization=`Bearer ${credentials.key}`;
  const response=await fetch(new URL(path.replace(/^\//,""),applicationBase),{...options,headers,signal:AbortSignal.timeout(80000)});
  if (response.status === 204) return null;
  const data=await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Niepoprawne dane lub odpowiedź serwera (HTTP ${response.status}).`);
  return data;
}
const url = suffix => `/api/workspaces/${credentials.id}${suffix}`;
async function action(message, callback) {
  if (busy) return;
  setBusy(true); status(message);
  try {await callback();} catch (error) {status(error.name === "TimeoutError" ? "Upłynął czas oczekiwania. Odczytaj przestrzeń przed ponowieniem operacji." : error.message,"error");}
  finally {setBusy(false);}
}
function blankMetrics() {
  currentResult=null;
  for (const id of ["own-baseline","own-route","own-extra","own-blocked"]) byId(id).textContent="—";
  byId("download-analysis").disabled=true;
}
function clearSession() {
  credentials=null;workspace=null;blankMetrics();
  byId("workspace-id").value="";byId("workspace-key").value="";
  byId("dataset-form").reset();byId("route-form").reset();byId("history-list").replaceChildren();
  byId("data-heading").textContent="Brak otwartej przestrzeni";byId("data-mode").textContent="PRYWATNA PRZESTRZEŃ";
  byId("workspace-info").textContent="Brak otwartej przestrzeni.";byId("own-metadata").textContent="";
  drawMap(null);status("Otwórz lub utwórz przestrzeń, aby rozpocząć.","pending","analysis-status");
}
function showWorkspace(data) {
  workspace=data; blankMetrics();
  byId("workspace-info").textContent=`${data.name} · wersja danych ${data.revision} · zapis ${new Date(data.created_at).toLocaleString("pl-PL")}`;
  const datasets=data.datasets;
  byId("data-heading").textContent=datasets ? datasets.source : "Brak zapisanych danych";
  byId("data-mode").textContent=({sample:"DANE PRZYKŁADOWE",user:"DANE UŻYTKOWNIKA",live:"IMPORT ZEWNĘTRZNY"})[datasets?.data_mode] || "PRYWATNA PRZESTRZEŃ";
  if (datasets) {
    byId("data-source").value=datasets.source;
    const observed = datasets.observed_at ? new Date(datasets.observed_at) : null;
    byId("observed-at").value = observed && Number.isFinite(observed.getTime())
      ? new Date(observed.getTime()-observed.getTimezoneOffset()*60000).toISOString().slice(0,16) : "";
    byId("sample-data").checked=datasets.data_mode === "sample";
    const points=roadPoints(datasets);
    if (points.length) {byId("route-start").value=[points[0][1],points[0][0]].join(",");byId("route-end").value=[points.at(-1)[1],points.at(-1)[0]].join(",");}
    byId("own-metadata").textContent=`${datasets.data_mode} · ${datasets.observed_at ? "data źródła: "+new Date(datasets.observed_at).toLocaleString("pl-PL") : "data obserwacji niepotwierdzona"} · zapis: ${new Date(datasets.saved_at).toLocaleString("pl-PL")}`;
  }
  drawMap(datasets);
  status(datasets?.roads && datasets?.flood ? "Dane odczytane. Wybierz punkty i oblicz analizę." : "Zapisz oba zbiory lub dokończ import tego samego obszaru.","pending","analysis-status");
}
async function refreshHistory() {
  const history=await request(url("/analyses")); const list=byId("history-list");list.replaceChildren();
  if (!history.length) {const p=document.createElement("p");p.className="privacy-note";p.textContent="Brak zapisanych wyników.";list.append(p);}
  for (const item of history) {
    const row=document.createElement("div");row.className="history-item";
    const button=document.createElement("button");button.type="button";
    button.textContent=`${new Date(item.created_at).toLocaleString("pl-PL")} · v${item.revision} · ${item.status === "found" ? "trasa" : "brak przejazdu"}`;
    button.addEventListener("click",()=>action("Odczytywanie wyniku…",async()=>{showResult(await request(url(`/analyses/${item.id}`)));status("Odczytano zapisany wynik, bez ponownych obliczeń.","");}));
    const remove=document.createElement("button");remove.type="button";remove.className="danger";remove.textContent="Usuń";remove.setAttribute("aria-label",`Usuń analizę ${item.id}`);
    remove.addEventListener("click",()=>{if (confirm("Usunąć wyłącznie ten wynik? Dane wejściowe pozostaną zapisane.")) action("Usuwanie wyniku…",async()=>{await request(url(`/analyses/${item.id}`),{method:"DELETE"});if(currentResult?.analysis_id===item.id) blankMetrics();await refreshHistory();status("Wynik usunięty. Zbiory wejściowe zachowano.","");});});
    row.append(button,remove);list.append(row);
  }
}
function showResult(result) {
  currentResult=result;
  byId("route-start").value=result.start.join(",");byId("route-end").value=result.end.join(",");
  drawMap(result,result); const m=result.metrics;
  byId("own-baseline").textContent=metres(m.baseline_length_m);
  byId("own-route").textContent=result.status === "unreachable" ? "Brak trasy" : metres(m.route_length_m);
  byId("own-extra").textContent=metres(m.extra_distance_m);
  byId("own-blocked").textContent=`${m.blocked_segments} / ${m.total_segments}`;
  byId("data-mode").textContent=({sample:"DANE PRZYKŁADOWE",user:"DANE UŻYTKOWNIKA",live:"IMPORT ZEWNĘTRZNY"})[result.data_mode];
  byId("data-heading").textContent=result.source;
  byId("own-metadata").textContent=`Wynik v${result.revision} · ${new Date(result.created_at).toLocaleString("pl-PL")} · ${m.nodes} węzłów · ${m.calc_time_ms.toLocaleString("pl-PL")} ms · bieżące dane v${workspace.revision}`;
  status(result.status === "unreachable" ? "Brak przejazdu. Wynik odcięcia zapisany w historii." : "Znaleziono przejazd. Wynik z danymi wejściowymi zapisany w historii.",result.status === "unreachable" ? "warning" : "","analysis-status");
}
function download(value, filename) {
  const location=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json"}));
  const link=document.createElement("a");link.href=location;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(location),1000);
}
byId("create-workspace").addEventListener("click",()=>action("Tworzenie prywatnej przestrzeni…",async()=>{
  const value=await request("/api/workspaces",{method:"POST",body:JSON.stringify({name:byId("workspace-name").value.trim()})},false);
  credentials={id:value.id,key:value.key};byId("workspace-id").value=value.id;byId("workspace-key").value=value.key;byId("access-details").open=true;
  showWorkspace(await request(url("")));await refreshHistory();
  status("Przestrzeń gotowa. Wczytaj dane; zachowaj klucz, jeśli chcesz wrócić do historii.","");
}));
byId("load-example").addEventListener("click",()=>{
  if(workspace?.datasets && !confirm("Zastąpić bieżące dane oznaczonym przykładem syntetycznym? Zapisane analizy pozostaną w historii.")) return;
  action("Wczytywanie przykładu…",async()=>{
    const [roads,flood]=await Promise.all([request("/examples/roads.geojson",{},false),request("/examples/flood.geojson",{},false)]);
    if(!credentials) {
      const value=await request("/api/workspaces",{method:"POST",body:JSON.stringify({name:"Przykład · objazd zalanej drogi"})},false);
      credentials={id:value.id,key:value.key};byId("workspace-id").value=value.id;byId("workspace-key").value=value.key;
      showWorkspace(await request(url("")));
    }
    const body={revision:workspace.revision,roads,flood,source:"Syntetyczny przykład SentinelHub · ręcznie przygotowane GeoJSON",observed_at:"2026-01-01T00:00:00Z",sample:true};
    showWorkspace(await request(url("/datasets"),{method:"PUT",body:JSON.stringify(body)}));
    byId("route-start").value="52,21";byId("route-end").value="52,21.002";
    byId("access-details").open=false;
    drawMap(workspace.datasets);await refreshHistory();
    status("Przykład wczytany. Kliknij „Oblicz i zapisz analizę” pod mapą. Aby wrócić później, zachowaj klucz w sekcji dostępu.","");
    status("Punkty są gotowe. Oblicz trasę: zalany odcinek wymusi objazd.","pending","analysis-status");
    byId("route-form").scrollIntoView({behavior:"smooth",block:"center"});
  });
});
byId("open-workspace").addEventListener("click",()=>action("Odczytywanie przestrzeni…",async()=>{
  const id=byId("workspace-id").value.trim(), key=byId("workspace-key").value.trim();
  if (!/^[a-f0-9]{32}$/.test(id) || !/^[A-Za-z0-9_-]{43}$/.test(key)) throw new Error("Sprawdź identyfikator i klucz z zapisanego pliku dostępu.");
  clearSession();credentials={id,key};byId("workspace-id").value=id;byId("workspace-key").value=key;
  try {showWorkspace(await request(url("")));await refreshHistory();status("Przestrzeń odczytana z trwałego magazynu.","");}
  catch(error) {clearSession();throw error;}
}));
byId("save-access").addEventListener("click",()=>download({workspace_id:credentials.id,key:credentials.key,note:"Prywatny klucz właściciela SentinelHub. Nie publikuj pliku."},`sentinelhub-access-${credentials.id}.json`));
byId("close-workspace").addEventListener("click",()=>{clearSession();setBusy(false);status("Przestrzeń zamknięta; dane pozostały zapisane. Do powrotu użyj zachowanego klucza.","");});
byId("rotate-access").addEventListener("click",()=>action("Zmiana klucza…",async()=>{
  const value=await request(url("/rotate-key"),{method:"POST"});credentials.key=value.key;
  byId("workspace-key").value=value.key;byId("access-details").open=true;
  status("Klucz zmieniony; poprzedni nie działa. Zapisz nowy klucz do pliku.","");
}));
byId("delete-workspace").addEventListener("click",()=>{
  if(!confirm("Usunąć tę przestrzeń, jej dane i historię? Inne przestrzenie pozostaną nienaruszone.")) return;
  action("Usuwanie Twojej przestrzeni…",async()=>{
    await request(url(""),{method:"DELETE"});credentials=null;workspace=null;blankMetrics();
    byId("workspace-id").value="";byId("workspace-key").value="";
    byId("dataset-form").reset();byId("route-form").reset();byId("history-list").replaceChildren();
    byId("data-heading").textContent="Brak otwartej przestrzeni";byId("data-mode").textContent="PRYWATNA PRZESTRZEŃ";
    byId("workspace-info").textContent="Twoja przestrzeń została usunięta.";byId("own-metadata").textContent="";
    drawMap(null);status("Przestrzeń usunięta; dane innych osób zachowano.","");
    status("Otwórz lub utwórz przestrzeń, aby rozpocząć.","pending","analysis-status");
  });
});
async function readGeoJSON(id) {
  const file=byId(id).files[0];if(!file) throw new Error("Wybierz oba pliki GeoJSON.");
  if(file.size>1048576) throw new Error("Jeden plik może mieć najwyżej 1 MiB.");
  try {return JSON.parse(await file.text());} catch {throw new Error(`Plik ${file.name} nie jest poprawnym JSON.`);}
}
byId("dataset-form").addEventListener("submit",event=>{event.preventDefault();action("Walidacja i zapis Twoich danych…",async()=>{
  const roads=await readGeoJSON("roads-file"), flood=await readGeoJSON("flood-file");
  const body={revision:workspace.revision,roads,flood,source:byId("data-source").value.trim(),observed_at:new Date(byId("observed-at").value).toISOString(),sample:byId("sample-data").checked};
  showWorkspace(await request(url("/datasets"),{method:"PUT",body:JSON.stringify(body)}));await refreshHistory();status("Oba zbiory zweryfikowane i zapisane. Możesz obliczyć trasę.","");
});});
function parseCoordinate(value) {
  const parts=value.split(",");if(parts.length!==2 || parts.some(p=>!p.trim() || !Number.isFinite(Number(p)))) throw new Error("Podaj współrzędne w formacie lat,lon.");
  return parts.map(Number);
}
byId("route-form").addEventListener("submit",event=>{event.preventDefault();action("Obliczanie trasy i trwały zapis wyniku…",async()=>{
  const [lat,lon]=parseCoordinate(byId("route-start").value), [endLat,endLon]=parseCoordinate(byId("route-end").value);
  const body={revision:workspace.revision,start:{lat,lon},end:{lat:endLat,lon:endLon}};
  blankMetrics();drawMap(workspace.datasets);status("Obliczanie i zapis…","pending","analysis-status");
  showResult(await request(url("/analyses"),{method:"POST",body:JSON.stringify(body)}));await refreshHistory();status("Analiza zakończona i zapisana.","");
});});
byId("refresh-history").addEventListener("click",()=>action("Odczytywanie historii…",async()=>{await refreshHistory();status("Historia odczytana.","");}));
byId("download-analysis").addEventListener("click",()=>download(currentResult,`sentinelhub-analysis-${currentResult.analysis_id}.json`));
svg.addEventListener("click",event=>{
  if(busy || !workspace?.datasets?.roads) return;
  const matrix=svg.getScreenCTM();if(!matrix) return;
  const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
  const points=roadPoints(workspace.datasets);
  const nearest=points.reduce((best,candidate)=>{
    const p=project(candidate);const d=(p[0]-point.x)**2+(p[1]-point.y)**2;return d<best.d ? {d,coord:candidate} : best;
  },{d:Infinity,coord:null});
  if(!nearest.coord) return;
  const target=document.querySelector("input[name=click-point]:checked").value;
  byId(`route-${target}`).value=[nearest.coord[1],nearest.coord[0]].join(",");
  blankMetrics();drawMap(workspace.datasets);status("Punkt zmieniony. Oblicz analizę dla nowego wejścia.","pending","analysis-status");
});
for(const id of ["route-start","route-end"]) byId(id).addEventListener("input",()=>{blankMetrics();drawMap(workspace?.datasets);status("Punkty zmienione. Oblicz nową analizę.","pending","analysis-status");});
drawMap(null);setBusy(false);
