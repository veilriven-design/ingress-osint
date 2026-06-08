const state = {
  target: "comprehensive",
  query: "",
  termFilter: "",
  payload: null,
  selectedId: null,
  timer: null,
  mode: "api",
};

const AUTO_REFRESH_MS = 15 * 60 * 1000;
const STATIC_SNAPSHOT_URL = "assets/dashboard-static.json";
const STATIC_MODE_LINE = "GitHub Pages scheduled snapshot + client filtering";
const TARGET_LABELS = {
  comprehensive: "Comprehensive",
  iran: "Iran",
  russia: "Russia",
  china: "China",
};
const COUNTRY_CODES = { iran: "IR", russia: "RU", china: "CN" };

const els = {
  modeLine: document.querySelector(".eyeline"),
  title: document.querySelector("#viewTitle"),
  tabs: [...document.querySelectorAll(".target-tab")],
  signalsBody: document.querySelector("#signalsBody"),
  resultCount: document.querySelector("#resultCount"),
  detailTarget: document.querySelector("#detailTarget"),
  detailBody: document.querySelector("#detailBody"),
  metricSignals: document.querySelector("#metricSignals"),
  metricArtifacts: document.querySelector("#metricArtifacts"),
  metricSources: document.querySelector("#metricSources"),
  metricUpdated: document.querySelector("#metricUpdated"),
  auditName: document.querySelector("#auditName"),
  auditMeta: document.querySelector("#auditMeta"),
  dbUrl: document.querySelector("#dbUrl"),
  countryBars: document.querySelector("#countryBars"),
  sourceList: document.querySelector("#sourceList"),
  termList: document.querySelector("#termList"),
  searchInput: document.querySelector("#searchInput"),
  refreshNow: document.querySelector("#refreshNow"),
  autoRefresh: document.querySelector("#autoRefresh"),
  seedSample: document.querySelector("#seedSample"),
  copyLive: document.querySelector("#copyLive"),
  copyIngest: document.querySelector("#copyIngest"),
  toast: document.querySelector("#toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function isUrl(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}

function short(value, limit = 80) {
  const text = String(value ?? "");
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function signalTerms(signal) {
  return [...(signal.entities || []), ...(signal.criticality_terms || [])].filter(Boolean).map(String);
}

function signalSearchText(signal) {
  return [
    signal.source,
    signal.text,
    signal.target,
    signal.status,
    signal.criticality_label,
    signal.raw_ref,
    ...signalTerms(signal),
  ]
    .join(" ")
    .toLowerCase();
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function prefersStaticSnapshot() {
  return window.location.protocol === "file:" || window.location.hostname.endsWith(".github.io");
}

function sortedCounts(values, limit = 999) {
  const counts = new Map();
  values.filter(Boolean).forEach((value) => {
    const key = String(value);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, limit);
}

function signalMatchesTarget(signal, target) {
  if (target === "comprehensive") return true;
  const signalTarget = String(signal.target || "").toLowerCase();
  const countryCode = String(signal.country_code || "").toUpperCase();
  return signalTarget === target || countryCode === COUNTRY_CODES[target];
}

function summarizeSignals(signals) {
  const terms = signals.flatMap(signalTerms);
  return {
    signals: signals.length,
    countries: sortedCounts(signals.map((signal) => signal.target || signal.country_code || "unknown")),
    sources: sortedCounts(signals.map((signal) => signal.source || "unknown"), 8),
    terms: sortedCounts(terms, 10),
    criticality: sortedCounts(signals.map((signal) => signal.criticality_label || "routine")),
    audit_logs: [],
  };
}

function payloadForCurrentTarget(payload, mode, fallbackError = null) {
  const target = TARGET_LABELS[state.target] ? state.target : "comprehensive";
  const signals =
    mode === "static" ? (payload.signals || []).filter((signal) => signalMatchesTarget(signal, target)) : payload.signals || [];
  const summary = mode === "static" ? summarizeSignals(signals) : payload.summary || summarizeSignals(signals);
  const counts =
    mode === "static"
      ? {
          artifacts: signals.length,
          provenance: signals.length,
          sightings: 0,
          sighting_artifacts: 0,
        }
      : payload.counts || {};
  return {
    ...payload,
    mode,
    fallback_error: fallbackError?.message || "",
    target,
    target_label: TARGET_LABELS[target],
    db_url:
      mode === "static"
        ? "GitHub Pages static snapshot; run local FastAPI for live SQLite data."
        : payload.db_url,
    counts,
    summary,
    signals,
  };
}

function setDashboardPayload(payload, mode, fallbackError = null) {
  state.mode = mode;
  state.payload = payloadForCurrentTarget(payload, mode, fallbackError);
  const selectedStillVisible = (state.payload.signals || []).some((signal) => signal.id === state.selectedId);
  if (!selectedStillVisible) {
    state.selectedId = state.payload.signals?.[0]?.id || null;
  }
  render();
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function criticalityInitial(signal) {
  const label = String(signal.criticality_label || "routine").toLowerCase();
  return { high: "H", elevated: "E", corroborated: "C", routine: "R" }[label] || "!";
}

function criticalityClass(signal) {
  const label = String(signal.criticality_label || "routine").toLowerCase();
  return `crit-${label}`;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("visible");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => els.toast.classList.remove("visible"), 2200);
}

function filteredSignals() {
  const signals = state.payload?.signals || [];
  const q = state.query.trim().toLowerCase();
  const activeTerm = state.termFilter.trim().toLowerCase();
  if (!q && !activeTerm) return signals;
  return signals.filter((signal) => {
    const haystack = signalSearchText(signal);
    const terms = signalTerms(signal).map((term) => term.toLowerCase());
    const matchesQuery = !q || haystack.includes(q);
    const matchesTerm = !activeTerm || terms.includes(activeTerm) || haystack.includes(activeTerm);
    return matchesQuery && matchesTerm;
  });
}

async function loadDashboard() {
  els.signalsBody.innerHTML = '<tr><td colspan="9" class="empty-state">Loading signals...</td></tr>';
  let apiError = null;
  if (!prefersStaticSnapshot()) {
    try {
      const payload = await fetchJson(`/api/dashboard?target=${encodeURIComponent(state.target)}&limit=80`);
      setDashboardPayload(payload, "api");
      return;
    } catch (error) {
      apiError = error;
    }
  }

  const payload = await fetchJson(`${STATIC_SNAPSHOT_URL}?updated=${Date.now()}`);
  setDashboardPayload(payload, "static", apiError);
}

function render() {
  renderHeader();
  renderSignals();
  renderDetail();
  renderSummaries();
}

function renderHeader() {
  const payload = state.payload;
  if (!payload) return;
  els.modeLine.textContent =
    payload.mode === "static"
      ? STATIC_MODE_LINE
      : "Local SQLite + JSONL audit surface";
  els.title.textContent =
    payload.target === "comprehensive"
      ? "Comprehensive Military Scanner"
      : `${payload.target_label} Military Watch`;
  els.metricSignals.textContent = String(payload.summary.signals || 0);
  els.metricArtifacts.textContent = String(payload.counts.artifacts || 0);
  els.metricSources.textContent = String(payload.summary.sources?.length || 0);
  els.metricUpdated.textContent = formatTime(payload.generated_at);
  els.dbUrl.textContent = payload.db_url;

  const audit = payload.summary.audit_logs?.[0];
  if (payload.mode === "static") {
    els.auditName.textContent = "Static Pages snapshot";
    els.auditMeta.textContent =
      "Refresh reloads the latest published JSON. Auto refresh checks again every 15 minutes.";
  } else if (audit) {
    els.auditName.textContent = audit.name;
    els.auditMeta.textContent = `${Math.round((audit.bytes || 0) / 1024)} KB updated ${formatTime(audit.updated_at)}`;
  } else {
    els.auditName.textContent = "No JSONL audit log yet";
    els.auditMeta.textContent = "Run watch or seed local sample data to populate the dashboard.";
  }

  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.target === state.target));
  els.seedSample.disabled = payload.mode === "static";
  els.seedSample.title =
    payload.mode === "static" ? "Sample seeding requires the local FastAPI API." : "Seed local sample data";
}

function renderSignals() {
  const signals = filteredSignals();
  const suffix = state.termFilter ? ` · term: ${state.termFilter}` : "";
  els.resultCount.textContent = `${signals.length} shown${suffix}`;
  if (!signals.some((signal) => signal.id === state.selectedId)) {
    state.selectedId = signals[0]?.id || null;
  }
  if (!signals.length) {
    els.signalsBody.innerHTML =
      '<tr><td colspan="9" class="empty-state">No matching signals. Clear the active term/search filter or run a target ingest from the CLI.</td></tr>';
    return;
  }

  els.signalsBody.innerHTML = signals
    .map((signal) => {
      const selected = signal.id === state.selectedId ? " selected" : "";
      const terms = signalTerms(signal)
        .filter(Boolean)
        .slice(0, 3)
        .join(", ");
      const sourceLink = isUrl(signal.raw_ref)
        ? `<a href="${escapeHtml(signal.raw_ref)}" target="_blank" rel="noreferrer">${escapeHtml(short(signal.source, 18))}</a>`
        : escapeHtml(short(signal.source, 18));
      const rawLink = isUrl(signal.raw_ref)
        ? `<a href="${escapeHtml(signal.raw_ref)}" target="_blank" rel="noreferrer">open</a>`
        : '<span class="muted">local</span>';
      return `<tr class="${selected}" data-id="${escapeHtml(signal.id)}">
        <td class="nowrap">${escapeHtml(signal.time_label || formatTime(signal.timestamp))}</td>
        <td><span class="crit-cell ${criticalityClass(signal)}">${escapeHtml(criticalityInitial(signal))}</span></td>
        <td class="nowrap">${escapeHtml(signal.country_code || "--")}</td>
        <td>${sourceLink}</td>
        <td class="signal-text">${escapeHtml(short(signal.text, 170))}</td>
        <td class="term-line">${escapeHtml(short(terms || signal.provenance, 70))}</td>
        <td class="nowrap">${Math.round((signal.confidence || 0) * 100)}%</td>
        <td><span class="status-pill">${escapeHtml(signal.criticality_label || signal.status)}</span></td>
        <td>${rawLink}</td>
      </tr>`;
    })
    .join("");

  els.signalsBody.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedId = row.dataset.id;
      renderSignals();
      renderDetail();
    });
  });
}

