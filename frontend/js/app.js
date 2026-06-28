/* ============================================================
   app.js — Controlador principal: router + carga + páginas.
   ============================================================ */
const { $, $$, eur, eur4, pct, num, svgIcon, toast, toastMessages, loading, animateValue } = UI;

// Rampa cromática sobria (azul marino institucional → grises) para gráficos
const BRAND_COLORS = ["#2c4a73", "#3a6098", "#5b7fa6", "#8aa3c0", "#b3c2d6", "#6b7a90"];
const PLOTLY_LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#5a667d", family: "Plus Jakarta Sans, sans-serif", size: 12 },
  margin: { t: 20, r: 10, b: 40, l: 50 },
  xaxis: { gridcolor: "rgba(15,23,42,0.07)", zerolinecolor: "rgba(15,23,42,0.12)" },
  yaxis: { gridcolor: "rgba(15,23,42,0.07)", zerolinecolor: "rgba(15,23,42,0.12)" },
  hoverlabel: { bgcolor: "#ffffff", bordercolor: "#e2e8f0", font: { color: "#1e2740", family: "Plus Jakarta Sans" } },
  transition: { duration: 400, easing: "cubic-in-out" },
};
const PLOTLY_CONFIG = { responsive: true, displayModeBar: false };

const State = {
  loaded: false,
  selectedFile: null,
  weights: null,        // payload de /api/weights
  loadedPages: {},      // qué páginas ya se cargaron una vez
};

// ============================================================
// Router
// ============================================================
const PAGES = ["dashboard", "weights", "retention", "analysis", "process", "cheques"];

function showPage(page) {
  // La página de Cheques es autónoma (re-sube su propio Excel), no exige sesión cargada.
  if (!State.loaded && page !== "cheques") {
    PAGES.forEach((p) => $(`#page-${p}`).classList.add("hidden"));
    $("#no-data").classList.remove("hidden");
    return;
  }
  $("#no-data").classList.add("hidden");
  PAGES.forEach((p) => $(`#page-${p}`).classList.toggle("hidden", p !== page));
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  loadPage(page);
}

function loadPage(page) {
  const loaders = {
    dashboard: loadDashboard,
    weights: loadWeights,
    retention: loadRetention,
    analysis: loadAnalysis,
    process: () => {}, // se carga al procesar
    cheques: () => {}, // se gestiona con sus propios eventos
  };
  (loaders[page] || (() => {}))();
}

// ============================================================
// Inicio
// ============================================================
async function init() {
  bindSidebar();
  bindUpload();
  bindWeightsPage();
  bindRetentionPage();
  bindAnalysisPage();
  bindProcessPage();
  bindChequesPage();
  UI.initTabs(document);

  try {
    const s = await API.session();
    State.loaded = s.loaded;
  } catch (e) {
    /* sin sesión todavía */
  }
  showPage("dashboard");
}

function bindSidebar() {
  $$(".nav-item").forEach((btn) =>
    btn.addEventListener("click", () => showPage(btn.dataset.page))
  );
}

// ============================================================
// Carga de archivo
// ============================================================
function bindUpload() {
  const dz = $("#dropzone");
  const input = $("#file-input");

  dz.addEventListener("click", () => input.click());
  dz.addEventListener("dragover", (e) => {
    e.preventDefault();
    dz.classList.add("drag");
  });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files.length) selectFile(input.files[0]);
  });

  $("#btn-upload").addEventListener("click", doUpload);
}

function selectFile(file) {
  State.selectedFile = file;
  $("#file-meta").classList.remove("hidden");
  $("#file-meta").innerHTML = `${svgIcon("file")} <b>${escapeHtml(file.name)}</b><br><span class="muted">${(file.size / 1024).toFixed(1)} KB</span>`;
  $("#btn-upload").classList.remove("hidden");
}

