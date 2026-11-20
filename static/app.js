"use strict";
const $ = id => document.getElementById(id);
const signals = {
  bearing_temperature_c: ["Bearing temperature", "C"], vibration_mm_s: ["Vibration", "mm/s"],
  suction_pressure_bar: ["Suction pressure", "bar"], discharge_pressure_bar: ["Discharge pressure", "bar"],
  flow_m3_h: ["Flow", "m3/h"], lubricant_pressure_bar: ["Lubricant pressure", "bar"],
  motor_current_a: ["Motor current", "A"], motor_temperature_c: ["Motor temperature", "C"],
  speed_rpm: ["Speed", "rpm"], ambient_temperature_c: ["Ambient temperature", "C"]
};
let overview = null, trendRows = [], selected = null, busy = false, details = null;
const escape = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const date = value => value ? new Date(value).toLocaleString() : "-";
const num = value => typeof value === "number" ? value.toFixed(2) : "-";
const state = alert => alert.resolved_at ? "resolved" : alert.acknowledged_at ? "acknowledged" : "active";
const badge = (text, kind) => `<span class="badge ${escape(kind)}">${escape(text)}</span>`;
const sourceUrl = (doc, revision) => `/api/documents/${encodeURIComponent(doc)}?revision=${encodeURIComponent(revision)}`;
async function api(url, options = {}) {
  const response = await fetch(url, {cache: "no-store", ...options});
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}
function showError(message) { $("error").textContent = message; $("error").hidden = !message; }
function renderOverview() {
  const active = overview.alerts.filter(a => !a.resolved_at);
  $("asset-count").textContent = overview.equipment.length;
  $("alert-count").textContent = active.length;
  $("detector").textContent = overview.detector.error ? "Degraded" : "Running";
  $("index").textContent = overview.index.ready ? `${overview.documents.length} SOPs ready` : "Unavailable";
  $("connection").textContent = "Live database connection";
  $("connection").dataset.state = "live";
  $("updated").textContent = `Updated ${date(overview.server_time)}`;
  const warnings = [overview.detector.error, overview.index.error].filter(Boolean);
  showError(warnings.join(" | "));
  $("equipment").innerHTML = overview.equipment.map((asset, index) => {
    const age = Math.max(0, (new Date(overview.server_time) - new Date(asset.measured_at)) / 1000);
    const assetAlerts = active.filter(a => a.equipment_id === asset.equipment_id);
    const level = age > 15 ? "stale" : assetAlerts.some(a => a.severity === "critical") ? "critical" : assetAlerts.length ? "warning" : "normal";
    return `<article class="asset ${level}"><div class="asset-title"><div class="asset-id"><span class="asset-no" aria-hidden="true">${String(index + 1).padStart(2, "0")}</span><div><span class="asset-type">PUMP SKID</span><strong>${escape(asset.equipment_id)}</strong></div></div>${badge(level, level)}</div>
      <div class="readings">${["bearing_temperature_c","vibration_mm_s","flow_m3_h","suction_pressure_bar"].map(field =>
        `<div class="reading"><span>${signals[field][0]}</span><strong>${num(asset[field])} <span class="unit">${signals[field][1]}</span></strong></div>`).join("")}</div>
      <div class="sample-meta"><time datetime="${escape(asset.measured_at)}">Event ${escape(date(asset.measured_at))}</time><span class="sample-age">${age.toFixed(0)}s old</span></div></article>`;
  }).join("");
  renderAlerts();
  if (!$("model").options.length) {
    for (const model of overview.models) $("model").add(new Option(model.label, model.id));
    const saved = localStorage.getItem("telemetry-model");
    if (overview.models.some(m => m.id === saved)) $("model").value = saved;
  }
  $("documents").innerHTML = overview.documents.map((doc, index) => `<article class="document">
    <div class="document-meta"><span class="document-number" aria-hidden="true">${String(index + 1).padStart(2, "0")}</span><span class="document-revision">REV ${escape(doc.revision)} / SOP</span></div>
    <h3>${escape(doc.title)}</h3><span class="document-id">${escape(doc.document_id)}</span>
    <a target="_blank" rel="noopener" href="${sourceUrl(doc.document_id,doc.revision)}">Read original procedure <span aria-hidden="true">&nearr;</span></a>
    <small>SHA-256: ${escape(doc.sha256.slice(0,20))}...</small></article>`).join("");
}
function renderAlerts() {
  const alerts = overview.alerts.filter(a => $("show-resolved").checked || !a.resolved_at);
  $("alerts").innerHTML = alerts.length ? alerts.map(a => `<button class="alert-row ${selected === a.id ? "selected" : ""}" data-alert="${escape(a.id)}">
    <div class="meta"><strong>${escape(a.equipment_id)}</strong>${badge(a.resolved_at ? "resolved" : a.severity,a.resolved_at ? "resolved" : a.severity)}</div>
    ${escape(a.title)}<small>${escape(state(a))} &middot; Opened ${escape(date(a.opened_at))}</small></button>`).join("") :
    '<div class="empty">No alerts in this view. Detection is continuous; sustained fault phases occur during each ten-minute cycle.</div>';
  for (const element of $("alerts").querySelectorAll("[data-alert]")) element.onclick = () => selectAlert(element.dataset.alert);
}
async function selectAlert(id) {
  try {
    const loaded = await api(`/api/alerts/${id}`);
    selected = id; details = loaded;
    renderAlerts(); renderDetail();
  } catch (error) { showError(error.message); }
}
function renderDetail() {
  const a = details.alert, evidence = a.evidence;
  $("detail").innerHTML = `<h3>${escape(a.equipment_id)} / ${escape(a.title)}</h3>
    ${badge(a.severity,a.severity)} <span class="facts">${escape(state(a))}</span>
    <div class="impact"><span class="field-label">Potential impact</span><p>${escape(a.impact)}</p></div>
    <div class="facts">Opened ${escape(date(a.opened_at))}<br>Latest triggering evidence ${escape(date(evidence.assessed_at))}
    <br>${escape(evidence.sample_count)} samples &middot; largest gap ${num(evidence.largest_gap_seconds)}s
    ${evidence.required_sustained_seconds ? `<br>Required continuous trigger: ${escape(evidence.required_sustained_seconds)}s<br>${evidence.triggering_conditions.map(c => `${escape(signals[c.field]?.[0] || c.field)} ${escape(c.op)} ${escape(c.value)}`).join(" AND ")}` : ""}
    ${a.resolved_at ? `<br>Resolved ${escape(date(a.resolved_at))}` : ""}</div>
    <p><a class="source-link" target="_blank" rel="noopener" href="${sourceUrl(a.source_document,a.source_revision)}">${escape(a.source_document)} rev ${escape(a.source_revision)} / ${escape(a.source_section)}</a></p>
    <div class="evidence-scroll" role="region" aria-label="Telemetry evidence" tabindex="0"><table class="evidence-table"><thead><tr><th>Observation (unit)</th><th>Latest</th><th>Min / max</th></tr></thead><tbody>
      ${Object.entries(evidence.signals || {}).map(([field,v]) => `<tr><td>${escape(signals[field]?.join(" / ") || field)}</td><td>${num(v.latest)}</td><td>${num(v.min)} / ${num(v.max)}</td></tr>`).join("")}</tbody></table></div>
    <h3>Validate related parameters</h3><p class="facts">${a.related_parameters.map(f => escape(signals[f]?.join(" / ") || f)).join(", ") || "Verify clocks, quality and communications."}</p>
    <h3>Missing observations &mdash; obtain independently</h3><ul class="facts">${a.missing_evidence.map(x => `<li>${escape(x)}</li>`).join("")}</ul>
    <div class="timeline">${details.events.map(e => `${escape(date(e.created_at))} &middot; ${escape(e.event_type)}: ${escape(e.detail)}`).join("<br>")}</div>`;
  $("diagnosis-controls").hidden = false;
  $("acknowledge").disabled = !!a.resolved_at || !!a.acknowledged_at;
  $("diagnose").disabled = busy || !overview.index.ready;
  $("diagnoses").innerHTML = details.diagnoses.map(d => `<article class="diagnosis">
    <h3>Advisory diagnosis</h3><small>${escape(d.model_id)} &middot; ${escape(date(d.created_at))} &middot; ${num(d.elapsed_seconds)}s
    <br>${d.usage ? `${d.usage.prompt_tokens} input / ${d.usage.completion_tokens} output / ${d.usage.total_tokens} total tokens` : "Model did not report token counts"}</small>
    <pre>${escape(d.result)}</pre><small>Historical evidence snapshot. Verify the interpretation; the model does not control alert severity.</small>
    ${d.sources.map(s => `<details><summary>[${escape(s.citation)}] ${escape(s.document_id)} rev ${escape(s.revision)} / ${escape(s.section)}</summary>
    <p>${escape(s.text)}</p><a class="source-link" target="_blank" rel="noopener" href="${sourceUrl(s.document_id,s.revision)}">Open source revision</a></details>`).join("")}</article>`).join("");
}
function drawChart() {
  const canvas = $("chart"), ratio = window.devicePixelRatio || 1, width = canvas.clientWidth, height = 250;
  if (!width) return;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const c = canvas.getContext("2d"); c.scale(ratio,ratio);
  const theme = getComputedStyle(document.documentElement);
  c.fillStyle = theme.getPropertyValue("--muted").trim();
  c.font = `11px ${theme.getPropertyValue("--mono").trim()}`;
  const field = $("parameter").value, values = trendRows.map(r => r[field]).filter(Number.isFinite);
  if (!values.length) { c.fillText("Waiting for telemetry history...",30,40); return; }
  const min = Math.min(...values), max = Math.max(...values), pad = Math.max((max-min)*.15,.2);
  const low = min-pad, high=max+pad, start = Date.now()-600000, end=Date.now();
  const left=55,right=width-15,top=15,bottom=215;
  c.strokeStyle=theme.getPropertyValue("--line").trim();
  for(let i=0;i<5;i++){const y=top+(bottom-top)*i/4;c.beginPath();c.moveTo(left,y);c.lineTo(right,y);c.stroke();c.fillText((high-(high-low)*i/4).toFixed(1),5,y+4);}
  c.fillText(new Date(start).toLocaleTimeString(),left,240);c.fillText(new Date(end).toLocaleTimeString(),Math.max(left,right-70),240);
  ["PUMP-001","PUMP-002","PUMP-003"].forEach((asset,i) => {
    c.beginPath();c.strokeStyle=theme.getPropertyValue(["--series-one","--series-two","--series-three"][i]).trim();c.lineWidth=2;c.setLineDash([[],[6,4],[2,4]][i]);let previous=null;
    for(const row of trendRows.filter(r=>r.equipment_id===asset)){
      const t=new Date(row.measured_at).getTime();if(!Number.isFinite(row[field])||t<start)continue;
      const x=left+(t-start)/(end-start)*(right-left),y=bottom-(row[field]-low)/(high-low)*(bottom-top);
      if(previous===null||t-previous>10000)c.moveTo(x,y);else c.lineTo(x,y);previous=t;
    }c.stroke();
  });
}
async function refresh() {
  try {
    const [data,trends] = await Promise.all([api("/api/overview"),api("/api/trends")]);
    overview=data;trendRows=trends;renderOverview();drawChart();
    if(selected&&!busy) {
      const id=selected, updated=await api(`/api/alerts/${id}`);
      if(selected===id){details=updated;renderDetail();}
    }
  } catch(error) {$("connection").textContent="Connection degraded";$("connection").dataset.state="degraded";showError(error.message);}
  finally {setTimeout(refresh,5000);}
}
$("diagnose").onclick = async () => {
  if(!selected||busy)return;
  const id=selected;busy=true;$("diagnose").disabled=true;
  $("diagnosis-status").textContent=`Running ${$("model").selectedOptions[0].text}. CPU inference may take several minutes; alerts continue independently.`;
  try {
    await api(`/api/alerts/${id}/diagnose`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:$("model").value})});
    $("diagnosis-status").textContent="Diagnosis saved with its model, evidence and SOP sources.";
    if(selected===id)await selectAlert(id);
  } catch(error){$("diagnosis-status").textContent=error.message;}
  finally{busy=false;$("diagnose").disabled=!overview?.index.ready;}
};
$("acknowledge").onclick = async () => {
  if(!selected)return;
  try{
    await api(`/api/alerts/${selected}/acknowledge`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({note:$("ack-note").value})});
    $("ack-note").value="";await selectAlert(selected);
  }catch(error){$("diagnosis-status").textContent=error.message;}
};
$("model").onchange=()=>localStorage.setItem("telemetry-model",$("model").value);
$("show-resolved").onchange=()=>overview&&renderAlerts();
for(const [field,[label,unit]] of Object.entries(signals))$("parameter").add(new Option(`${label} (${unit})`,field));
$("parameter").onchange=drawChart;
window.addEventListener("resize",drawChart);