function renderDetail() {
  const signal = (state.payload?.signals || []).find((item) => item.id === state.selectedId);
  if (!signal) {
    els.detailTarget.textContent = "No selection";
    els.detailBody.className = "detail-empty";
    els.detailBody.textContent =
      "Select a row to inspect provenance, criticality reasoning, and raw source reference.";
    return;
  }
  els.detailTarget.textContent = `${signal.country_code || "--"} ${signal.criticality_label || "routine"}`;
  const terms = (signal.criticality_terms || []).join(", ") || "No configured critical terms matched.";
  const entities = (signal.entities || []).join(", ") || "None recorded";
  const sourceLink = isUrl(signal.raw_ref)
    ? `<a href="${escapeHtml(signal.raw_ref)}" target="_blank" rel="noreferrer">${escapeHtml(signal.raw_ref)}</a>`
    : escapeHtml(signal.raw_ref || "No raw reference");
  els.detailBody.className = "detail-content";
  els.detailBody.innerHTML = `
    <h4 class="detail-title">${escapeHtml(short(signal.text, 420))}</h4>
    <dl class="detail-grid">
      <dt>Source</dt><dd>${escapeHtml(signal.source)}</dd>
      <dt>Target</dt><dd>${escapeHtml(signal.target || "unknown")}</dd>
      <dt>Fetched</dt><dd>${escapeHtml(new Date(signal.timestamp).toLocaleString())}</dd>
      <dt>Confidence</dt><dd>${Math.round((signal.confidence || 0) * 100)}%</dd>
      <dt>Terms</dt><dd>${escapeHtml(terms)}</dd>
      <dt>Entities</dt><dd>${escapeHtml(entities)}</dd>
      <dt>Raw Ref</dt><dd>${sourceLink}</dd>
    </dl>
    <div class="reason-box">${escapeHtml(signal.criticality_reason || "No criticality reason recorded.")}</div>
  `;
}