async function doUpload() {
  if (!State.selectedFile) return;
  loading(true, "Analizando y cargando archivo…");
  try {
    const res = await API.upload(State.selectedFile);
    toastMessages(res.messages);
    if (res.ok) {
      State.loaded = true;
      State.loadedPages = {};
      toast("Archivo cargado correctamente", "success");
      showPage("dashboard");
    } else {
      toast("Error al cargar el archivo", "error");
    }
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

// ============================================================
// Dashboard
// ============================================================
async function loadDashboard() {
  try {
    const d = await API.dashboard();
    animateValue($("#dash-budget"), d.total_budget, { prefix: "€", decimals: 2 });
    animateValue($("#dash-distributed"), d.total_distributed, { prefix: "€", decimals: 2 });
    animateValue($("#dash-diff"), d.difference, { prefix: "€", decimals: 2 });

    const cats = Object.entries(d.category_counts);
    Plotly.newPlot(
      "chart-categories",
      [{ type: "pie", labels: cats.map((c) => c[0]), values: cats.map((c) => c[1]), hole: 0.5,
         marker: { colors: BRAND_COLORS, line: { color: "#ffffff", width: 2 } },
         textfont: { family: "Plus Jakarta Sans" } }],
      { ...PLOTLY_LAYOUT, showlegend: true, legend: { orientation: "h", y: -0.1 } },
      PLOTLY_CONFIG
    );

    const ev = d.budget_by_event;
    Plotly.newPlot(
      "chart-budget",
      [{ type: "bar", orientation: "h",
         x: ev.map((e) => e["A REPARTIR"]), y: ev.map((e) => e.ACTES),
         marker: { color: "#2c4a73", line: { width: 0 } } }],
      { ...PLOTLY_LAYOUT, margin: { t: 20, r: 10, b: 40, l: 200 }, yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)" } },
      PLOTLY_CONFIG
    );
  } catch (e) {
    toast(e.message, "error");
  }
}

// ============================================================
// Ponderaciones
// ============================================================
const CAT_COLS = ["A", "B", "C", "D", "E"];

function bindWeightsPage() {
  $("#btn-weights-save").addEventListener("click", async () => {
    await API.saveWeights();
    toast("Ponderaciones guardadas correctamente.", "success");
  });
  $("#btn-weights-restore").addEventListener("click", async () => {
    const res = await API.restoreWeights();
    applyWeightsPayload({ ...State.weights, rows: res.rows, preview: res.preview });
    toast("Ponderaciones restauradas.", "success");
  });

  $("#auto-decimales").addEventListener("input", (e) => {
    $("#auto-decimales-val").textContent = e.target.value;
  });
  $("#auto-evento").addEventListener("change", (e) => {
    $("#btn-auto-uno").disabled = e.target.value === "";
  });
  $("#btn-auto-uno").addEventListener("click", () => runAutoA([$("#auto-evento").value]));
  $("#btn-auto-todos").addEventListener("click", () =>
    runAutoA(State.weights ? State.weights.non_official_events : [])
  );

  $("#eq-eventos").addEventListener("change", updateEqDefaultBudget);
  $("#btn-equalize").addEventListener("click", runEqualize);
}

async function loadWeights() {
  try {
    State.weights = await API.getWeights();
    renderWeightsTable();
    renderAutoEventos();
    renderEqEventos();
    renderPreview(State.weights.preview);
  } catch (e) {
    toast(e.message, "error");
  }
}

function applyWeightsPayload(payload) {
  State.weights = payload;
  renderWeightsTable();
  renderPreview(payload.preview);
}

function renderWeightsTable() {
  const table = $("#weights-table");
  const rows = State.weights.rows;
  const head = `<thead><tr><th>Acto</th>${CAT_COLS.map((c) => `<th class="num">${c}</th>`).join("")}</tr></thead>`;
  const body = rows
    .map((r, i) => {
      const inputs = CAT_COLS.map((c) => {
        const step = c === "A" ? "0.0001" : "0.001";
        return `<td class="num"><input type="number" data-row="${i}" data-col="${c}" step="${step}" min="0" max="10" value="${r[c]}" /></td>`;
      }).join("");
      return `<tr><td>${r.ACTES}</td>${inputs}</tr>`;
    })
    .join("");
  table.innerHTML = head + `<tbody>${body}</tbody>`;

  let debounce;
  table.querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", () => {
      const i = +inp.dataset.row;
      State.weights.rows[i][inp.dataset.col] = parseFloat(inp.value) || 0;
      clearTimeout(debounce);
      debounce = setTimeout(pushWeights, 400);
    })
  );
}

