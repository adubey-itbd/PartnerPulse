// PartnerPulse — per-partner detail page (data-driven via fetch)
(function () {
    "use strict";

    const qs = new URLSearchParams(location.search);
    const slug = qs.get("partner") || "logically";

    const state = {
        data: null,
        cw: null,
        activeTab: "overview",
        csatFilter: "All",
        feedbackTab: "csat",
        selectedTranscriptIndex: 0,
        selectedDeckIndex: 0,
        transcriptSearchQuery: "",
        activeKeywordFilter: "",
    };

    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    // ITBD speakers to align chat bubbles (right = ITBD)
    const ITBD_SPEAKERS = ["Akhilesh", "Bhanu", "Rick Arora", "Automation", "Shukla", "Bhatia"];

    function ragBadgeClass(rag) {
        const r = (rag || "").toLowerCase();
        if (r === "red") return "badge-danger";
        if (r === "amber") return "badge-warning";
        if (r === "green") return "badge-success";
        return "badge-outline";
    }
    function riskBadgeClass(risk) {
        const r = (risk || "").toLowerCase();
        if (r === "high") return "badge-danger";
        if (r === "medium") return "badge-warning";
        if (r === "low") return "badge-success";
        return "badge-outline";
    }
    function bandClass(band) {
        const b = (band || "").toLowerCase();
        if (b === "critical" || b === "high") return "badge-danger";
        if (b === "medium") return "badge-warning";
        if (b === "low") return "badge-success";
        return "badge-outline";
    }
    // Risk band is a deterministic function of the 0–100 score — SAME thresholds as
    // the Executive Overview (High ≥45 · ≥25 · Low). Display this, never the raw
    // the model's raw risk_band, which mis-calibrated vs its own score (e.g. 63 → "Medium").
    function bandFromScore(s) { return s >= 45 ? "High" : s >= 25 ? "Medium" : "Low"; }
    function sevClass(sev) {
        const s = (sev || "").toLowerCase();
        if (s === "high") return "badge-danger";
        if (s === "medium") return "badge-warning";
        return "badge-info";
    }

    // ---------------- Navigation ----------------
    function setupNavigation() {
        document.querySelectorAll(".nav-link-item, [data-tab]").forEach((item) => {
            if (!item.getAttribute("data-tab")) return;
            item.addEventListener("click", (e) => {
                e.preventDefault();
                switchTab(item.getAttribute("data-tab"));
            });
        });
    }
    function switchTab(tab) {
        document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
        const link = document.querySelector(`.nav-link-item[data-tab="${tab}"]`);
        if (link) link.closest(".nav-item").classList.add("active");
        document.querySelectorAll(".page-container").forEach((p) => {
            p.classList.toggle("active", p.id === `page-${tab}`);
        });
        state.activeTab = tab;
        if (tab === "transcripts") renderTranscriptDialogue();
        if (tab === "decks") renderDeck();
    }

    // ---------------- Header / Meta ----------------
    function initClientMeta() {
        const c = state.data.client;
        const ai = state.data.ai || {};
        document.title = `PartnerPulse — ${c.name}`;
        $("client-name").textContent = c.name;
        $("partner-avatar").textContent = (c.name || "?").charAt(0);
        $("partner-details-name").textContent = c.name;
        $("partner-details-status").textContent = `Client #${c.id}`;

        const ragBadge = $("client-rag-badge");
        ragBadge.className = `badge ${ragBadgeClass(c.rag)}`;
        ragBadge.innerHTML = `RAG: ${esc(c.rag || "—")}`;

        const riskBadge = $("client-risk-badge");
        riskBadge.className = `badge ${riskBadgeClass(c.cancel_risk)}`;
        riskBadge.innerHTML = `Cancel Risk: ${esc(c.cancel_risk || "—")}`;

        const auBadge = $("client-aurisk-badge");
        if (ai.risk_score != null) {
            auBadge.className = `badge ${bandClass(bandFromScore(ai.risk_score))}`;
            auBadge.innerHTML = `AI Churn: ${esc(ai.risk_score)} (${bandFromScore(ai.risk_score)})`;
        } else {
            auBadge.style.display = "none";
        }

        $("ov-am").textContent = c.account_manager || "—";
        $("ov-service").textContent = c.service_line || "—";
        $("ov-health-reason").textContent = c.health_reason || "—";
        $("ov-next-step").textContent = c.next_step || "—";
        $("ov-sip-ticket").innerHTML = c.sip_ticket
            ? `<a href="#" style="color:var(--primary);font-weight:600;text-decoration:none;">Ticket #${esc(c.sip_ticket)}</a>`
            : "N/A";
        const sipOpen = c.sip_open || 0, sipClosed = c.sip_closed || 0;
        $("ov-sip-counts").textContent = `${sipOpen} open / ${sipClosed} closed`;
    }

    // ---------------- Revenue & Renewals (ConnectWise) ----------------
    const fmtMoney = (n) => "$" + Math.round(n || 0).toLocaleString();
    function fmtDate(s) {
        if (!s) return "—";
        const d = new Date(s + "T00:00:00");
        return isNaN(d) ? s : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    }
    // Privacy masking — money figures blur until the eye toggle reveals them (HRIS-style).
    const _EYE_ON = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" style="width:16px;height:16px;"><path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.22A10.48 10.48 0 0 0 1.93 12C3.23 16.34 7.24 19.5 12 19.5c.99 0 1.95-.14 2.86-.39M6.23 6.23A10.45 10.45 0 0 1 12 4.5c4.76 0 8.77 3.16 10.07 7.5a10.52 10.52 0 0 1-4.29 5.27M6.23 6.23 3 3m3.23 3.23 3.65 3.65m7.89 7.89L21 21"/></svg>`;
    const _EYE_OFF = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" style="width:16px;height:16px;"><path stroke-linecap="round" stroke-linejoin="round" d="M2.04 12.32a1.01 1.01 0 0 1 0-.64C3.42 7.51 7.36 4.5 12 4.5c4.64 0 8.57 3.01 9.96 7.18.07.2.07.44 0 .64C20.58 16.49 16.64 19.5 12 19.5c-4.64 0-8.57-3.01-9.96-7.18Z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/></svg>`;
    let ppPrivate = true;
    const m = (n) => `<span class="pp-money">${fmtMoney(n)}</span>`;
    function applyPrivacy() {
        document.body.classList.toggle("pp-private", ppPrivate);
        const b = $("privacy-toggle");
        if (b) { b.setAttribute("aria-pressed", String(ppPrivate)); b.innerHTML = (ppPrivate ? _EYE_ON + " Show $" : _EYE_OFF + " Hide $"); }
    }
    function setupPrivacy() {
        try { ppPrivate = localStorage.getItem("pp_private") === "1"; } catch (e) { ppPrivate = false; }
        const b = $("privacy-toggle");
        if (b) b.addEventListener("click", () => {
            ppPrivate = !ppPrivate;
            try { localStorage.setItem("pp_private", ppPrivate ? "1" : "0"); } catch (e) {}
            applyPrivacy();
        });
        applyPrivacy();
    }
    function renderRenewal() {
        const cw = state.cw;
        if (!cw) return;                         // no CW agreements -> card stays hidden
        $("ov-renewal-card").style.display = "";
        const band = cw.renewalRiskBand || "—";
        const why = (cw.riskReasons || []).map((r) => {
            const cls = r.severity === "high" ? "badge-danger" : r.severity === "action" ? "badge-info" : "badge-warning";
            return `<span class="badge ${cls}" style="margin:2px 4px 2px 0;display:inline-block;">${esc(r.label)}</span>`;
        }).join("");
        const kpis = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:18px;">
            <div><div class="kpi-label">Agreements</div><div class="kpi-value">${cw.agreementCount}</div></div>
            <div><div class="kpi-label">Total MRR</div><div class="kpi-value">${m(cw.mrr)}<span style="font-size:0.7rem;color:var(--text-muted);">/mo</span></div><div style="font-size:0.72rem;color:var(--text-muted);">${m(cw.arr)} ARR</div></div>
            <div><div class="kpi-label">Renewal Risk</div><div class="kpi-value">${cw.renewalRiskScore} <span class="badge ${bandClass(band)}" style="font-size:0.7rem;">${esc(band)}</span></div><div style="font-size:0.72rem;color:var(--text-muted);">${cw.daysToNextRenewal != null ? ("next in " + cw.daysToNextRenewal + "d") : "no upcoming renewal"}</div></div>
            <div><div class="kpi-label">MRR at risk</div><div class="kpi-value" style="${cw.mrrAtRisk ? "color:var(--danger);" : ""}">${cw.mrrAtRisk ? m(cw.mrrAtRisk) : "—"}</div><div style="font-size:0.72rem;color:var(--text-muted);">${cw.atRiskCount} agreement(s)</div></div>
        </div>`;
        const whyBlock = why ? `<div style="margin-bottom:14px;"><div class="kpi-label" style="margin-bottom:6px;">Why at risk</div>${why}</div>` : "";
        const recBlock = cw.recommendation
            ? `<div style="margin-bottom:18px;padding:10px 14px;background:var(--bg-subtle,rgba(16,185,129,0.08));border-left:3px solid var(--success);border-radius:0 8px 8px 0;"><span style="font-weight:700;color:var(--success);">→ Recommended action:</span> ${esc(cw.recommendation)}</div>`
            : "";
        const body = (cw.agreements || []).map((a) => {
            const sc = a.tier === "At Risk" ? "badge-danger" : a.tier === "Watch" ? "badge-warning" : "badge-success";
            const end = a.end ? (fmtDate(a.end) + (a.daysOut != null ? ` <span style="color:var(--text-muted);font-size:0.8rem;">(${a.daysOut}d)</span>` : "")) : `<span class="badge badge-warning">no date</span>`;
            return `<tr><td style="font-weight:500;">${esc(a.name || "—")}</td><td>${esc(a.engineer || "")}</td><td>${esc(a.type)}</td><td>${m(a.mrr)}/mo</td><td>${end}</td><td><span class="badge ${sc}">${esc(a.tier)}</span></td></tr>`;
        }).join("");
        const table = `<div class="table-wrapper"><table class="custom-table"><thead><tr><th>Agreement</th><th>Engineer</th><th>Type</th><th>MRR</th><th>End date</th><th>Status</th></tr></thead><tbody>${body}</tbody></table></div>`;
        $("ov-renewal-body").innerHTML = kpis + whyBlock + recBlock + table;
    }

    // ---------------- Overview ----------------
    function actionItems() {
        const d = state.data;
        if (d.action_items && d.action_items.length) return d.action_items;
        if (d.ai && d.ai.action_items && d.ai.action_items.length) return d.ai.action_items;
        return [];
    }

    function renderOverview() {
        const d = state.data;
        const cs = d.csat_stats || {};
        const total = (cs.Positive || 0) + (cs.Neutral || 0) + (cs.Negative || 0) + (cs.Unrated || 0);
        const pct = (n) => total ? ((n / total) * 100).toFixed(1) : "0.0";

        $("ov-csat-score").textContent = `${pct(cs.Positive || 0)}%`;
        $("ov-nps-score").textContent = (d.nps_stats && d.nps_stats.Promoter != null)
            ? `${d.nps_stats.Promoter}` : "0";
        $("ov-reviews").textContent = total;
        $("ov-sip").textContent = `${d.client.sip_open || 0} / ${d.client.sip_closed || 0}`;

        $("ov-stacked-bar").innerHTML = `
            <div class="stacked-segment stacked-positive" style="width:${pct(cs.Positive || 0)}%" title="Positive: ${cs.Positive || 0}"></div>
            <div class="stacked-segment stacked-neutral" style="width:${pct(cs.Neutral || 0)}%" title="Neutral: ${cs.Neutral || 0}"></div>
            <div class="stacked-segment stacked-negative" style="width:${pct(cs.Negative || 0)}%" title="Negative: ${cs.Negative || 0}"></div>
            <div class="stacked-segment stacked-unrated" style="width:${pct(cs.Unrated || 0)}%" title="Unrated: ${cs.Unrated || 0}"></div>`;
        $("ov-legend-positive").textContent = `Positive: ${cs.Positive || 0} (${pct(cs.Positive || 0)}%)`;
        $("ov-legend-neutral").textContent = `Neutral: ${cs.Neutral || 0} (${pct(cs.Neutral || 0)}%)`;
        $("ov-legend-negative").textContent = `Negative: ${cs.Negative || 0} (${pct(cs.Negative || 0)}%)`;
        $("ov-legend-unrated").textContent = `Unrated: ${cs.Unrated || 0} (${pct(cs.Unrated || 0)}%)`;

        // AI banner
        const ai = d.ai || {};
        if (ai.risk_score != null) {
            $("ov-ai-banner").style.display = "block";
            $("ov-ai-score").textContent = ai.risk_score;
            const bandEl = $("ov-ai-band");
            bandEl.textContent = bandFromScore(ai.risk_score);
            $("ov-ai-banner").querySelector(".risk-gauge").className =
                `risk-gauge gauge-${bandFromScore(ai.risk_score).toLowerCase()}`;
            $("ov-ai-summary").textContent = ai.summary || "";
        }

        // Open action items
        const open = actionItems().filter((a) => a.status !== "Completed").slice(0, 4);
        $("ov-open-count").textContent = `${open.length} Open`;
        $("ov-recent-actions-body").innerHTML = open.length ? "" : `<tr><td colspan="3" class="no-results" style="padding:20px;">No open action items.</td></tr>`;
        open.forEach((a) => {
            const tr = document.createElement("tr");
            const badge = a.status === "In Progress" ? "badge-warning" : a.status === "Pending" ? "badge-danger" : "badge-info";
            tr.innerHTML = `<td style="font-weight:500;">${esc(a.task)}</td><td>${esc(a.owner)}</td><td><span class="badge ${badge}">${esc(a.status)}</span></td>`;
            $("ov-recent-actions-body").appendChild(tr);
        });
    }

    // ---------------- AI Insights ----------------
    function renderAI() {
        const ai = state.data.ai;
        const host = $("ai-content");
        if (!ai || ai.risk_score == null) {
            host.innerHTML = `<div class="card"><div class="no-results">No AI analysis available for this partner.${ai && ai._error ? "<br><small>" + esc(ai._error) + "</small>" : ""}</div></div>`;
            return;
        }
        const drivers = (ai.drivers || []).map((dr) => `
            <div class="insight-row">
                <span class="badge ${sevClass(dr.severity)}" style="flex-shrink:0;">${esc(dr.severity || "")}</span>
                <div><div class="insight-factor">${esc(dr.factor)}</div><div class="insight-evidence">${esc(dr.evidence || "")}</div></div>
            </div>`).join("");
        const rem = (ai.remediation || []).map((r) => `
            <div class="insight-row">
                <span class="badge ${sevClass(r.priority)}" style="flex-shrink:0;">${esc(r.priority || "")}</span>
                <div><div class="insight-factor">${esc(r.action)}</div>
                    <div class="insight-evidence">${esc(r.rationale || "")}</div>
                    ${r.owner ? `<div class="insight-owner">Owner: ${esc(r.owner)}</div>` : ""}</div>
            </div>`).join("");

        host.innerHTML = `
            <div class="card dashboard-full-width ai-banner" style="margin-bottom:24px;">
                <div class="ai-banner-grid">
                    <div class="risk-gauge gauge-${bandFromScore(ai.risk_score).toLowerCase()}">
                        <div class="risk-gauge-score">${esc(ai.risk_score)}</div>
                        <div class="risk-gauge-band">${bandFromScore(ai.risk_score)}</div>
                        <div class="risk-gauge-label">Churn Risk</div>
                    </div>
                    <div class="ai-banner-text">
                        <div class="card-title" style="margin-bottom:8px;">Grok Executive Assessment</div>
                        <p style="color:var(--text-secondary);">${esc(ai.summary)}</p>
                        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
                            <span class="badge badge-outline">Sentiment: ${esc(ai.sentiment_trend || "—")}</span>
                            <span class="badge badge-outline">Confidence: ${esc(ai.confidence || "—")}</span>
                            <span class="badge badge-outline">Model: ${esc(ai._model || "grok-4-1-fast-reasoning")}</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="dashboard-grid">
                <div class="card">
                    <div class="card-header"><h2 class="card-title">Churn Risk Drivers</h2><span class="badge badge-danger">${(ai.drivers || []).length}</span></div>
                    <div class="insight-list">${drivers || '<div class="no-results">None identified.</div>'}</div>
                </div>
                <div class="card">
                    <div class="card-header"><h2 class="card-title">Proactive Remediation</h2><span class="badge badge-success">${(ai.remediation || []).length}</span></div>
                    <div class="insight-list">${rem || '<div class="no-results">None suggested.</div>'}</div>
                </div>
            </div>`;
    }

    // ---------------- Action Tracker ----------------
    function renderActionsPage() {
        const items = actionItems();
        $("action-count").textContent = `${items.length} Items`;
        const body = $("action-table-body");
        body.innerHTML = items.length ? "" : `<tr><td colspan="5" class="no-results" style="padding:24px;">No action items extracted.</td></tr>`;
        items.forEach((a) => {
            let badge = "badge-info";
            if (a.status === "Completed") badge = "badge-success";
            else if (a.status === "In Progress") badge = "badge-warning";
            else if (a.status === "Pending") badge = "badge-danger";
            const tr = document.createElement("tr");
            tr.innerHTML = `<td style="font-weight:600;">${esc(a.task)}</td><td>${esc(a.owner)}</td><td>${esc(a.due)}</td><td><span class="badge ${badge}">${esc(a.status)}</span></td><td><span style="font-size:0.8rem;color:var(--text-muted);">${esc(a.source)}</span></td>`;
            body.appendChild(tr);
        });

        // Reusable accordion builder (used by both the MoM and the SIP cards). The
        // active-toggle is scoped to the owning list so opening a SIP note doesn't
        // collapse an open MoM note and vice-versa.
        function buildAccordion(container, rows, fmt) {
            container.innerHTML = "";
            (rows || []).forEach((row) => {
                const item = document.createElement("div");
                item.className = "accordion-item";
                const d = row[fmt.dateKey] ? new Date(row[fmt.dateKey]) : null;
                const dateStr = d && !isNaN(d) ? d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" }) : "";
                item.innerHTML = `
                    <div class="accordion-header">
                        <div class="accordion-header-left">
                            ${fmt.icon}
                            <span class="accordion-title">${esc(fmt.title(row))}</span>
                            <span class="accordion-date">${dateStr}</span>
                        </div>
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="accordion-icon"><path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
                    </div>
                    <div class="accordion-content"><div class="accordion-body"><div style="font-size:0.9rem;color:var(--text-secondary);line-height:1.7;">${fmt.body(row)}</div></div></div>`;
                item.querySelector(".accordion-header").addEventListener("click", () => {
                    const wasActive = item.classList.contains("active");
                    container.querySelectorAll(".accordion-item").forEach((a) => a.classList.remove("active"));
                    if (!wasActive) item.classList.add("active");
                });
                container.appendChild(item);
            });
        }

        // MoM service-review notes
        buildAccordion($("accordion-list"), state.data.historical_calls || [], {
            dateKey: "date",
            icon: CAL_ICON,
            title: (c) => c.summary || "Service Review",
            body: (c) => esc(c.notes || "")
                .replace(/1\.\s+Meeting\s+Summary/gi, "<h4 class='notes-h4'>1. Meeting Summary</h4>")
                .replace(/2\.\s+Action\s+Items/gi, "<h4 class='notes-h4' style='margin-top:16px;'>2. Action Items</h4>")
                .replace(/\n/g, "<br>"),
        });

        // SIP Progress card: one entry per SIP ticket (grouped, with status badge + date
        // range). Active SIPs show the AI journey summary + raw updates behind an expander;
        // closed SIPs collapse to a one-liner. Hidden entirely when the partner has no SIPs.
        renderSipCard(state.data.sips || []);
    }

    const CAL_ICON = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width:20px;height:20px;color:var(--primary);"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" /></svg>`;

    // Map a SIP status_class to a badge style.
    function sipBadge(cls) {
        if (cls === "closed") return "badge-success";
        if (cls === "hold") return "badge-warning";
        return "badge-info"; // open / active
    }
    function fmtDate(s) {
        const d = s ? new Date(s) : null;
        return d && !isNaN(d) ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
    }
    function renderSipCard(sips) {
        const card = $("sip-card");
        if (!sips.length) { card.style.display = "none"; return; }
        card.style.display = "";
        const active = sips.filter((s) => s.status_class !== "closed").length;
        $("sip-count").textContent = `${sips.length} SIP${sips.length === 1 ? "" : "s"}` + (active ? ` · ${active} active` : "");
        const acc = $("sip-accordion-list");
        acc.innerHTML = "";
        sips.forEach((s) => {
            const range = [fmtDate(s.started), fmtDate(s.latest)].filter(Boolean);
            const rangeStr = range.length === 2 && range[0] !== range[1] ? `${range[0]} → ${range[1]}` : (range[range.length - 1] || "");
            const updates = s.updates || [];
            let body = "";
            if (s.summary) {
                body += `<div style="font-size:0.92rem;color:var(--text-secondary);line-height:1.7;">${esc(s.summary)}</div>`;
                if (s.latest_status) body += `<div style="margin-top:10px;font-size:0.8rem;font-weight:700;letter-spacing:.04em;color:var(--primary);">LATEST STATUS: ${esc(s.latest_status)}</div>`;
            }
            if (updates.length) {
                const inner = updates.map((u) => {
                    const note = esc(u.note || "")
                        .replace(/(SIP PROGRESS UPDATE[^\n]*)/i, "<strong>$1</strong>")
                        .replace(/(UTILIZATION|TICKET CLOSURE|PARAMETER COMPLIANCE|GOVERNANCE REVIEW|OVERALL STATUS)/g, "<h4 class='notes-h4' style='margin-top:12px;'>$1</h4>")
                        .replace(/\n/g, "<br>");
                    return `<div style="padding:12px 0;border-top:1px solid var(--border,#eee);"><div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px;">${fmtDate(u.datetime)} · ${esc(u.who || "")}</div><div style="font-size:0.88rem;color:var(--text-secondary);line-height:1.7;">${note}</div></div>`;
                }).join("");
                body += `<details style="margin-top:${s.summary ? "12px" : "0"};"><summary style="cursor:pointer;font-size:0.82rem;color:var(--primary);font-weight:600;">Show ${updates.length} update${updates.length === 1 ? "" : "s"}</summary>${inner}</details>`;
            }
            if (!body) body = `<div class="no-results" style="padding:8px 0;">No progress notes recorded on this SIP.</div>`;

            const item = document.createElement("div");
            item.className = "accordion-item";
            item.innerHTML = `
                <div class="accordion-header">
                    <div class="accordion-header-left">
                        ${CAL_ICON}
                        <span class="accordion-title">${esc(s.subject || "SIP")}</span>
                        <span class="badge ${sipBadge(s.status_class)}" title="${esc(s.status || s.status_label)}">${esc(s.status_label || "Open")}</span>
                        <span class="accordion-date">${rangeStr}</span>
                    </div>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="accordion-icon"><path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
                </div>
                <div class="accordion-content"><div class="accordion-body">${body}</div></div>`;
            item.querySelector(".accordion-header").addEventListener("click", (e) => {
                if (e.target.closest("details")) return; // inner expander shouldn't toggle the card
                const wasActive = item.classList.contains("active");
                acc.querySelectorAll(".accordion-item").forEach((a) => a.classList.remove("active"));
                if (!wasActive) item.classList.add("active");
            });
            if (s.status_class !== "closed") item.classList.add("active"); // active SIPs open by default
            acc.appendChild(item);
        });
    }

    // ---------------- Feedback (CSAT / NPS) ----------------
    function setupFeedbackPage() {
        $("tab-btn-csat").addEventListener("click", () => {
            $("tab-btn-csat").classList.add("active"); $("tab-btn-nps").classList.remove("active");
            $("csat-filters-container").style.display = "flex"; state.feedbackTab = "csat"; renderFeedbackGrid();
        });
        $("tab-btn-nps").addEventListener("click", () => {
            $("tab-btn-nps").classList.add("active"); $("tab-btn-csat").classList.remove("active");
            $("csat-filters-container").style.display = "none"; state.feedbackTab = "nps"; renderFeedbackGrid();
        });
        [["pill-all", "All"], ["pill-pos", "Positive"], ["pill-neu", "Neutral"], ["pill-neg", "Negative"]].forEach(([id]) => {
            $(id).addEventListener("click", () => {
                document.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
                $(id).classList.add("active");
                state.csatFilter = $(id).getAttribute("data-filter");
                renderFeedbackGrid();
            });
        });
    }
    function renderFeedbackGrid() {
        const grid = $("feedback-grid");
        grid.innerHTML = "";
        if (state.feedbackTab === "csat") {
            let list = state.data.csat_comments || [];
            if (state.csatFilter !== "All") list = list.filter((c) => c.rating === state.csatFilter);
            if (!list.length) { grid.innerHTML = `<div class="no-results" style="grid-column:1/-1;">No reviews for "${esc(state.csatFilter)}".</div>`; return; }
            list.slice(0, 150).forEach((c) => {
                let cls = "badge-success";
                if (c.rating === "Neutral") cls = "badge-warning"; else if (c.rating === "Negative") cls = "badge-danger";
                const d = c.date ? new Date(c.date) : null;
                const ds = d && !isNaN(d) ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
                const card = document.createElement("div");
                card.className = "feedback-card";
                card.innerHTML = `<div><div class="feedback-card-header"><div class="feedback-author-info"><span class="feedback-author-name">${esc(c.contact || "Anonymous")}</span><span class="feedback-date">${ds}</span></div><span class="badge ${cls}">${esc(c.rating)}</span></div><div class="feedback-text">"${esc(c.comment)}"</div></div><div class="feedback-footer-details">Ticket: ${esc(c.ticket_name)} (ID: ${esc(c.ticket_id)})</div>`;
                grid.appendChild(card);
            });
        } else {
            const list = state.data.nps_comments || [];
            if (!list.length) { grid.innerHTML = `<div class="no-results" style="grid-column:1/-1;">No NPS comments logged.</div>`; return; }
            list.forEach((n) => {
                const d = n.date ? new Date(n.date) : null;
                const ds = d && !isNaN(d) ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
                const card = document.createElement("div");
                card.className = "feedback-card";
                card.innerHTML = `<div><div class="feedback-card-header"><div class="feedback-author-info"><span class="feedback-author-name">${esc(n.respondent_name || n.respondent)}</span><span class="feedback-date">${ds}</span></div><span class="badge badge-success" style="font-size:0.9rem;padding:6px 12px;">Score: ${esc(n.score)}</span></div><div class="feedback-text">"${esc(n.comment)}"</div></div><div class="feedback-footer-details">Campaign: ${esc(n.campaign || "—")}</div>`;
                grid.appendChild(card);
            });
        }
    }

    // ---------------- Transcripts ----------------
    function initTranscriptsPage() {
        const panel = $("transcript-option-list");
        panel.innerHTML = "";
        (state.data.transcripts || []).forEach((t, index) => {
            const item = document.createElement("div");
            item.className = `transcript-option-item ${index === state.selectedTranscriptIndex ? "active" : ""}`;
            const shortName = (t.filename || "").replace(/\.docx$/i, "");
            item.innerHTML = `<div class="transcript-option-title">${esc(shortName)}</div><div class="transcript-option-meta"><span>${esc(t.date || "")}</span><span>${esc(t.duration || "")}</span></div>`;
            item.addEventListener("click", () => {
                document.querySelectorAll("#transcript-option-list .transcript-option-item").forEach((el) => el.classList.remove("active"));
                item.classList.add("active");
                state.selectedTranscriptIndex = index;
                renderTranscriptDialogue();
            });
            panel.appendChild(item);
        });
        $("dialogue-search").addEventListener("input", (e) => { state.transcriptSearchQuery = e.target.value.toLowerCase(); renderTranscriptDialogue(); });
        document.querySelectorAll(".keyword-pill").forEach((pill) => {
            pill.addEventListener("click", () => {
                const kw = pill.getAttribute("data-kw");
                if (state.activeKeywordFilter === kw) { pill.classList.remove("active"); state.activeKeywordFilter = ""; }
                else { document.querySelectorAll(".keyword-pill").forEach((p) => p.classList.remove("active")); pill.classList.add("active"); state.activeKeywordFilter = kw; }
                renderTranscriptDialogue();
            });
        });
    }
    function renderTranscriptDialogue() {
        const t = (state.data.transcripts || [])[state.selectedTranscriptIndex];
        const stream = $("dialogue-stream");
        if (!t) { stream.innerHTML = `<div class="no-results">No transcripts available.</div>`; $("dialogue-title").textContent = "No transcript"; return; }
        $("dialogue-title").textContent = t.title || t.filename;
        $("dialogue-subtitle").textContent = `Date: ${t.date || "—"} | Duration: ${t.duration || "—"} | ${(t.dialogue || []).length} turns`;
        stream.innerHTML = "";
        let list = t.dialogue || [];
        const q = state.transcriptSearchQuery, kw = state.activeKeywordFilter;
        if (q || kw) {
            list = list.filter((turn) => {
                const txt = turn.text.toLowerCase(), sp = turn.speaker.toLowerCase();
                let ms = true; if (q) ms = txt.includes(q) || sp.includes(q);
                let mk = true;
                if (kw === "sla") mk = /sla|response time|target/.test(txt);
                else if (kw === "pip_sip") mk = /pip|sip|monitoring|plan/.test(txt);
                else if (kw === "unreliability") mk = /absent|attendance|unreliable|replace|unplanned/.test(txt);
                else if (kw === "improvement") mk = /coaching|improve|training|progress|success/.test(txt);
                return ms && mk;
            });
        }
        if (!list.length) { stream.innerHTML = `<div class="no-results">No dialogue matches your filter/search.</div>`; return; }
        list.forEach((turn) => {
            const isItbd = ITBD_SPEAKERS.some((s) => turn.speaker.includes(s));
            const div = document.createElement("div");
            div.className = `dialogue-turn ${isItbd ? "itbd" : "client"}`;
            let text = esc(turn.text)
                .replace(/\b(pip|sip|sla|absent|attendance|unreliable|unreliability|mistake|mistakes|avoiding|missed)\b/gi, (m) => `<span class="highlight-risk">${m}</span>`)
                .replace(/\b(improvement|coaching|training|completed|closed|correct|success|positive|improved)\b/gi, (m) => `<span class="highlight-itbd">${m}</span>`);
            div.innerHTML = `<div class="turn-meta"><span class="turn-speaker">${esc(turn.speaker)}</span><span class="turn-time">${esc(turn.timestamp)}</span></div><div class="turn-bubble">${text}</div>`;
            stream.appendChild(div);
        });
    }

    // ---------------- Decks ----------------
    function initDecksPage() {
        const panel = $("deck-option-list");
        const decks = state.data.decks || [];
        panel.innerHTML = "";
        if (!decks.length) { panel.innerHTML = `<div class="no-results" style="padding:20px;">No decks attached.</div>`; return; }
        decks.forEach((d, index) => {
            const item = document.createElement("div");
            item.className = `transcript-option-item ${index === state.selectedDeckIndex ? "active" : ""}`;
            item.innerHTML = `<div class="transcript-option-title">${esc(d.filename || ("Deck " + (index + 1)))}</div><div class="transcript-option-meta"><span>Ticket #${esc(d.ticket_id)}</span><span>${(d.markdown || "").length} chars</span></div>`;
            item.addEventListener("click", () => {
                document.querySelectorAll("#deck-option-list .transcript-option-item").forEach((el) => el.classList.remove("active"));
                item.classList.add("active");
                state.selectedDeckIndex = index;
                renderDeck();
            });
            panel.appendChild(item);
        });
    }
    function renderDeck() {
        const decks = state.data.decks || [];
        const d = decks[state.selectedDeckIndex];
        if (!d) { $("deck-content").innerHTML = `<div class="no-results">No deck content.</div>`; return; }
        $("deck-title").textContent = d.filename || `Deck #${state.selectedDeckIndex + 1}`;
        $("deck-subtitle").textContent = `Ticket #${d.ticket_id} · converted via MarkItDown`;
        $("deck-content").innerHTML = `<pre class="deck-pre">${esc(d.markdown || "")}</pre>`;
    }

    // ---------------- Loading / error states ----------------
    function showLoading() {
        const host = document.querySelector("#page-overview") || document.querySelector(".main-content");
        if (host) host.insertAdjacentHTML("afterbegin",
            `<div id="pp-loading" class="pp-loading"><div class="pp-spinner" role="status" aria-label="Loading"></div><div>Loading partner data…</div></div>`);
    }
    function hideLoading() { const el = $("pp-loading"); if (el) el.remove(); }
    function showLoadError(e) {
        const isProd = !!(window.PP_AUTH && window.PP_AUTH.mode === "prod");
        const hint = isProd
            ? `We couldn't load this partner's data. This is usually a transient network or sign-in issue — please try again.`
            : `${esc(e && e.message)} — has it been built? Run <code>python -m extract.build_all</code>`;
        document.querySelector(".main-content").innerHTML =
            `<div class="page-container active"><div class="card"><div class="no-results">Could not load partner "<b>${esc(slug)}</b>".<br><small>${hint}</small>` +
            (isProd ? `<div class="pp-error-actions"><button type="button" class="pp-retry-btn" onclick="location.reload()">Retry</button></div>` : ``) +
            `<br><br><a class="badge badge-info" href="index.html">&larr; Back to all partners</a></div></div></div>`;
    }

    // ---------------- Init ----------------
    async function init() {
        setupNavigation();
        showLoading();
        try {
            await window.PP_AUTH.ready();
            // Partner 360 data: prod reassembles it from the sharded Firestore
            // docs (partners/<slug> + detail/profile + subcollections); dev reads
            // the local data/<slug>.json blob. Same shape either way. See auth.js.
            state.data = await window.PP_AUTH.loadPartner(slug);
        } catch (e) {
            hideLoading();
            showLoadError(e);
            return;
        }
        // CW agreements (Renewal Risk) — optional; find this partner's row by slug.
        try {
            if (window.PP_AUTH.loadCwAgreements) {
                const cw = await window.PP_AUTH.loadCwAgreements();
                state.cw = (cw && cw.rows) ? (cw.rows.find((r) => r.slug === slug) || null) : null;
            }
        } catch (e) { state.cw = null; }
        hideLoading();
        setupPrivacy();
        initClientMeta();
        renderOverview();
        renderRenewal();
        renderAI();
        renderActionsPage();
        setupFeedbackPage();
        renderFeedbackGrid();
        initTranscriptsPage();
        renderTranscriptDialogue();
        initDecksPage();
    }

    document.addEventListener("DOMContentLoaded", init);
})();