function renderSummaries() {
  const payload = state.payload;
  if (!payload) return;
  const countryRows = payload.summary.countries || [];
  const total = countryRows.reduce((sum, [, count]) => sum + count, 0) || 1;
  els.countryBars.innerHTML = countryRows.length
    ? countryRows
        .map(([name, count]) => {
          const pct = Math.round((count / total) * 100);
          return `<div class="bar-row">
            <strong>${escapeHtml(String(name).toUpperCase())}</strong>
            <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
            <span>${pct}%</span>
          </div>`;
        })
        .join("")
    : '<span class="muted">No target distribution yet.</span>';

  els.sourceList.innerHTML = (payload.summary.sources || []).length
    ? payload.summary.sources
        .map(([name, count]) => `<div class="rank-row"><span>${escapeHtml(name)}</span><strong>${count}</strong></div>`)
        .join("")
    : '<span class="muted">No sources yet.</span>';

  els.termList.innerHTML = (payload.summary.terms || []).length
    ? payload.summary.terms
        .map(([term, count]) => {
          const active = state.termFilter.toLowerCase() === String(term).toLowerCase();
          return `<button class="term-chip${active ? " active" : ""}" type="button" data-term="${escapeHtml(term)}" aria-pressed="${active}">
            <span>${escapeHtml(term)}</span><strong>${count}</strong>
          </button>`;
        })
        .join("") +
      (state.termFilter
        ? `<button class="term-chip term-chip-clear" type="button" data-clear-term="true">Clear</button>`
        : "")
    : '<span class="muted">No observed terms yet.</span>';

  els.termList.querySelectorAll("button[data-term]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const nextTerm = chip.dataset.term || "";
      state.termFilter = state.termFilter.toLowerCase() === nextTerm.toLowerCase() ? "" : nextTerm;
      renderSignals();
      renderDetail();
      renderSummaries();
      showToast(state.termFilter ? `Filtering term: ${state.termFilter}` : "Term filter cleared");
    });
  });
  els.termList.querySelector("button[data-clear-term]")?.addEventListener("click", () => {
    state.termFilter = "";
    renderSignals();
    renderDetail();
    renderSummaries();
    showToast("Term filter cleared");
  });
}