async function pushWeights() {
  try {
    const res = await API.putWeights(State.weights.rows);
    State.weights.rows = res.rows;
    renderPreview(res.preview);
  } catch (e) {
    toast(e.message, "error");
  }
}

function renderAutoEventos() {
  const sel = $("#auto-evento");
  const opts = ['<option value="">— (ninguno) —</option>']
    .concat(State.weights.non_official_events.map((e) => `<option value="${escapeHtml(e)}">${escapeHtml(e)}</option>`));
  sel.innerHTML = opts.join("");
  $("#btn-auto-uno").disabled = true;
}

async function runAutoA(eventos) {
  if (!eventos || !eventos.length) return;
  const decimales = +$("#auto-decimales").value;
  loading(true, "Recalculando ponderaciones…");
  try {
    const res = await API.autoA(eventos, decimales);
    State.weights.rows = res.rows;
    renderWeightsTable();
    renderPreview(res.preview);
    renderAutoResult(res);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

function renderAutoResult(res) {
  const box = $("#auto-result");
  const d = res.decimales;
  let html = "";
  if (res.cambios.length) {
    const diffTotal = res.cambios.reduce((s, c) => s + c["Diff (€)"], 0);
    const diffMax = Math.max(...res.cambios.map((c) => c["Diff (€)"]));
    html += `<div class="result-banner">${svgIcon("check")}<span>${res.cambios.length} acto(s) recalculados · Diff total = ${eur4(diffTotal)} · Diff máx/acto = ${eur4(diffMax)}</span></div>`;
    const cols = [
      { key: "Acto", label: "Acto" },
      { key: "A anterior", label: "A anterior", cls: "num", fmt: (v) => num(v, d) },
      { key: "A nuevo", label: "A nuevo", cls: "num", fmt: (v) => num(v, d) },
      { key: "B", label: "B", cls: "num", fmt: (v) => num(v, 4) },
      { key: "Asistentes", label: "Asistentes", cls: "num" },
      { key: "Neto (€)", label: "Neto", cls: "num", fmt: eur },
      { key: "Total Repartido (€)", label: "Total Repartido", cls: "num", fmt: eur },
      { key: "Diff (€)", label: "Diff", cls: "num", fmt: eur4 },
    ];
    html += '<div class="table-wrap"><table class="data-table" id="auto-result-table"></table></div>';
    box.innerHTML = html;
    UI.renderTable($("#auto-result-table"), cols, res.cambios);
  } else {
    box.innerHTML = "";
  }
  if (res.saltados.length) {
    box.innerHTML += `<div class="result-banner warn">${svgIcon("alert")}<span>${res.saltados.length} acto(s) no procesado(s): ${res.saltados.map((s) => `${escapeHtml(s.Acto)} (${escapeHtml(s.Motivo)})`).join("; ")}</span></div>`;
  }
}

function renderEqEventos() {
  const sel = $("#eq-eventos");
  sel.innerHTML = State.weights.all_events
    .map((e) => `<option value="${escapeHtml(e)}">${escapeHtml(e)}</option>`)
    .join("");
}

function selectedEqEvents() {
  return Array.from($("#eq-eventos").selectedOptions).map((o) => o.value);
}

async function updateEqDefaultBudget() {
  const eventos = selectedEqEvents();
  try {
    const res = await API.defaultBudget(eventos);
    $("#eq-total").value = res.default_budget.toFixed(2);
  } catch (e) {
    /* silencioso */
  }
}

async function runEqualize() {
  const eventos = selectedEqEvents();
  if (!eventos.length) {
    toast("Selecciona al menos un acto.", "warning");
    return;
  }
  const total = parseFloat($("#eq-total").value) || 0;
  loading(true, "Calculando presupuestos…");
  try {
    const res = await API.equalize(eventos, total);
    renderPreview(res.preview);
    const box = $("#eq-result");
    box.innerHTML = `<div class="result-banner">${svgIcon("check")}<span>Presupuestos actualizados · Valor unitario común: ${eur4(res.valor_unitario)}</span></div>`;
    if (res.changes_log.length) {
      box.innerHTML += '<div class="table-wrap"><table class="data-table" id="eq-result-table"></table></div>';
      UI.renderTable($("#eq-result-table"), [
        { key: "Acto", label: "Acto" },
        { key: "Anterior", label: "Anterior", cls: "num", fmt: eur },
        { key: "Nuevo", label: "Nuevo", cls: "num", fmt: eur },
        { key: "Cambio", label: "Cambio", cls: "num", fmt: eur, classer: (v) => (v < 0 ? "neg" : "pos") },
      ], res.changes_log);
    }
    toast("Presupuestos actualizados.", "success");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

function renderPreview(preview) {
  if (!preview) return;
  const m = preview.metrics;
  const diffCls = Math.abs(m.total_diff) < 1 ? "good" : m.total_diff < 0 ? "bad" : "";
  const diffNote = Math.abs(m.total_diff) < 1 ? "óptima" : eur(m.total_diff);
  $("#weights-metrics").innerHTML = `
    ${metricCard("wallet", "Presupuesto total", eur(m.total_budget))}
    ${metricCard("bank", "Retención banda", eur(m.total_retention))}
    ${metricCard("users", "Neto músicos", eur(m.total_net))}
    ${metricCard("scale", "Diferencia", eur(m.total_diff), `<span class="metric-delta ${diffCls}">${diffNote}</span>`)}
  `;

  UI.renderTable($("#preview-comp-table"), [
    { key: "Acto", label: "Acto" },
    { key: "Presupuesto", label: "Presupuesto", cls: "num", fmt: eur },
    { key: "Retencion_PCT", label: "Retención %", cls: "num", fmt: (v) => pct(v) },
    { key: "Retencion_Amount", label: "Retención €", cls: "num", fmt: eur },
    { key: "Neto", label: "Neto músicos", cls: "num", fmt: eur },
    { key: "Total_Repartido", label: "Total repartido", cls: "num", fmt: eur },
    { key: "Diferencia", label: "Diferencia", cls: "num", fmt: eur, classer: (v) => (v < -0.005 ? "neg" : "") },
  ], preview.comparison);

  UI.renderTable($("#preview-earn-table"), [
    { key: "Acto", label: "Acto" },
    { key: "Original", label: "Original", cls: "num", fmt: eur },
    { key: "Retención %", label: "Retención %", cls: "num", fmt: (v) => pct(v) },
    { key: "Neto", label: "Neto", cls: "num", fmt: eur },
    { key: "A", label: "A", cls: "num", fmt: eur },
    { key: "B", label: "B", cls: "num", fmt: eur },
    { key: "C", label: "C", cls: "num", fmt: eur },
    { key: "D", label: "D", cls: "num", fmt: eur },
    { key: "E", label: "E", cls: "num", fmt: eur },
  ], preview.earnings);
}

// ============================================================
// Retención de banda
// ============================================================
function bindRetentionPage() {
  $("#btn-ret-save").addEventListener("click", async () => {
    await API.saveRetention();
    toast("Configuración de retención guardada.", "success");
  });
  $("#btn-ret-reset").addEventListener("click", async () => {
    const res = await API.resetRetention();
    renderRetention(res);
    toast("Configuración reseteada a 0%.", "success");
  });
  $("#btn-ret-template").addEventListener("click", async () => {
    const res = await API.templateRetention();
    renderRetention(res);
    toast("Plantilla aplicada.", "success");
  });
}

async function loadRetention() {
  try {
    renderRetention(await API.getRetention());
  } catch (e) {
    toast(e.message, "error");
  }
}

function renderRetention(payload) {
  const table = $("#retention-table");
  const head = `<thead><tr><th>Acto</th><th class="num">Retención (%)</th><th>Descripción</th></tr></thead>`;
  const body = payload.rows
    .map((r, i) => `
      <tr>
        <td>${escapeHtml(r.ACTES)}</td>
        <td class="num"><input type="number" data-row="${i}" data-field="BANDA_PORCENTAJE" min="0" max="100" step="0.5" value="${r.BANDA_PORCENTAJE}" /></td>
        <td><input type="text" data-row="${i}" data-field="DESCRIPCION" value="${escapeHtml(r.DESCRIPCION)}" /></td>
      </tr>`)
    .join("");
  table.innerHTML = head + `<tbody>${body}</tbody>`;

  State.retentionRows = payload.rows;
  let debounce;
  table.querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", () => {
      const i = +inp.dataset.row;
      const field = inp.dataset.field;
      State.retentionRows[i][field] = field === "BANDA_PORCENTAJE" ? (parseFloat(inp.value) || 0) : inp.value;
      clearTimeout(debounce);
      debounce = setTimeout(pushRetention, 400);
    })
  );

  renderRetentionImpact(payload.impact);
}

async function pushRetention() {
  try {
    const res = await API.putRetention(State.retentionRows);
    State.retentionRows = res.rows;
    renderRetentionImpact(res.impact);
  } catch (e) {
    toast(e.message, "error");
  }
}

function renderRetentionImpact(impact) {
  $("#retention-metrics").innerHTML = `
    ${metricCard("wallet", "Total Presupuesto", eur(impact.total_budget))}
    ${metricCard("bank", "Total Retención Banda", eur(impact.total_retention))}
    ${metricCard("users", "Neto para Músicos", eur(impact.net_for_musicians))}
  `;
  const box = $("#retention-breakdown");
  if (impact.breakdown.length) {
    box.innerHTML = '<h4>Desglose de Retenciones</h4><div class="table-wrap"><table class="data-table" id="ret-breakdown-table"></table></div>';
    UI.renderTable($("#ret-breakdown-table"), [
      { key: "Acto", label: "Acto" },
      { key: "Presupuesto", label: "Presupuesto", cls: "num", fmt: eur },
      { key: "Retención %", label: "Retención %", cls: "num", fmt: (v) => pct(v) },
      { key: "Retención €", label: "Retención €", cls: "num", fmt: eur },
      { key: "Neto Músicos", label: "Neto Músicos", cls: "num", fmt: eur },
    ], impact.breakdown);
  } else {
    box.innerHTML = `<p class="muted note">${svgIcon("info")}<span>No hay retenciones configuradas — todo el presupuesto se repartirá.</span></p>`;
  }
}

// ============================================================
// Análisis por actos
// ============================================================
function bindAnalysisPage() {
  $("#analysis-evento").addEventListener("change", (e) => loadEventAnalysis(e.target.value));
}

async function loadAnalysis() {
  try {
    const { events } = await API.events();
    const sel = $("#analysis-evento");
    sel.innerHTML = events.map((e) => `<option value="${escapeHtml(e)}">${escapeHtml(e)}</option>`).join("");
    if (events.length) loadEventAnalysis(events[0]);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadEventAnalysis(event) {
  if (!event) return;
  try {
    const data = await API.eventAnalysis(event);
    const cats = data.categorias;
    if (cats.length) {
      Plotly.newPlot(
        "analysis-chart",
        [{ type: "bar", x: cats.map((c) => c.Categoria), y: cats.map((c) => c.Count), marker: { color: "#2c4a73" } }],
        { ...PLOTLY_LAYOUT },
        PLOTLY_CONFIG
      );
      UI.renderTable($("#analysis-table"), [
        { key: "Categoria", label: "Categoría" },
        { key: "Count", label: "Cantidad", cls: "num" },
        { key: "Musicians", label: "Músicos", fmt: (v) => (v || []).join(", ") },
      ], cats);
    } else {
      $("#analysis-chart").innerHTML = "";
      $("#analysis-table").innerHTML = "<tbody><tr><td>No hay asistencia para este acto</td></tr></tbody>";
    }

    const b = data.presupuesto;
    $("#analysis-budget").innerHTML = b
      ? `${metricCard("banknote", "Cobrado", eur(b.COBRAT))}${metricCard("send", "Gastos Alquiler", eur(b.LLOGATS))}${metricCard("send", "Transporte", eur(b.TRANSPORT))}${metricCard("wallet", "A Repartir", eur(b["A REPARTIR"]))}`
      : '<p class="muted">No hay información presupuestaria para este acto</p>';
  } catch (e) {
    toast(e.message, "error");
  }
}

// ============================================================
// Procesar y descargar
// ============================================================
function bindProcessPage() {
  $$('input[name="penalty"]').forEach((r) =>
    r.addEventListener("change", () => {
      $("#penalty-fixed").classList.toggle("hidden", $('input[name="penalty"]:checked').value !== "fixed");
    })
  );
  $$('input[name="penalty-type"]').forEach((r) =>
    r.addEventListener("change", () => {
      const byCat = $('input[name="penalty-type"]:checked').value === "by_category";
      $("#penalty-bycat").classList.toggle("hidden", !byCat);
      $("#penalty-uniform").classList.toggle("hidden", byCat);
    })
  );

  $("#btn-process").addEventListener("click", runProcess);
  $("#btn-export-full").addEventListener("click", () => download("full"));
  $("#btn-export-basic").addEventListener("click", () => download("basic"));
}

function buildPenaltyPayload() {
  const criteria = $('input[name="penalty"]:checked').value;
  const payload = { penalty_criteria: criteria, fixed_penalty_amount: 0, category_penalties: null };
  if (criteria === "fixed") {
    const type = $('input[name="penalty-type"]:checked').value;
    if (type === "uniform") {
      payload.fixed_penalty_amount = parseFloat($("#penalty-uniform-amount").value) || 0;
    } else {
      const cp = {};
      $$(".pen-cat").forEach((inp) => (cp[inp.dataset.cat] = parseFloat(inp.value) || 0));
      payload.category_penalties = cp;
    }
  }
  return payload;
}

async function runProcess() {
  loading(true, "Procesando datos…");
  try {
    const res = await API.process(buildPenaltyPayload());
    toastMessages(res.messages);
    if (!res.ok) {
      toast("Error procesando datos", "error");
      return;
    }
    renderProcessResults(res);
    $("#process-results").classList.remove("hidden");
    toast("Datos procesados correctamente", "success");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

function renderProcessResults(res) {
  const s = res.summary;
  const totalLabel = s.has_penalties ? "Total Final" : "Total Distribuido";
  const totalVal = s.has_penalties ? s.total_final : s.total_distributed;
  const avgLabel = s.has_penalties ? "Pago Final Promedio" : "Pago Promedio";
  $("#process-metrics").innerHTML = `
    ${metricCard("users", "Músicos con Ganancias", s.musicians_paid)}
    ${metricCard("wallet", totalLabel, eur(totalVal))}
    ${metricCard("bank", "Retención Banda", eur(s.total_band_retention))}
    ${metricCard("banknote", avgLabel, eur(s.avg_payment))}
  `;

  $("#process-penalty-metrics").innerHTML =
    s.has_penalties
      ? `<div class="card"><h3>${svgIcon("alert")} Resumen de Penalizaciones</h3><div class="metrics-grid">
          ${metricCard("scale", "Total Penalizaciones", eur(s.total_penalties))}
          ${metricCard("users", "Músicos Penalizados", s.musicians_penalized)}
          ${metricCard("scale", "Penalización Promedio", eur(s.avg_penalty))}
        </div></div>`
      : "";

  const t = res.tables;
  UI.renderRecords($("#res-ms"), t.musician_summary, ["Importe_Individual", "Penalizacion_Total", "Importe_Final"]);
  UI.renderRecords($("#res-bc"), t.budget_comparison, ["A REPARTIR", "Distribuido_Real", "Banda_Retencion_Amount", "Neto_Para_Musicos", "Diferencia"]);
  UI.renderRecords($("#res-mc"), t.musicians_by_category, []);
  UI.renderTable($("#res-rd"), [
    { key: "Acto", label: "Acto" },
    { key: "Presupuesto_Original", label: "Presupuesto Original", cls: "num", fmt: eur },
    { key: "Retencion_PCT", label: "Retención %", cls: "num", fmt: (v) => pct(v) },
    { key: "Retencion_Amount", label: "Retención €", cls: "num", fmt: eur },
    { key: "Neto", label: "Neto para Músicos", cls: "num", fmt: eur },
  ], t.retention_detail);
}

function download(kind) {
  window.location.href = API.exportUrl(kind);
}

// ============================================================
// Cheques (PDF)
// ============================================================
const Cheques = { file: null, cal: null, defaults: null };
const CAL_STORAGE_KEY = "chq_calibration";

function bindChequesPage() {
  const dz = $("#chq-dropzone");
  const input = $("#chq-file-input");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    if (e.dataTransfer.files.length) selectChequeFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files.length) selectChequeFile(input.files[0]);
  });

  // Fecha por defecto: hoy
  $("#chq-fecha").value = new Date().toISOString().slice(0, 10);

  $("#btn-chq-pdf").addEventListener("click", generateChequesPdf);
  $("#btn-chq-calib").addEventListener("click", downloadCalibration);
  $("#btn-chq-ejemplo").addEventListener("click", downloadEjemplo);
  $("#btn-cal-reset").addEventListener("click", resetCalibration);
  $("#cal-offset-x").addEventListener("input", (e) => {
    Cheques.cal.offset_x = parseFloat(e.target.value) || 0;
    saveStoredCal();
  });
  $("#cal-offset-y").addEventListener("input", (e) => {
    Cheques.cal.offset_y = parseFloat(e.target.value) || 0;
    saveStoredCal();
  });
  $("#cal-drift-x").addEventListener("input", (e) => {
    Cheques.cal.drift_x = parseFloat(e.target.value) || 0;
    saveStoredCal();
  });
  $("#cal-drift-y").addEventListener("input", (e) => {
    Cheques.cal.drift_y = parseFloat(e.target.value) || 0;
    saveStoredCal();
  });

  initChequesCalibration();
}

// ---- Calibración (persistida en localStorage) ----
function cloneCal(d) {
  return {
    offset_x: d.offset_x || 0,
    offset_y: d.offset_y || 0,
    drift_x: d.drift_x || 0,
    drift_y: d.drift_y || 0,
    fields: Object.fromEntries(
      Object.entries(d.fields || {}).map(([k, v]) => [k, { x: v.x, y: v.y, size: v.size }])
    ),
  };
}

function buildCal(defaults, stored) {
  const base = cloneCal(defaults);
  if (!stored) return base;
  if (stored.offset_x != null) base.offset_x = stored.offset_x;
  if (stored.offset_y != null) base.offset_y = stored.offset_y;
  if (stored.drift_x != null) base.drift_x = stored.drift_x;
  if (stored.drift_y != null) base.drift_y = stored.drift_y;
  Object.keys(base.fields).forEach((k) => {
    const sf = stored.fields && stored.fields[k];
    if (sf) {
      if (sf.x != null) base.fields[k].x = sf.x;
      if (sf.y != null) base.fields[k].y = sf.y;
      if (sf.size != null) base.fields[k].size = sf.size;
    }
  });
  return base;
}

function loadStoredCal() {
  try {
    const s = localStorage.getItem(CAL_STORAGE_KEY);
    return s ? JSON.parse(s) : null;
  } catch (_) { return null; }
}

function saveStoredCal() {
  try { localStorage.setItem(CAL_STORAGE_KEY, JSON.stringify(Cheques.cal)); } catch (_) {}
}

async function initChequesCalibration() {
  let defaults;
  try {
    defaults = await API.chequesCalibDefaults();
  } catch (e) {
    defaults = { offset_x: 0, offset_y: 0, fields: {}, labels: {} };
  }
  Cheques.defaults = defaults;
  Cheques.cal = buildCal(defaults, loadStoredCal());
  syncCalInputs();
  renderCalFields();
}

function syncCalInputs() {
  $("#cal-offset-x").value = Cheques.cal.offset_x;
  $("#cal-offset-y").value = Cheques.cal.offset_y;
  $("#cal-drift-x").value = Cheques.cal.drift_x;
  $("#cal-drift-y").value = Cheques.cal.drift_y;
}

function renderCalFields() {
  const f = Cheques.cal.fields;
  const labels = (Cheques.defaults && Cheques.defaults.labels) || {};
  const keys = Object.keys(f);
  const head = `<thead><tr><th>Campo</th><th class="num">X (mm)</th><th class="num">Y (mm)</th><th class="num">Tamaño (pt)</th></tr></thead>`;
  const body = keys.map((k) => {
    const v = f[k];
    return `<tr><td>${escapeHtml(labels[k] || k)}</td>
      <td class="num"><input type="number" step="0.5" data-key="${k}" data-prop="x" value="${v.x}" /></td>
      <td class="num"><input type="number" step="0.5" data-key="${k}" data-prop="y" value="${v.y}" /></td>
      <td class="num"><input type="number" step="1" min="6" data-key="${k}" data-prop="size" value="${v.size}" /></td>
    </tr>`;
  }).join("");
  const table = $("#cal-fields-table");
  table.innerHTML = head + `<tbody>${body}</tbody>`;
  table.querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", () => {
      Cheques.cal.fields[inp.dataset.key][inp.dataset.prop] = parseFloat(inp.value) || 0;
      saveStoredCal();
    })
  );
}

