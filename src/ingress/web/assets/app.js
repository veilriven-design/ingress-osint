const state = {
  target: "comprehensive",
  query: "",
  payload: null,
  selectedId: null,
  timer: null,
};

const els = {
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

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
  if (!q) return signals;
  return signals.filter((signal) => {
    const haystack = [
      signal.source,
      signal.text,
      signal.target,
      signal.status,
      signal.criticality_label,
      ...(signal.entities || []),
      ...(signal.criticality_terms || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(q);
  });
}

async function loadDashboard() {
  els.signalsBody.innerHTML = '<tr><td colspan="9" class="empty-state">Loading local signals...</td></tr>';
  const response = await fetch(`/api/dashboard?target=${encodeURIComponent(state.target)}&limit=80`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  state.payload = await response.json();
  if (!state.selectedId && state.payload.signals?.length) {
    state.selectedId = state.payload.signals[0].id;
  }
  render();
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
  if (audit) {
    els.auditName.textContent = audit.name;
    els.auditMeta.textContent = `${Math.round((audit.bytes || 0) / 1024)} KB updated ${formatTime(audit.updated_at)}`;
  } else {
    els.auditName.textContent = "No JSONL audit log yet";
    els.auditMeta.textContent = "Run watch or seed local sample data to populate the dashboard.";
  }

  els.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.target === state.target));
}

function renderSignals() {
  const signals = filteredSignals();
  els.resultCount.textContent = `${signals.length} shown`;
  if (!signals.length) {
    els.signalsBody.innerHTML =
      '<tr><td colspan="9" class="empty-state">No matching signals. Seed sample data or run a target ingest from the CLI.</td></tr>';
    return;
  }

  els.signalsBody.innerHTML = signals
    .map((signal) => {
      const selected = signal.id === state.selectedId ? " selected" : "";
      const terms = [...(signal.entities || []), ...(signal.criticality_terms || [])]
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
        .map(([term, count]) => `<span class="term-chip">${escapeHtml(term)} ${count}</span>`)
        .join("")
    : '<span class="muted">No observed terms yet.</span>';
}

async function copyText(value, label) {
  await navigator.clipboard.writeText(value);
  showToast(`${label} copied`);
}

els.tabs.forEach((tab) => {
  tab.addEventListener("click", async () => {
    state.target = tab.dataset.target;
    state.selectedId = null;
    await loadDashboard().catch((error) => showToast(`Refresh failed: ${error.message}`));
  });
});

els.searchInput.addEventListener("input", () => {
  state.query = els.searchInput.value;
  renderSignals();
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
    }, 10000);
    showToast("Auto refresh on");
  } else {
    showToast("Auto refresh off");
  }
});

els.seedSample.addEventListener("click", async () => {
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
