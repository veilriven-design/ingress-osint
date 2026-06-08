const state = {
  target: "comprehensive",
  query: "",
  termFilter: "",
  payload: null,
  networkPayload: null,
  selectedId: null,
  timer: null,
  mode: "api",
  lastRefreshAt: null,
  lastSnapshotKey: "",
  lastSnapshotStatus: "",
  networkError: "",
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
  metricNetwork: document.querySelector("#metricNetwork"),
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
  seedNetwork: document.querySelector("#seedNetwork"),
  copyLive: document.querySelector("#copyLive"),
  copyIngest: document.querySelector("#copyIngest"),
  copyNetwork: document.querySelector("#copyNetwork"),
  copyNetworkImport: document.querySelector("#copyNetworkImport"),
  networkResultCount: document.querySelector("#networkResultCount"),
  networkCount: document.querySelector("#networkCount"),
  networkDomains: document.querySelector("#networkDomains"),
  networkProtocols: document.querySelector("#networkProtocols"),
  networkUpdated: document.querySelector("#networkUpdated"),
  networkHighlights: document.querySelector("#networkHighlights"),
  networkBody: document.querySelector("#networkBody"),
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

function dbUrlForCommands(payload) {
  const dbUrl = payload?.db_url;
  return typeof dbUrl === "string" && dbUrl.startsWith("sqlite") ? dbUrl : "sqlite:///./data/ingress.db";
}

function networkCommandForTarget(target, dbUrl) {
  const targetFlag = target === "comprehensive" ? "" : ` --${target}`;
  return `ingress monitor network${targetFlag} --db-url ${dbUrl}`;
}

function networkImportCommand(dbUrl) {
  return `ingress monitor network --input telemetry.jsonl --db-url ${dbUrl}`;
}

function networkSummary(observations) {
  return {
    observations: observations.length,
    domains: sortedCounts(
      observations.map((observation) => observation.network?.remote_domain || observation.network?.remote_host || "unknown"),
      10
    ),
    protocols: sortedCounts(observations.map((observation) => observation.network?.protocol || "unknown")),
    remote_ports: sortedCounts(observations.map((observation) => observation.network?.remote_port || "unknown"), 10),
    processes: sortedCounts(observations.map((observation) => observation.network?.process || "unknown"), 10),
  };
}

function networkSearchText(observation) {
  const network = observation.network || {};
  return [
    signalSearchText(observation),
    network.remote_host,
    network.remote_domain,
    network.remote_port,
    network.local_host,
    network.local_port,
    network.protocol,
    network.process,
    network.state,
    network.ja3,
    network.dns_query,
    ...(network.matched_network_indicators || []),
  ]
    .join(" ")
    .toLowerCase();
}

function formatBytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "";
  if (number < 1024) return `${Math.round(number)} B`;
  if (number < 1024 * 1024) return `${Math.round(number / 1024)} KB`;
  return `${(number / (1024 * 1024)).toFixed(1)} MB`;
}

function formatNetworkRemote(observation) {
  const network = observation.network || {};
  const remote = network.remote_domain || network.remote_host || observation.raw_ref || "unknown";
  return network.remote_port ? `${remote}:${network.remote_port}` : remote;
}