function resetCalibration() {
  Cheques.cal = cloneCal(Cheques.defaults);
  try { localStorage.removeItem(CAL_STORAGE_KEY); } catch (_) {}
  syncCalInputs();
  renderCalFields();
  toast("Calibración restablecida a los valores por defecto.", "success");
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function downloadCalibration() {
  loading(true, "Generando hoja de calibración…");
  try {
    const blob = await API.chequesCalibPdf(Cheques.cal, $("#chq-dorso").checked);
    triggerDownload(blob, "cheques_calibracion.pdf");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

async function downloadEjemplo() {
  loading(true, "Generando cheque de ejemplo…");
  try {
    const blob = await API.chequesEjemplo({
      fecha: $("#chq-fecha").value || undefined,
      serie_inicial: $("#chq-serie").value.trim() || undefined,
      calibration: Cheques.cal,
      incluir_dorso: $("#chq-dorso").checked,
    });
    triggerDownload(blob, "cheques_ejemplo.pdf");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

async function selectChequeFile(file) {
  Cheques.file = file;
  $("#chq-file-meta").classList.remove("hidden");
  $("#chq-file-meta").innerHTML = `${svgIcon("file")} <b>${escapeHtml(file.name)}</b><br><span class="muted">${(file.size / 1024).toFixed(1)} KB</span>`;
  loading(true, "Leyendo importes del Excel…");
  try {
    const res = await API.chequesPreview(file);
    renderChequesPreview(res);
    $("#chq-preview-card").classList.remove("hidden");
    $("#chq-form-card").classList.remove("hidden");
    if (res.info.warnings && res.info.warnings.length) {
      res.info.warnings.forEach((w) => toast(w, "warning"));
    }
  } catch (e) {
    Cheques.file = null;
    $("#chq-preview-card").classList.add("hidden");
    $("#chq-form-card").classList.add("hidden");
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

function renderChequesPreview(res) {
  $("#chq-metrics").innerHTML = `
    ${metricCard("banknote", "Cheques a generar", res.count)}
    ${metricCard("wallet", "Importe total", eur(res.total))}
    ${metricCard("file", "Hoja / columna", `${escapeHtml(res.info.sheet)} · ${escapeHtml(res.info.amount_col)}`)}
  `;
  UI.renderTable($("#chq-preview-table"), [
    { key: "nombre", label: "Músico" },
    { key: "importe", label: "Importe (€)", cls: "num" },
    { key: "letras", label: "En letra (valencià)" },
  ], res.items);
}

async function generateChequesPdf() {
  if (!Cheques.file) {
    toast("Sube primero el Excel editado.", "warning");
    return;
  }
  const fecha = $("#chq-fecha").value;
  if (!fecha) {
    toast("Indica la fecha de emisión.", "warning");
    return;
  }
  const serie = $("#chq-serie").value.trim();
  loading(true, "Generando PDF de cheques…");
  try {
    const incluirDorso = $("#chq-dorso").checked;
    const blob = await API.chequesPdf(Cheques.file, fecha, serie, Cheques.cal, incluirDorso);
    triggerDownload(blob, "cheques.pdf");
    toast("PDF de cheques generado.", "success");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    loading(false);
  }
}

// ============================================================
// Utilidades
// ============================================================
// metricCard(iconName, label, value, extra) — iconName referencia un símbolo del sprite (#i-*).
function metricCard(iconName, label, value, extra = "") {
  const head = `<div class="metric-head">${iconName ? `<div class="metric-icon">${svgIcon(iconName)}</div>` : ""}<div class="metric-label">${label}</div></div>`;
  return `<div class="metric">${head}<div class="metric-value">${value}</div>${extra}</div>`;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

document.addEventListener("DOMContentLoaded", init);
