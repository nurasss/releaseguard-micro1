/* global DEMO_DATA */

(function () {
  "use strict";

  const app = document.getElementById("app");
  const stages = [
    ["Repository Snapshot", "snapshot", "check"],
    ["Deterministic Checks", "checks", "check"],
    ["Analyzer", "analyzer", "pulse"],
    ["Verification", "verification", "hourglass"],
    ["Report", "report", "file"],
  ];

  const state = {
    view: getRoute(),
    form: {
      repository_url: "",
      ref: "",
      mode: "final",
    },
    loading: false,
    run: null,
    report: null,
    trajectory: [],
    activeTab: "report",
    activeEvidenceId: null,
    progressIndex: 2,
    logEntries: [],
    error: "",
    isDemo: false,
    controller: null,
    demoTimer: null,
    progressTimer: null,
    evaluation: DEMO_DATA.evaluation,
    evaluationLoading: false,
  };

  const icons = {
    shield: '<path d="M12 2.5 19 5v5.1c0 4.55-2.72 8.1-7 10.4-4.28-2.3-7-5.85-7-10.4V5l7-2.5Z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m8.7 11.8 2.1 2.1 4.6-4.8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>',
    link: '<path d="M9.7 14.3 8.1 16a3.25 3.25 0 1 1-4.6-4.6l2.8-2.8a3.25 3.25 0 0 1 4.6 0" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8"/><path d="m14.3 9.7 1.6-1.7a3.25 3.25 0 1 1 4.6 4.6l-2.8 2.8a3.25 3.25 0 0 1-4.6 0" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8"/><path d="m8.5 15.5 7-7" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8"/>',
    commit: '<circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M2.5 12H9m6 0h6.5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.7"/>',
    play: '<path d="m9 6.5 7 5.5-7 5.5v-11Z" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-width="1.8"/>',
    flask: '<path d="M9 3v5.1l-4.6 8.1A2 2 0 0 0 6.1 19h11.8a2 2 0 0 0 1.7-2.8L15 8.1V3M7 3h10M7.4 14h9.2" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7"/>',
    info: '<circle cx="12" cy="12" r="8.8" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M12 10.7v5.1M12 7.5h.01" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8"/>',
    check: '<path d="m5.2 12.2 4.3 4.2 9.3-9.1" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>',
    pulse: '<path d="M4 12h3l1.7-5.3L12 17l2-6 1.5 3H20" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7"/>',
    hourglass: '<path d="M7 3h10M7 21h10M8 3c0 4.3 4 4.3 4 9s-4 4.7-4 9m8-18c0 4.3-4 4.3-4 9s4 4.7 4 9" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.7"/>',
    file: '<path d="M6 3.5h7l5 5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M13 3.5V9h5M8 13h6m-6 3h6" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.5"/>',
    data: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v13a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5v-13Z" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8 7h8M8 11h8M8 15h4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.5"/>',
    terminal: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13Z" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="m7.5 9 2.8 2.8-2.8 2.7M12.5 14.5h4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"/>',
    close: '<path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.9"/>',
    eye: '<path d="M2.8 12s3.3-5 9.2-5 9.2 5 9.2 5-3.3 5-9.2 5-9.2-5-9.2-5Z" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-width="1.7"/><circle cx="12" cy="12" r="2.1" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    copy: '<rect x="8" y="8" width="10" height="11" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v10A1.5 1.5 0 0 0 5.5 17H8" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    arrow: '<path d="M5 12h13m-5-5 5 5-5 5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7"/>',
    chevron: '<path d="m7 9 5 5 5-5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"/>',
    warning: '<path d="m12 3 9 16H3L12 3Z" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-width="1.7"/><path d="M12 9v4m0 3h.01" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.8"/>',
    block: '<circle cx="12" cy="12" r="8.7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m6 6 12 12" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="2"/>',
    trend: '<path d="M4 17 9 12l3 3 7-8M15 7h4v4" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7"/>',
  };

  function icon(name, className) {
    const content = icons[name] || icons.info;
    return `<svg class="icon${className ? ` ${className}` : ""}" viewBox="0 0 24 24" aria-hidden="true">${content}</svg>`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function inlineCode(value) {
    return escapeHtml(value)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function formatDuration(ms) {
    const value = Number(ms || 0);
    if (!value) return "—";
    if (value < 1000) return `${Math.round(value)}ms`;
    const totalSeconds = Math.floor(value / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${seconds}s`;
  }

  function formatCost(value) {
    const cost = Number(value || 0);
    return cost === 0 ? "$0.00" : `$${cost.toFixed(2)}`;
  }

  function shortCommit(value) {
    const text = String(value || "");
    return text && text !== "0".repeat(40) ? text.slice(0, 8) : "unresolved";
  }

  function repoIdentity(url) {
    const value = String(url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
    return value.replace(/^github\.com\//, "") || "unknown/repository";
  }

  function decisionClass(decision) {
    return String(decision || "").toLowerCase().replace("-", "");
  }

  function decisionTextClass(decision) {
    const normalized = String(decision || "").toLowerCase();
    if (normalized === "go") return "go";
    if (normalized === "review") return "review";
    return "nogo";
  }

  function findingOrder(finding) {
    const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
    return order[finding.severity] ?? 5;
  }

  function findEvidence(report, id) {
    return (report?.evidence || []).find((evidence) => evidence.id === id) || null;
  }

  function firstEvidence(report, finding) {
    return (finding?.evidence_ids || []).map((id) => findEvidence(report, id)).find(Boolean) || null;
  }

  function evidenceContent(evidence) {
    const payload = evidence?.payload || {};
    if (typeof payload.content === "string") return payload.content;
    if (typeof payload.excerpt === "string") return payload.excerpt;
    if (payload.report) return JSON.stringify(payload.report, null, 2);
    return JSON.stringify(payload, null, 2);
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toISOString().replace("T", " ").replace("Z", " UTC");
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function setView(view) {
    clearRunTimers();
    if (view !== "running" && state.controller) {
      state.controller.abort();
      state.controller = null;
    }
    state.view = view;
    state.activeEvidenceId = null;
    state.error = "";
    if (view !== "running") state.loading = false;
    const route = view === "new" ? "#/new" : `#/${view}`;
    if (window.location.hash !== route) window.history.pushState({}, "", route);
    render();
  }

  function clearDemoTimer() {
    if (state.demoTimer) {
      window.clearTimeout(state.demoTimer);
      state.demoTimer = null;
    }
  }

  function clearRunTimers() {
    clearDemoTimer();
    if (state.progressTimer) {
      window.clearInterval(state.progressTimer);
      state.progressTimer = null;
    }
  }

  function getRoute() {
    const hash = window.location.hash.replace(/^#\/?/, "");
    if (hash.startsWith("report/")) return "report";
    if (hash === "evaluation" || hash === "evaluations") return "evaluation";
    if (hash === "running") return "running";
    return "new";
  }

  function header() {
    const active = state.view === "evaluation" ? "evaluation" : "new";
    return `
      <header class="topbar">
        <div class="topbar-left">
          <a class="brand-lockup" href="#/new" data-action="go-new" aria-label="ReleaseGuard home">
            <span class="brand-mark" aria-hidden="true">${icon("shield", "icon--sm")}</span>
            <span>ReleaseGuard</span>
          </a>
          <nav class="nav-links" aria-label="Primary navigation">
            <a class="nav-link ${active === "new" ? "is-active" : ""}" href="#/new" data-action="go-new">New Audit</a>
            <a class="nav-link ${active === "evaluation" ? "is-active" : ""}" href="#/evaluation" data-action="go-evaluation">Evaluation</a>
          </nav>
        </div>
        <div class="topbar-right">
          <a class="topbar-github" href="https://github.com" target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </header>
    `;
  }

  function footer() {
    return `
      <footer class="site-footer">
        <span>© 2026 ReleaseGuard Audit Engine</span>
        <div class="footer-links">
          <a href="https://github.com" target="_blank" rel="noreferrer">Documentation</a>
          <a href="https://github.com" target="_blank" rel="noreferrer">Privacy Policy</a>
          <a href="/docs" target="_blank" rel="noreferrer">Security API</a>
        </div>
      </footer>
    `;
  }

  function newAuditView() {
    const form = state.form;
    return `
      <main class="page-canvas page-canvas--new">
        <div class="new-audit-content">
          <section class="hero-copy">
            <p class="eyebrow">Release readiness / evidence boundary</p>
            <h1>Evidence-backed release readiness</h1>
            <p>Find release blockers before they reach production. Every critical finding is independently verified against repository evidence.</p>
          </section>

          <form class="panel audit-form-card" id="audit-form">
            <div class="audit-form-inner">
              <div class="form-stack">
                <label class="field">
                  <span class="field-label">Repository URL</span>
                  <span class="field-control">
                    <span class="field-icon">${icon("link", "icon--sm")}</span>
                    <input class="text-input" name="repository_url" value="${escapeHtml(form.repository_url)}" placeholder="https://github.com/org/repository" autocomplete="url" required />
                  </span>
                </label>
                <label class="field">
                  <span class="field-label">Ref (branch, tag, or SHA)</span>
                  <span class="field-control">
                    <span class="field-icon">${icon("commit", "icon--sm")}</span>
                    <input class="text-input" name="ref" value="${escapeHtml(form.ref)}" placeholder="release/v1.4" autocomplete="off" />
                  </span>
                </label>
                <div class="form-options">
                  <div class="field">
                    <span class="field-label">Audit profile</span>
                    <div class="mode-switch" role="group" aria-label="Audit profile">
                      <button type="button" class="mode-button ${form.mode === "final" ? "is-selected" : ""}" data-action="select-mode" data-mode="final">Final verifier</button>
                      <button type="button" class="mode-button ${form.mode === "baseline" ? "is-selected" : ""}" data-action="select-mode" data-mode="baseline">Baseline</button>
                    </div>
                  </div>
                  <label class="field">
                    <span class="field-label">Ref policy</span>
                    <span class="field-control">
                      <select class="select-input" aria-label="Ref policy">
                        <option>Immutable snapshot</option>
                      </select>
                      <span class="select-chevron">${icon("chevron", "icon--sm")}</span>
                    </span>
                  </label>
                </div>
              </div>

              <div class="form-actions">
                <button class="button button--primary" type="submit" ${state.loading ? "disabled" : ""}>
                  ${icon("play", "icon--sm")}
                  <span>Run release audit</span>
                </button>
                <button class="button button--ghost" type="button" data-action="try-demo" ${state.loading ? "disabled" : ""}>
                  ${icon("flask", "icon--sm")}
                  <span>Try demo repository</span>
                </button>
              </div>

              <div class="read-only-note">
                ${icon("info", "icon--sm")}
                <span>Read-only audit — no repository changes will be made.</span>
              </div>
            </div>
          </form>

          ${state.error ? `<div class="error-banner">${icon("warning", "icon--sm")}<span>${escapeHtml(state.error)}</span></div>` : ""}
          <p class="checks-caption"><span>Checks include</span> CI &amp; workflows <span>·</span> Tests <span>·</span> Release metadata <span>·</span> Configuration <span>·</span> Evidence verification</p>
        </div>
      </main>
    `;
  }

  function progressStepMarkup(index) {
    const current = state.progressIndex;
    const status = index < current ? "is-complete" : index === current ? "is-active" : "is-pending";
    const stage = stages[index];
    const symbol = status === "is-complete" ? "check" : status === "is-active" ? "pulse" : stage[2];
    return `
      <div class="progress-step ${status}">
        <span class="progress-node">${icon(symbol, status === "is-active" ? "spin" : "icon--sm")}</span>
        <span>${stage[0]}</span>
      </div>
    `;
  }

  function logLine(entry) {
    const typeClass = entry.type === "INFO" ? "log-type--info" : entry.type === "FINDING" ? "log-type--finding" : "";
    return `
      <div class="log-line">
        <span class="log-time">[${escapeHtml(entry.time)}]</span>
        <span class="log-type ${typeClass}">${escapeHtml(entry.type)}</span>
        <span class="log-message">${inlineCode(entry.message)}</span>
      </div>
    `;
  }

  function runningView() {
    const run = state.run || {
      repository_url: state.form.repository_url || "demo/payment-service",
      requested_ref: state.form.ref || "release/v1.4",
      commit_sha: "pending",
      id: "pending",
    };
    const target = repoIdentity(run.repository_url);
    const logs = state.logEntries.length ? state.logEntries : [{ time: "--:--:--", type: "INFO", message: "Audit session initializing…" }];
    const progress = Math.round((state.progressIndex / (stages.length - 1)) * 100);
    return `
      <main class="page-canvas page-canvas--running">
        <section class="running-header">
          <div>
            <div class="title-with-icon">
              ${icon("pulse", "icon--lg spin")}
              <h1 class="page-title">Running Audit</h1>
            </div>
            <p class="subline">Target: <strong>${escapeHtml(target)}</strong><span class="separator">|</span>Transition: <strong>${escapeHtml(run.requested_ref || state.form.ref || "main")} → ${escapeHtml(shortCommit(run.commit_sha || "pending"))}</strong></p>
          </div>
          <button class="button button--ghost button--danger-ghost" type="button" data-action="stop-audit">Stop audit</button>
        </section>

        <div class="progress-rail" style="--progress: ${progress}%" aria-label="Audit progress">
          ${stages.map((_, index) => progressStepMarkup(index)).join("")}
        </div>

        <div class="running-grid">
          <section class="panel context-panel">
            <div class="panel-heading">${icon("data", "icon--sm")}<span>Execution Context</span></div>
            <div class="context-body">
              <dl class="context-list">
                <div class="context-item">
                  <dt>Target repository</dt>
                  <dd><span class="context-value">${escapeHtml(target)}</span></dd>
                </div>
                <div class="context-item">
                  <dt>Source ref</dt>
                  <dd>${icon("commit", "icon--sm")} ${escapeHtml(shortCommit(run.commit_sha || "resolving"))}…</dd>
                </div>
                <div class="context-item">
                  <dt>Target ref</dt>
                  <dd>refs/heads/${escapeHtml(run.requested_ref || state.form.ref || "main")}</dd>
                </div>
                <div class="context-item">
                  <dt>Profile</dt>
                  <dd>${escapeHtml(state.form.mode === "baseline" ? "baseline / direct signals" : "final / verifier enabled")}</dd>
                </div>
              </dl>
              <div class="context-uptime">
                <span class="metadata-label">Uptime</span>
                <strong>${escapeHtml(formatDuration(Math.max(1000, Date.now() - (state.startedAt || Date.now()))))}</strong>
              </div>
            </div>
          </section>

          <section class="running-console">
            <div class="running-console-inner">
              <div class="console-heading">
                <div class="console-title">${icon("terminal", "icon--sm")}<span>system.log</span></div>
                <span class="run-status">${state.loading ? "analyzing" : "complete"}</span>
              </div>
              <div class="console-body" aria-live="polite">${logs.map(logLine).join("")}</div>
            </div>
          </section>
        </div>
      </main>
    `;
  }

  function countMetrics(report) {
    const activeFindings = (report?.findings || []).filter((finding) => finding.verification_status !== "rejected");
    const critical = activeFindings.filter((finding) => finding.severity === "critical" && finding.verification_status === "confirmed").length;
    const needsReview = activeFindings.filter((finding) => finding.severity === "high" || finding.verification_status === "needs_human_review").length;
    const passed = (report?.deterministic_checks || []).filter((check) => check.status === "pass").length;
    return { critical, needsReview, passed };
  }

  function verificationFor(report, finding) {
    return (report?.verifications || []).find((item) => item.finding_id === finding.id) || null;
  }

  function verificationMarkup(report, finding) {
    const status = finding.verification_status || "pending";
    const verification = verificationFor(report, finding);
    if (status === "confirmed") {
      return `<div class="finding-verification finding-verification--confirmed">${icon("check", "icon--sm")}<span>${escapeHtml(verification?.reason_summary || "Confirmed by Verifier against cited repository evidence.")}</span></div>`;
    }
    if (status === "needs_human_review") {
      return `<div class="finding-verification finding-verification--review">${icon("warning", "icon--sm")}<span>Evidence is strong, but this finding needs a human decision before the release gate can open.</span></div>`;
    }
    if (status === "rejected") {
      return `<div class="finding-verification finding-verification--rejected">${icon("close", "icon--sm")}<span>${escapeHtml(verification?.reason_summary || "Rejected by Verifier after contradicting evidence was found.")}</span></div>`;
    }
    return `<div class="finding-verification">${icon("hourglass", "icon--sm")}<span>Verification pending. Review the cited evidence before making a release decision.</span></div>`;
  }

  function verificationBadge(finding) {
    const status = finding.verification_status || "pending";
    const labels = {
      confirmed: "Confirmed",
      needs_human_review: "Needs review",
      rejected: "Rejected",
      pending: "Pending",
    };
    const className = status === "needs_human_review" ? "review" : status;
    return `<span class="verification-badge verification-badge--${className}">${escapeHtml(labels[status] || status)}</span>`;
  }

  function findingCard(report, finding, rejected) {
    const evidence = firstEvidence(report, finding);
    const excerpt = evidence ? evidenceContent(evidence) : "No repository excerpt attached to this finding.";
    const status = finding.severity || "info";
    return `
      <article class="finding-card finding-card--${escapeHtml(status)} ${rejected ? "finding-card--rejected" : ""}">
        <div class="finding-card-header">
          <div class="finding-header-copy">
            <div class="finding-meta">
              <span class="status-badge status-badge--${escapeHtml(status)}">${escapeHtml(status)}</span>
              ${verificationBadge(finding)}
              <span class="finding-id">${escapeHtml(finding.id)} · ${escapeHtml(finding.category || "other")}</span>
            </div>
            <h3>${escapeHtml(finding.title)}</h3>
          </div>
          <div class="finding-actions">
            ${evidence ? `<button class="icon-button" type="button" data-action="open-evidence" data-evidence-id="${escapeHtml(evidence.id)}" aria-label="View evidence" title="View evidence">${icon("eye", "icon--sm")}</button>` : ""}
            <button class="icon-button" type="button" data-action="copy-finding" data-finding-id="${escapeHtml(finding.id)}" aria-label="Copy finding" title="Copy finding">${icon("copy", "icon--sm")}</button>
          </div>
        </div>
        <div class="finding-grid">
          <div class="finding-column">
            <span class="finding-label">Repository evidence</span>
            <pre class="finding-excerpt">${escapeHtml(excerpt)}</pre>
          </div>
          <div class="finding-column">
            <span class="finding-label">ReleaseGuard interpretation</span>
            <p class="finding-copy">${inlineCode(finding.claim)}</p>
            ${verificationMarkup(report, finding)}
          </div>
        </div>
        ${!rejected ? `<div class="action-callout"><h4 class="action-title">Recommended action</h4><p class="action-copy">${inlineCode(finding.recommended_action || "Review the cited evidence and rerun the audit.")}</p></div>` : ""}
        <div class="finding-footer">
          ${evidence ? `<button class="evidence-link" type="button" data-action="open-evidence" data-evidence-id="${escapeHtml(evidence.id)}">${icon("file", "icon--sm")}<span>Evidence ${escapeHtml(evidence.id)}</span><span>${escapeHtml(evidence.source_path)}</span></button>` : "<span class=\"finding-id\">No evidence linked</span>"}
          <span class="finding-id">confidence ${Math.round(Number(finding.confidence || 0) * 100)}%</span>
        </div>
      </article>
    `;
  }

  function checksMarkup(report) {
    const checks = report?.deterministic_checks || [];
    if (!checks.length) return `<div class="empty-state">No deterministic checks were recorded for this run.</div>`;
    return `<div class="check-grid">${checks.map((check) => `
      <div class="check-item">
        <div class="check-item-top"><span class="check-id">${escapeHtml(check.check_id)}</span><span class="check-status check-status--${escapeHtml(check.status)}">${escapeHtml(check.status === "pass" ? "PASS" : check.status.replaceAll("_", " ").toUpperCase())}</span></div>
        <strong class="check-name">${escapeHtml(check.name)}</strong>
        <p class="check-details">${escapeHtml(check.details)}</p>
      </div>
    `).join("")}</div>`;
  }

  function reportView() {
    const report = state.report || DEMO_DATA.report;
    const run = state.run || report;
    const metrics = countMetrics(report);
    const decision = report.decision || run.final_decision || "REVIEW";
    const decisionLabel = decision === "NO-GO" ? "NO-GO" : decision;
    const activeFindings = (report.findings || []).filter((finding) => finding.verification_status !== "rejected").sort((a, b) => findingOrder(a) - findingOrder(b));
    const rejected = (report.rejected_findings || []).filter((finding) => !activeFindings.some((item) => item.id === finding.id));
    const target = repoIdentity(report.repository_url);
    return `
      <main class="page-canvas page-canvas--report">
        <div class="report-toolbar">
          <div class="toolbar-group">
            <button class="toolbar-button" type="button" data-action="go-new">${icon("arrow", "icon--sm")} Back to new audit</button>
            ${state.isDemo ? '<span class="demo-pill">local demo fixture</span>' : ""}
          </div>
          <div class="toolbar-group">
            <button class="toolbar-button" type="button" data-action="download-report">${icon("arrow", "icon--sm")} Download report</button>
          </div>
        </div>

        <div class="report-meta-bar">
          <div class="meta-cell"><span class="metadata-label">Identity</span><span class="metadata-value">${escapeHtml(target)}</span></div>
          <div class="meta-cell"><span class="metadata-label">Commit</span><span class="metadata-value metadata-value--blue">${escapeHtml(shortCommit(report.commit_sha))}</span></div>
          <div class="meta-cell"><span class="metadata-label">Runtime</span><span class="metadata-value">${escapeHtml(formatDuration(report.runtime_ms || run.runtime_ms))}</span></div>
          <div class="meta-cell"><span class="metadata-label">Cost</span><span class="metadata-value">${escapeHtml(formatCost(report.estimated_cost_usd ?? run.estimated_cost_usd))}</span></div>
        </div>

        <section class="report-hero report-hero--${decisionClass(decision)}">
          <div class="report-decision">
            <h1>${icon(decision === "GO" ? "check" : decision === "REVIEW" ? "warning" : "block", "icon--lg")} ${escapeHtml(decisionLabel)}</h1>
            <p>${escapeHtml(decision === "NO-GO" ? "Audit completed. Release gate closed due to critical findings." : decision === "REVIEW" ? "Audit completed. Human review is required before release." : "Audit completed. No release-blocking findings were confirmed.")}</p>
          </div>
          <div class="metrics-strip">
            <div class="metric-card"><span class="metric-value metric-value--critical">${metrics.critical}</span><span class="metric-label">Critical</span></div>
            <div class="metric-card"><span class="metric-value metric-value--review">${metrics.needsReview}</span><span class="metric-label">Needs review</span></div>
            <div class="metric-card"><span class="metric-value metric-value--passed">${metrics.passed}</span><span class="metric-label">Passed</span></div>
          </div>
        </section>

        <section class="summary-panel">
          <h2>${icon("data", "icon--sm")} Summary</h2>
          <p class="summary-copy">${inlineCode(report.executive_summary || "No executive summary was recorded.")}</p>
        </section>

        <div class="report-tabs" role="tablist">
          <button class="tab-button ${state.activeTab === "report" ? "is-active" : ""}" type="button" data-action="select-tab" data-tab="report">Report</button>
          <button class="tab-button ${state.activeTab === "trace" ? "is-active" : ""}" type="button" data-action="select-tab" data-tab="trace">Trace</button>
        </div>

        ${state.activeTab === "trace" ? traceView(report) : `
          <section>
            <div class="section-header"><h2 class="section-title">${decision === "GO" ? "Release findings" : "Findings requiring attention"}</h2><span class="section-count">${activeFindings.length} active finding${activeFindings.length === 1 ? "" : "s"}</span></div>
            <div class="finding-list">${activeFindings.length ? activeFindings.map((finding) => findingCard(report, finding, false)).join("") : '<div class="empty-state">No active findings. The repository passed the release gate.</div>'}</div>
          </section>
          <section class="checks-section">
            <div class="section-header"><h2 class="section-title">Passed and deterministic checks</h2><span class="section-count">${(report.deterministic_checks || []).length} checks recorded</span></div>
            ${checksMarkup(report)}
          </section>
          ${rejected.length ? `<section class="rejected-section"><div class="section-header"><h2 class="section-title">Rejected by verifier</h2><span class="section-count">${rejected.length} rejected</span></div><div class="finding-list">${rejected.map((finding) => findingCard(report, finding, true)).join("")}</div></section>` : ""}
        `}
      </main>
      ${state.activeEvidenceId ? evidenceDrawer(report, state.activeEvidenceId) : ""}
    `;
  }

  function traceView(report) {
    const trajectory = state.trajectory || [];
    const evidenceCount = (report.evidence || []).length;
    const verificationCount = (report.verifications || []).length;
    if (!trajectory.length) {
      return `<div class="empty-state">No trace steps are available for this run.</div>`;
    }
    return `
      <div class="trace-layout">
        <div class="trace-list">
          ${trajectory.map((step) => {
            const kind = step.state === "finding" ? "finding" : step.status === "success" ? "success" : "default";
            return `<article class="trace-item trace-item--${kind}"><span class="trace-node"></span><div class="trace-card"><div class="trace-card-header"><span class="trace-agent">${escapeHtml(step.component || step.agent_name || "agent")}</span><span class="trace-state">${escapeHtml(step.state || "step")}</span></div><p class="trace-output">${escapeHtml(step.output_summary || "No output summary recorded.")}</p><div class="trace-meta"><span>${icon("terminal", "icon--sm")} ${escapeHtml(step.tool || "internal")}</span><span>${escapeHtml(formatDuration(step.duration_ms))}</span><span>${escapeHtml(formatDate(step.timestamp))}</span>${(step.evidence_created || []).length ? `<span class="trace-badge">${icon("file", "icon--sm")} ${escapeHtml(step.evidence_created.join(", "))}</span>` : ""}</div></div></article>`;
          }).join("")}
        </div>
        <aside class="trace-aside"><h3>Run instrumentation</h3><div class="trace-stat"><span class="trace-stat-label">Steps</span><span class="trace-stat-value">${trajectory.length}</span></div><div class="trace-stat"><span class="trace-stat-label">Evidence records</span><span class="trace-stat-value">${evidenceCount}</span></div><div class="trace-stat"><span class="trace-stat-label">Verifier decisions</span><span class="trace-stat-value">${verificationCount}</span></div><div class="trace-stat"><span class="trace-stat-label">Model</span><span class="trace-stat-value">${escapeHtml(report.model_id || "—")}</span></div></aside>
      </div>
    `;
  }

  function evidenceDrawer(report, evidenceId) {
    const evidence = findEvidence(report, evidenceId);
    if (!evidence) return "";
    const payload = evidence.payload || {};
    const path = payload.path || evidence.source_path;
    const interpretation = evidence.id === "E-014"
      ? "Static analysis detects missing release trigger context. The deployment job is mapped to the production environment, but the workflow is only triggered by main. This violates release policy POL-RLS-02."
      : evidence.summary;
    return `
      <div class="drawer-backdrop" data-action="close-drawer">
        <aside class="evidence-drawer" role="dialog" aria-modal="true" aria-label="Evidence ${escapeHtml(evidence.id)}">
          <div class="drawer-header"><div class="drawer-title">${icon("terminal", "icon--sm")}<span>EVIDENCE: ${escapeHtml(evidence.id)}</span></div><button class="icon-button" type="button" data-action="close-drawer" aria-label="Close evidence drawer">${icon("close", "icon--sm")}</button></div>
          <div class="drawer-content">
            <section class="drawer-section">
              <div class="drawer-metadata">
                <div class="drawer-metadata-item"><span class="drawer-label">Evidence ID</span><span class="drawer-value">${escapeHtml(evidence.id)}</span></div>
                <div class="drawer-metadata-item"><span class="drawer-label">Source type</span><span class="drawer-value">${escapeHtml(String(evidence.source_type || "evidence").replaceAll("_", " "))}</span></div>
                <div class="drawer-metadata-item drawer-metadata-item--wide"><span class="drawer-label">Path</span><span class="drawer-value">${icon("file", "icon--sm")} ${escapeHtml(path)}</span></div>
                <div class="drawer-metadata-item"><span class="drawer-label">Commit</span><span class="drawer-value">${escapeHtml(shortCommit(evidence.source_ref))}</span></div>
                <div class="drawer-metadata-item"><span class="drawer-label">Lines</span><span class="drawer-value">${evidence.line_start ? `${evidence.line_start}-${evidence.line_end}` : "—"}</span></div>
                <div class="drawer-metadata-item drawer-metadata-item--wide"><span class="drawer-label">Content hash</span><span class="drawer-value drawer-value--muted">${escapeHtml(evidence.content_hash || "—")}</span></div>
              </div>
            </section>
            <section class="drawer-section"><h2 class="drawer-section-title">Source excerpt</h2><pre class="code-well">${escapeHtml(evidenceContent(evidence))}</pre></section>
            <section class="drawer-section"><div class="drawer-interpretation"><h3>ReleaseGuard interpretation</h3><p>${inlineCode(interpretation)}</p></div></section>
          </div>
        </aside>
      </div>
    `;
  }

  function evaluationView() {
    const evaluation = state.evaluation || DEMO_DATA.evaluation;
    const aggregate = evaluation.aggregate?.all || {};
    const results = evaluation.results || [];
    return `
      <main class="page-canvas page-canvas--evaluation">
        <section class="evaluation-header">
          <div>
            <p class="eyebrow">Benchmark / releaseguard evaluation</p>
            <h1 class="page-title">Evaluation cockpit</h1>
            <p class="subline">${escapeHtml(evaluation.meta?.cases_total || 12)} frozen cases · ${escapeHtml(evaluation.meta?.execution_mode || "offline_fixture")} · model <strong>${escapeHtml(evaluation.meta?.model_id || "releaseguard-offline-v1")}</strong></p>
          </div>
          <button class="button button--ghost" type="button" data-action="run-evaluation" ${state.evaluationLoading ? "disabled" : ""}>${icon("trend", "icon--sm")} ${state.evaluationLoading ? "Running evaluation…" : "Run evaluation"}</button>
        </section>

        <section class="evaluation-kpis">
          <div class="kpi-card"><span class="kpi-label">Critical blocker recall</span><strong class="kpi-value">${Math.round((aggregate.cbr || 0) * 100)}%</strong><span class="kpi-subline">all cases</span></div>
          <div class="kpi-card"><span class="kpi-label">Precision</span><strong class="kpi-value">${Math.round((aggregate.precision || 0) * 100)}%</strong><span class="kpi-subline">finding quality</span></div>
          <div class="kpi-card"><span class="kpi-label">Decision accuracy</span><strong class="kpi-value">${Math.round((aggregate.decision_accuracy || 0) * 100)}%</strong><span class="kpi-subline">GO / REVIEW / NO-GO</span></div>
          <div class="kpi-card"><span class="kpi-label">Evidence coverage</span><strong class="kpi-value">${Math.round((aggregate.critical_evidence_coverage || 0) * 100)}%</strong><span class="kpi-subline">critical / high claims</span></div>
          <div class="kpi-card"><span class="kpi-label">Runtime</span><strong class="kpi-value">${escapeHtml(formatDuration(aggregate.total_runtime_ms))}</strong><span class="kpi-subline">12 case suite</span></div>
        </section>

        <section class="evaluation-panel">
          <div class="evaluation-panel-heading"><h2>Case matrix</h2><span class="demo-pill">${escapeHtml(evaluation.meta?.run_label || "fixture")}</span></div>
          <div class="evaluation-table-wrap"><table class="evaluation-table"><thead><tr><th>Case</th><th>Expected decision</th><th>Actual decision</th><th>Result</th></tr></thead><tbody>${results.map((row) => `<tr><td class="case-id">${escapeHtml(row[0])}</td><td class="decision-text--${decisionTextClass(row[1])}">${escapeHtml(row[1])}</td><td class="decision-text--${decisionTextClass(row[2])}">${escapeHtml(row[2])}</td><td class="result-pass">${escapeHtml(row[3])}</td></tr>`).join("")}</tbody></table></div>
        </section>
      </main>
    `;
  }

  function render() {
    const page = state.view === "running" ? runningView() : state.view === "report" ? reportView() : state.view === "evaluation" ? evaluationView() : newAuditView();
    app.innerHTML = `<div class="app-shell">${header()}${page}${state.view === "new" ? footer() : ""}</div>`;
  }

  function addLog(type, message) {
    const now = new Date();
    state.logEntries.push({
      time: now.toISOString().slice(11, 19),
      type,
      message,
    });
  }

  function startDemo() {
    clearRunTimers();
    state.isDemo = true;
    state.loading = true;
    state.view = "running";
    state.startedAt = Date.now();
    state.progressIndex = 0;
    state.run = clone(DEMO_DATA.run);
    state.report = null;
    state.trajectory = [];
    state.logEntries = [];
    state.form.repository_url = DEMO_DATA.run.repository_url;
    state.form.ref = DEMO_DATA.run.requested_ref;
    state.form.mode = "final";
    window.history.pushState({}, "", "#/running");
    addLog("INFO", "Audit session initiated. ID: DEMO-8924-X");
    render();

    const updates = [
      [1, "CHECK", "Run check: create_workspace_snapshot"],
      [2, "CHECK", "Read file: .github/workflows/release.yml"],
      [2, "FINDING", "Created finding: F-001 (release trigger missing)"],
      [3, "CHECK", "Run check: ci_release_trigger_conditions"],
      [4, "INFO", "Analyzer completed. Verifier started."],
      [4, "CHECK", "Cross-checking alternative workflows and release refs"],
      [5, "INFO", "Report assembled. Decision policy evaluated."],
    ];
    let index = 0;
    const tick = () => {
      if (!state.loading || state.view !== "running") return;
      if (index < updates.length) {
        const [progressIndex, type, message] = updates[index];
        state.progressIndex = progressIndex;
        addLog(type, message);
        index += 1;
        render();
        state.demoTimer = window.setTimeout(tick, index === updates.length ? 700 : 850);
        return;
      }
      state.loading = false;
      state.progressIndex = 5;
      state.report = clone(DEMO_DATA.report);
      state.trajectory = clone(DEMO_DATA.trajectory);
      state.view = "report";
      state.activeTab = "report";
      window.history.pushState({}, "", "#/report/demo-audit-2026-08-31");
      render();
    };
    state.demoTimer = window.setTimeout(tick, 650);
  }

  async function runLiveAudit() {
    clearRunTimers();
    const form = document.getElementById("audit-form");
    const data = new FormData(form);
    const repositoryUrl = String(data.get("repository_url") || "").trim();
    const ref = String(data.get("ref") || "").trim() || "main";
    if (!repositoryUrl) return;
    state.form.repository_url = repositoryUrl;
    state.form.ref = ref;
    state.isDemo = false;
    state.loading = true;
    state.view = "running";
    state.progressIndex = 0;
    state.run = { repository_url: repositoryUrl, requested_ref: ref, commit_sha: "resolving", id: "pending" };
    state.report = null;
    state.trajectory = [];
    state.logEntries = [];
    state.error = "";
    state.startedAt = Date.now();
    state.controller = new AbortController();
    window.history.pushState({}, "", "#/running");
    addLog("INFO", "Audit request submitted. Waiting for repository resolution…");
    render();

    const liveProgressLogs = [
      [1, "CHECK", "Creating immutable workspace snapshot"],
      [2, "CHECK", "Running deterministic release checks"],
      [2, "EXEC", "Analyzer is collecting bounded repository evidence"],
    ];
    let liveProgressIndex = 0;
    state.progressTimer = window.setInterval(() => {
      if (!state.loading || state.view !== "running") return;
      const update = liveProgressLogs[Math.min(liveProgressIndex, liveProgressLogs.length - 1)];
      if (liveProgressIndex < liveProgressLogs.length) {
        state.progressIndex = update[0];
        addLog(update[1], update[2]);
        liveProgressIndex += 1;
      }
      render();
    }, 1800);

    try {
      const response = await fetch("/api/v1/audits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository_url: repositoryUrl, ref, mode: state.form.mode, profile: "default-release" }),
        signal: state.controller.signal,
      });
      const created = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(created.detail || `Audit request failed (${response.status})`);
      addLog("INFO", `Audit run created: ${created.audit_id}`);
      state.progressIndex = 2;
      render();

      const detailResponse = await fetch(`/api/v1/audits/${encodeURIComponent(created.audit_id)}`, { signal: state.controller.signal });
      const detail = await detailResponse.json().catch(() => ({}));
      if (!detailResponse.ok) throw new Error(detail.detail || "The completed audit report could not be loaded.");
      let trajectory = [];
      try {
        const trajectoryResponse = await fetch(`/api/v1/audits/${encodeURIComponent(created.audit_id)}/trajectory`, { signal: state.controller.signal });
        if (trajectoryResponse.ok) trajectory = await trajectoryResponse.json();
      } catch (_error) {
        trajectory = [];
      }
      state.loading = false;
      clearRunTimers();
      state.run = detail.run;
      state.report = detail.report;
      state.trajectory = trajectory;
      state.progressIndex = 5;
      state.view = "report";
      state.activeTab = "report";
      window.history.pushState({}, "", `#/report/${encodeURIComponent(created.audit_id)}`);
      render();
    } catch (error) {
      if (error?.name === "AbortError") return;
      clearRunTimers();
      state.loading = false;
      state.view = "new";
      state.error = error?.message || "Audit could not be completed.";
      state.controller = null;
      render();
    }
  }

  async function runEvaluation() {
    state.evaluationLoading = true;
    render();
    try {
      const response = await fetch("/api/v1/evaluations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "final", cases: null }),
      });
      const created = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(created.detail || `Evaluation failed (${response.status})`);
      const resultResponse = await fetch(`/api/v1/evaluations/${encodeURIComponent(created.evaluation_id)}`);
      if (resultResponse.ok) state.evaluation = await resultResponse.json();
    } catch (error) {
      state.error = error?.message || "Evaluation could not be completed.";
    } finally {
      state.evaluationLoading = false;
      render();
    }
  }

  function copyFinding(findingId) {
    const finding = (state.report?.findings || []).find((item) => item.id === findingId) || (state.report?.rejected_findings || []).find((item) => item.id === findingId);
    if (!finding) return;
    const text = `${finding.id} — ${finding.title}\n${finding.claim}\nRecommended action: ${finding.recommended_action || "Review evidence."}`;
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).catch(() => {});
    const button = document.querySelector(`[data-finding-id="${CSS.escape(findingId)}"]`);
    if (button) {
      button.style.color = "var(--green)";
      window.setTimeout(() => { button.style.color = ""; }, 900);
    }
  }

  function downloadReport() {
    if (!state.report) return;
    const content = JSON.stringify(state.report, null, 2);
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${state.report.audit_run_id || "releaseguard-report"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  app.addEventListener("submit", (event) => {
    if (event.target.id !== "audit-form") return;
    event.preventDefault();
    runLiveAudit();
  });

  app.addEventListener("input", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    if (event.target.name === "repository_url") state.form.repository_url = event.target.value;
    if (event.target.name === "ref") state.form.ref = event.target.value;
  });

  app.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    if (action === "go-new") {
      event.preventDefault();
      state.form.repository_url = "";
      state.form.ref = "";
      state.isDemo = false;
      state.report = null;
      setView("new");
    }
    if (action === "go-evaluation") {
      event.preventDefault();
      setView("evaluation");
    }
    if (action === "try-demo") startDemo();
    if (action === "select-mode") {
      state.form.mode = target.dataset.mode || "final";
      render();
    }
    if (action === "stop-audit") {
      clearRunTimers();
      if (state.controller) state.controller.abort();
      state.controller = null;
      state.loading = false;
      state.error = "Audit stopped before a report was produced.";
      state.view = "new";
      render();
    }
    if (action === "select-tab") {
      state.activeTab = target.dataset.tab || "report";
      state.activeEvidenceId = null;
      render();
    }
    if (action === "open-evidence") {
      state.activeEvidenceId = target.dataset.evidenceId || null;
      render();
    }
    if (action === "close-drawer") {
      state.activeEvidenceId = null;
      render();
    }
    if (action === "copy-finding") copyFinding(target.dataset.findingId);
    if (action === "download-report") downloadReport();
    if (action === "run-evaluation") runEvaluation();
  });

  function syncRoute() {
    const route = getRoute();
    if (route === "report" && state.report) state.view = "report";
    else if (route === "evaluation") state.view = "evaluation";
    else if (route === "running" && state.loading) state.view = "running";
    else state.view = "new";
    render();
    if (route === "report") hydrateReportRoute();
  }

  window.addEventListener("popstate", syncRoute);
  window.addEventListener("hashchange", syncRoute);

  render();

  async function hydrateReportRoute() {
    const hash = window.location.hash.replace(/^#\/?/, "");
    if (!hash.startsWith("report/") || state.report) return;
    const auditId = decodeURIComponent(hash.slice("report/".length));
    if (auditId === DEMO_DATA.run.id) {
      state.run = clone(DEMO_DATA.run);
      state.report = clone(DEMO_DATA.report);
      state.trajectory = clone(DEMO_DATA.trajectory);
      state.isDemo = true;
      render();
      return;
    }
    try {
      const response = await fetch(`/api/v1/audits/${encodeURIComponent(auditId)}`);
      if (!response.ok) throw new Error("Audit report not found.");
      const detail = await response.json();
      state.run = detail.run;
      state.report = detail.report;
      state.isDemo = false;
      try {
        const trajectoryResponse = await fetch(`/api/v1/audits/${encodeURIComponent(auditId)}/trajectory`);
        if (trajectoryResponse.ok) state.trajectory = await trajectoryResponse.json();
      } catch (_error) {
        state.trajectory = [];
      }
      state.view = "report";
      render();
    } catch (error) {
      state.view = "new";
      state.error = error?.message || "Audit report not found.";
      render();
    }
  }

  hydrateReportRoute();
})();