function formatNetworkFlow(network) {
  const sent = formatBytes(network?.bytes?.sent);
  const received = formatBytes(network?.bytes?.received);
  const parts = [];
  if (sent) parts.push(`sent ${sent}`);
  if (received) parts.push(`recv ${received}`);
  if (network?.ja3) parts.push(`ja3 ${short(network.ja3, 10)}`);
  if (network?.dns_query) parts.push(`dns ${short(network.dns_query, 22)}`);
  return parts.join(" / ") || "metadata";
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatTimeWithSeconds(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "--";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function snapshotKey(payload) {
  const ids = (payload.signals || []).slice(0, 8).map((signal) => signal.id).join(",");
  return [payload.generated_at || "", payload.summary?.signals || 0, ids].join("|");
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

function networkPayloadForCurrentTarget(payload, mode, fallbackError = null) {
  const target = TARGET_LABELS[state.target] ? state.target : "comprehensive";
  const dbUrl = dbUrlForCommands(state.payload || payload);
  const rawObservations = payload?.observations || [];
  const observations =
    mode === "static"
      ? rawObservations.filter((observation) => signalMatchesTarget(observation, target))
      : rawObservations;
  const summary = payload?.summary && mode !== "static" ? payload.summary : networkSummary(observations);
  const commands = {
    monitor_network:
      payload?.commands?.monitor_network || state.payload?.commands?.network_monitor || networkCommandForTarget(target, dbUrl),
    import_jsonl: payload?.commands?.import_jsonl || networkImportCommand(dbUrl),
  };
  return {
    status: payload?.status || (fallbackError ? "degraded" : "ok"),
    version: payload?.version || state.payload?.version || "",
    target,
    target_label: TARGET_LABELS[target],
    generated_at: payload?.generated_at || state.payload?.generated_at || new Date().toISOString(),
    db_url: payload?.db_url || state.payload?.db_url || dbUrl,
    mode,
    fallback_error: fallbackError?.message || "",
    summary,
    commands,
    observations,
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

function setNetworkPayload(payload, mode, fallbackError = null) {
  state.networkPayload = networkPayloadForCurrentTarget(payload || {}, mode, fallbackError);
  state.networkError = fallbackError?.message || "";
  renderNetwork();
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

function setRefreshButtonLoading(isLoading) {
  els.refreshNow.disabled = isLoading;
  els.refreshNow.classList.toggle("loading", isLoading);
  els.refreshNow.setAttribute("aria-busy", isLoading ? "true" : "false");
}

function refreshMessage(mode, reason, changed) {
  const payload = state.payload;
  const count = payload?.summary?.signals || 0;
  if (mode === "static") {
    if (changed) return `New Pages snapshot loaded: ${count} signal(s)`;
    if (reason === "auto") return `Auto checked Pages snapshot: ${count} signal(s)`;
    if (reason === "manual") return `Pages snapshot checked: ${count} signal(s), no newer publish yet`;
    return `Pages snapshot loaded: ${count} signal(s)`;
  }
  return `Dashboard refreshed: ${count} signal(s)`;
}

async function loadDashboard({ reason = "initial" } = {}) {
  els.signalsBody.innerHTML = '<tr><td colspan="9" class="empty-state">Loading signals...</td></tr>';
  els.networkBody.innerHTML = '<tr><td colspan="5" class="empty-state">Loading network telemetry...</td></tr>';
  const previousSnapshotKey = state.lastSnapshotKey;
  let apiError = null;
  if (!prefersStaticSnapshot()) {
    try {
      const payload = await fetchJson(`/api/dashboard?target=${encodeURIComponent(state.target)}&limit=80`);
      state.lastRefreshAt = new Date().toISOString();
      state.lastSnapshotStatus = "";
      setDashboardPayload(payload, "api");
      await loadNetworkPayload({ mode: "api" });
      return { mode: "api", changed: true, message: refreshMessage("api", reason, true) };
    } catch (error) {
      apiError = error;
    }
  }

  const payload = await fetchJson(`${STATIC_SNAPSHOT_URL}?updated=${Date.now()}`);
  const currentSnapshotKey = snapshotKey(payload);
  const changed = Boolean(previousSnapshotKey && previousSnapshotKey !== currentSnapshotKey);
  state.lastRefreshAt = new Date().toISOString();
  state.lastSnapshotKey = currentSnapshotKey;
  state.lastSnapshotStatus =
    reason === "manual"
      ? changed
        ? "New snapshot loaded."
        : "Snapshot checked; no newer Pages publish yet."
      : reason === "auto"
        ? changed
          ? "Auto refresh loaded a new snapshot."
          : "Auto refresh checked; no newer Pages publish yet."
        : "Snapshot loaded.";
  setDashboardPayload(payload, "static", apiError);
  setNetworkPayload(payload.network || {}, "static", apiError);
  return { mode: "static", changed, message: refreshMessage("static", reason, changed) };
}

async function loadNetworkPayload({ mode = state.mode } = {}) {
  if (mode !== "api" || prefersStaticSnapshot()) {
    setNetworkPayload({}, "static");
    return;
  }
  try {
    const payload = await fetchJson(`/api/network?target=${encodeURIComponent(state.target)}&limit=60`);
    setNetworkPayload(payload, "api");
  } catch (error) {
    setNetworkPayload({}, "api", error);
  }
}

function render() {
  renderHeader();
  renderSignals();
  renderNetwork();
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
  els.metricNetwork.textContent = String(state.networkPayload?.summary?.observations || 0);
  els.metricArtifacts.textContent = String(payload.counts.artifacts || 0);
  els.metricSources.textContent = String(payload.summary.sources?.length || 0);
  els.metricUpdated.textContent = formatTime(payload.generated_at);
  els.dbUrl.textContent = payload.db_url;

  const audit = payload.summary.audit_logs?.[0];
  if (payload.mode === "static") {
    els.auditName.textContent = "Static Pages snapshot";
    const generatedAt = formatTimeWithSeconds(payload.generated_at);
    const checkedAt = state.lastRefreshAt ? formatTimeWithSeconds(state.lastRefreshAt) : "--";
    els.auditMeta.textContent =
      `${state.lastSnapshotStatus} Last checked ${checkedAt}; snapshot generated ${generatedAt}; scheduled source refresh every 15 minutes.`;
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
  els.seedNetwork.disabled = payload.mode === "static";
  els.seedNetwork.title =
    payload.mode === "static" ? "Network sample seeding requires the local FastAPI API." : "Seed local network telemetry";
}

function filteredNetworkObservations() {
  const observations = state.networkPayload?.observations || [];
  const q = state.query.trim().toLowerCase();
  const activeTerm = state.termFilter.trim().toLowerCase();
  if (!q && !activeTerm) return observations;
  return observations.filter((observation) => {
    const haystack = networkSearchText(observation);
    const terms = signalTerms(observation).map((term) => term.toLowerCase());
    const indicators = (observation.network?.matched_network_indicators || []).map((term) => String(term).toLowerCase());
    const matchesQuery = !q || haystack.includes(q);
    const matchesTerm =
      !activeTerm || terms.includes(activeTerm) || indicators.includes(activeTerm) || haystack.includes(activeTerm);
    return matchesQuery && matchesTerm;
  });
}

function renderNetwork() {
  const payload = state.networkPayload;
  if (!payload) {
    els.metricNetwork.textContent = "0";
    return;
  }
  const observations = filteredNetworkObservations();
  const summary = payload.summary || networkSummary(observations);
  const errorSuffix = payload.fallback_error ? " / network API unavailable" : "";
  els.metricNetwork.textContent = String(summary.observations || 0);
  els.networkResultCount.textContent = `${observations.length} shown${errorSuffix}`;
  els.networkCount.textContent = String(summary.observations || 0);
  els.networkDomains.textContent = String(summary.domains?.length || 0);
  els.networkProtocols.textContent = String(summary.protocols?.length || 0);
  els.networkUpdated.textContent = formatTime(payload.generated_at);

  const highlights = [
    ...(summary.domains || []).slice(0, 3).map(([name, count]) => ["domain", name, count]),
    ...(summary.protocols || []).slice(0, 2).map(([name, count]) => ["proto", name, count]),
    ...(summary.processes || []).slice(0, 2).map(([name, count]) => ["proc", name, count]),
  ];
  els.networkHighlights.innerHTML = highlights.length
    ? highlights
        .map(
          ([kind, name, count]) =>
            `<span class="telemetry-pill"><strong>${escapeHtml(kind)}</strong>${escapeHtml(short(name, 28))}<em>${count}</em></span>`
        )
        .join("")
    : '<span class="muted">No network telemetry observations yet.</span>';

  if (!observations.length) {
    const message = payload.fallback_error
      ? `Network API unavailable: ${payload.fallback_error}`
      : "No network telemetry observations match the current target/search.";
    els.networkBody.innerHTML = `<tr><td colspan="5" class="empty-state">${escapeHtml(message)}</td></tr>`;
    return;
  }

  els.networkBody.innerHTML = observations
    .map((observation) => {
      const selected = observation.id === state.selectedId ? " selected" : "";
      const network = observation.network || {};
      const indicators = (network.matched_network_indicators || []).slice(0, 2).join(", ");
      return `<tr class="${selected}" data-id="${escapeHtml(observation.id)}">
        <td><strong>${escapeHtml(short(formatNetworkRemote(observation), 42))}</strong><span>${escapeHtml(formatTime(observation.timestamp))}</span></td>
        <td class="nowrap">${escapeHtml((network.protocol || "--").toUpperCase())}</td>
        <td>${escapeHtml(short(network.process || "--", 26))}</td>
        <td class="term-line">${escapeHtml(short(indicators || observation.provenance || "metadata", 72))}</td>
        <td>${escapeHtml(short(formatNetworkFlow(network), 72))}</td>
      </tr>`;
    })
    .join("");

  els.networkBody.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedId = row.dataset.id;
      renderNetwork();
      renderSignals();
      renderDetail();
    });
  });
}

function renderSignals() {
  const signals = filteredSignals();
  const suffix = state.termFilter ? ` · term: ${state.termFilter}` : "";
  els.resultCount.textContent = `${signals.length} shown${suffix}`;
  const selectedNetworkVisible = filteredNetworkObservations().some((observation) => observation.id === state.selectedId);
  if (!signals.some((signal) => signal.id === state.selectedId) && !selectedNetworkVisible) {
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

function networkDetailRows(network) {
  if (!network) return "";
  const remote = [network.remote_domain || network.remote_host || "unknown", network.remote_port].filter(Boolean).join(":");
  const local = [network.local_host, network.local_port].filter(Boolean).join(":") || "Not recorded";
  const enriched = [
    network.ja3 ? `JA3 ${short(network.ja3, 18)}` : "",
    network.dns_query ? `DNS ${network.dns_query}` : "",
    network.schema || "",
  ].filter(Boolean);
  const indicators = (network.matched_network_indicators || []).join(", ") || "No indicators recorded";
  return `
      <dt>Remote</dt><dd>${escapeHtml(remote)}</dd>
      <dt>Local</dt><dd>${escapeHtml(local)}</dd>
      <dt>Protocol</dt><dd>${escapeHtml((network.protocol || "--").toUpperCase())}</dd>
      <dt>Process</dt><dd>${escapeHtml(network.process || "Not recorded")}</dd>
      <dt>State</dt><dd>${escapeHtml(network.state || "observed")}</dd>
      <dt>Enrich</dt><dd>${escapeHtml(enriched.join(", ") || formatNetworkFlow(network))}</dd>
      <dt>Indicators</dt><dd>${escapeHtml(indicators)}</dd>
    `;
}

function renderDetail() {
  const signal =
    (state.payload?.signals || []).find((item) => item.id === state.selectedId) ||
    (state.networkPayload?.observations || []).find((item) => item.id === state.selectedId);
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
      ${networkDetailRows(signal.network)}
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
      renderNetwork();
      renderSignals();
      renderDetail();
      renderSummaries();
      showToast(state.termFilter ? `Filtering term: ${state.termFilter}` : "Term filter cleared");
    });
  });
  els.termList.querySelector("button[data-clear-term]")?.addEventListener("click", () => {
    state.termFilter = "";
    renderNetwork();
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
    setRefreshButtonLoading(true);
    await loadDashboard({ reason: "target" })
      .then((result) => showToast(result.message))
      .catch((error) => showToast(`Refresh failed: ${error.message}`))
      .finally(() => setRefreshButtonLoading(false));
  });
});