async function copyText(value, label) {
  await navigator.clipboard.writeText(value);
  showToast(`${label} copied`);
}

els.tabs.forEach((tab) => {
  tab.addEventListener("click", async () => {
    state.target = tab.dataset.target;
    state.selectedId = null;
    state.termFilter = "";
    await loadDashboard().catch((error) => showToast(`Refresh failed: ${error.message}`));
  });
});

els.searchInput.addEventListener("input", () => {
  state.query = els.searchInput.value;
  renderSignals();
  renderDetail();
});

els.refreshNow.addEventListener("click", () => {
  loadDashboard().then(() => showToast("Dashboard refreshed")).catch((error) => showToast(`Refresh failed: ${error.message}`));
});

els.autoRefresh.addEventListener("change", () => {
  window.clearInterval(state.timer);
  state.timer = null;
  if (els.autoRefresh.checked) {
    state.timer = window.setInterval(() => {
      loadDashboard().catch((error) => showToast(`Auto refresh failed: ${error.message}`));
    }, AUTO_REFRESH_MS);
    showToast("Auto refresh every 15 min");
  } else {
    showToast("Auto refresh off");
  }
});

els.seedSample.addEventListener("click", async () => {
  if (state.payload?.mode === "static") {
    showToast("Sample seed is local API only");
    return;
  }
  const response = await fetch("/api/sample", { method: "POST" });
  if (!response.ok) {
    showToast("Sample seed failed");
    return;
  }
  const result = await response.json();
  showToast(`Sample seed: ${result.inserted_artifacts} artifact(s), ${result.inserted_sightings} sighting(s)`);
  await loadDashboard();
});

els.copyLive.addEventListener("click", () => {
  copyText(state.payload?.commands?.watch_live || "ingress watch --live", "Live command").catch(() =>
    showToast("Copy failed")
  );
});

els.copyIngest.addEventListener("click", () => {
  copyText(state.payload?.commands?.target_ingest || "ingress ingest target --iran --russia --china", "Ingest command").catch(
    () => showToast("Copy failed")
  );
});

loadDashboard().catch((error) => {
  els.signalsBody.innerHTML = `<tr><td colspan="9" class="empty-state">Dashboard failed: ${escapeHtml(error.message)}</td></tr>`;
  showToast("Dashboard failed to load");
});