const counts = new Intl.NumberFormat(), reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
const dataFields = Object.keys(signals);
let dataSummary = null, dataAsset = localStorage.getItem("telemetry-data-equipment"), knownRows = null, dataTimer = null;
const meters = {};
function bytes(value) {
  if (!Number.isFinite(value)) return "unavailable";
  const units = ["B","KiB","MiB","GiB","TiB"]; let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;
}
function span(milliseconds) {
  const minutes = Math.floor(milliseconds / 60000);
  if (minutes < 60) return `${minutes} min of history`;
  return minutes < 2880 ? `${(minutes / 60).toFixed(1)} h of history` : `${(minutes / 1440).toFixed(1)} days of history`;
}
function tick(id, target, reset) {
  const meter = meters[id] ??= {shown: target, frame: 0}, element = $(id);
  cancelAnimationFrame(meter.frame);
  if (reset || reduceMotion.matches || !Number.isFinite(meter.shown)) { meter.shown = target; element.textContent = counts.format(target); return; }
  const from = meter.shown, began = performance.now(), duration = 1800;
  const step = now => {
    const progress = Math.min(1, (now - began) / duration);
    meter.shown = from + (target - from) * progress;
    element.textContent = counts.format(Math.round(meter.shown));
    if (progress < 1) meter.frame = requestAnimationFrame(step);
  };
  meter.frame = requestAnimationFrame(step);
}
function renderDataSummary(reset = false) {
  const s = dataSummary, asset = s.equipment.find(a => a.equipment_id === dataAsset);
  tick("meter-total", s.total_rows, reset);
  $("meter-rate").textContent = `${counts.format(s.rows_last_minute)} stored in the last minute`;
  $("meter-asset-label").textContent = `Rows for ${asset.equipment_id}`;
  tick("meter-asset", asset.rows, reset);
  $("meter-asset-rate").textContent = `${counts.format(asset.rows_last_minute)} in the last minute`;
  $("meter-first").textContent = asset.first_sample ? date(asset.first_sample) : "-";
  $("meter-span").textContent = asset.first_sample && asset.latest_sample ? span(new Date(asset.latest_sample) - new Date(asset.first_sample)) : "";
  $("meter-latest").textContent = asset.latest_sample ? date(asset.latest_sample) : "-";
  $("meter-lag").textContent = asset.latest_sample ? `${Math.max(0, (new Date(s.server_time) - new Date(asset.latest_sample)) / 1000).toFixed(1)} s ago` : "";
  const st = s.storage, share = st.database_bytes / st.volume_bytes;
  $("meter-size").textContent = bytes(st.database_bytes);
  $("meter-retention").textContent = [st.retention && `kept ${st.retention}`, st.chunks != null && `${st.chunks} daily chunks`].filter(Boolean).join(" / ") || "\u00a0";
  $("storage-fill").style.width = `${Number.isFinite(share) ? Math.min(100, share * 100) : 0}%`;
  $("data-note").textContent = Number.isFinite(share)
    ? `Database ${bytes(st.database_bytes)} (samples ${bytes(st.samples_bytes)}) of the ${bytes(st.volume_bytes)} volume = ${(share * 100).toFixed(2)}%; excludes WAL. Retention drops expired data automatically, one whole daily chunk at a time.`
    : "Storage size is unavailable to this database role.";
}
function renderDataRows(rows, reset) {
  $("data-head").innerHTML = `<tr><th>Measured at</th><th>Seq</th><th>Stored after</th>${dataFields.map(f => `<th>${escape(signals[f][0])} (${escape(signals[f][1])})</th>`).join("")}</tr>`;
  const seen = new Set(rows.map(r => r.event_id));
  $("data-rows").innerHTML = rows.map(r => {
    const fresh = knownRows && !reset && !knownRows.has(r.event_id);
    return `<tr${fresh ? ' class="fresh"' : ""}><td>${escape(new Date(r.measured_at).toLocaleTimeString())}</td><td>${escape(r.sequence)}</td>
      <td>${Math.max(0, new Date(r.ingested_at) - new Date(r.measured_at))} ms</td>${dataFields.map(f => `<td>${num(r[f])}</td>`).join("")}</tr>`;
  }).join("") || `<tr><td colspan="${3 + dataFields.length}">No rows stored for this equipment yet.</td></tr>`;
  knownRows = seen;
}
async function refreshData(reset = false) {
  clearTimeout(dataTimer);
  try {
    if (!document.hidden) {
      dataSummary = await api("/api/data/summary");
      const select = $("data-equipment");
      if (!select.options.length) for (const a of dataSummary.equipment) select.add(new Option(a.equipment_id, a.equipment_id));
      if (!dataSummary.equipment.some(a => a.equipment_id === dataAsset)) dataAsset = dataSummary.equipment[0].equipment_id;
      select.value = dataAsset;
      const rows = await api(`/api/data/recent?equipment_id=${encodeURIComponent(dataAsset)}&limit=15`);
      renderDataSummary(reset); renderDataRows(rows, reset);
    }
  } catch (error) { $("data-note").textContent = error.message; }
  finally { dataTimer = setTimeout(refreshData, 2000); }
}
$("data-equipment").onchange = () => {
  dataAsset = $("data-equipment").value;
  localStorage.setItem("telemetry-data-equipment", dataAsset);
  refreshData(true);
};
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshData(true); });
refreshData(true);
refresh();