els.searchInput.addEventListener("input", () => {
  state.query = els.searchInput.value;
  renderNetwork();
  renderSignals();
  renderDetail();
});

els.refreshNow.addEventListener("click", () => {
  setRefreshButtonLoading(true);
  loadDashboard({ reason: "manual" })
    .then((result) => showToast(result.message))
    .catch((error) => showToast(`Refresh failed: ${error.message}`))
    .finally(() => setRefreshButtonLoading(false));
});

els.autoRefresh.addEventListener("change", () => {
  window.clearInterval(state.timer);
  state.timer = null;
  if (els.autoRefresh.checked) {
    state.timer = window.setInterval(() => {
      loadDashboard({ reason: "auto" }).catch((error) => showToast(`Auto refresh failed: ${error.message}`));
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

els.seedNetwork.addEventListener("click", async () => {
  if (state.payload?.mode === "static") {
    showToast("Network sample is local API only");
    return;
  }
  els.seedNetwork.disabled = true;
  const response = await fetch(`/api/network/sample?target=${encodeURIComponent(state.target)}`, { method: "POST" });
  els.seedNetwork.disabled = false;
  if (!response.ok) {
    showToast("Network sample failed");
    return;
  }
  const result = await response.json();
  showToast(`Network sample: ${result.inserted_artifacts} artifact(s)`);
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

els.copyNetwork.addEventListener("click", () => {
  copyText(
    state.networkPayload?.commands?.monitor_network ||
      state.payload?.commands?.network_monitor ||
      networkCommandForTarget(state.target, dbUrlForCommands(state.payload)),
    "Network command"
  ).catch(() => showToast("Copy failed"));
});

els.copyNetworkImport.addEventListener("click", () => {
  copyText(
    state.networkPayload?.commands?.import_jsonl || networkImportCommand(dbUrlForCommands(state.payload)),
    "Network import command"
  ).catch(() => showToast("Copy failed"));
});

loadDashboard({ reason: "initial" }).catch((error) => {
  els.signalsBody.innerHTML = `<tr><td colspan="9" class="empty-state">Dashboard failed: ${escapeHtml(error.message)}</td></tr>`;
  showToast("Dashboard failed to load");
});
