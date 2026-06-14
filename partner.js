// PartnerPulse — per-partner detail page (data-driven via fetch)
(function () {
    "use strict";

    const qs = new URLSearchParams(location.search);
    const slug = qs.get("partner") || "logically";

    const state = {
        data: null,
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
    // gpt-5.4 risk_band, which mis-calibrated vs its own score (e.g. 63 → "Medium").
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
                        <div class="card-title" style="margin-bottom:8px;">gpt-5.4 Executive Assessment</div>
                        <p style="color:var(--text-secondary);">${esc(ai.summary)}</p>
                        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
                            <span class="badge badge-outline">Sentiment: ${esc(ai.sentiment_trend || "—")}</span>
                            <span class="badge badge-outline">Confidence: ${esc(ai.confidence || "—")}</span>
                            <span class="badge badge-outline">Model: ${esc(ai._model || "gpt-5.4")}</span>
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

        const acc = $("accordion-list");
        acc.innerHTML = "";
        (state.data.historical_calls || []).forEach((call, index) => {
            const item = document.createElement("div");
            item.className = "accordion-item";
            const d = call.date ? new Date(call.date) : null;
            const dateStr = d && !isNaN(d) ? d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" }) : "";
            const notes = esc(call.notes || "")
                .replace(/1\.\s+Meeting\s+Summary/gi, "<h4 class='notes-h4'>1. Meeting Summary</h4>")
                .replace(/2\.\s+Action\s+Items/gi, "<h4 class='notes-h4' style='margin-top:16px;'>2. Action Items</h4>")
                .replace(/\n/g, "<br>");
            item.innerHTML = `
                <div class="accordion-header" data-index="${index}">
                    <div class="accordion-header-left">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width:20px;height:20px;color:var(--primary);"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" /></svg>
                        <span class="accordion-title">${esc(call.summary || "Service Review")}</span>
                        <span class="accordion-date">${dateStr}</span>
                    </div>
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="accordion-icon"><path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" /></svg>
                </div>
                <div class="accordion-content"><div class="accordion-body"><div style="font-size:0.9rem;color:var(--text-secondary);line-height:1.7;">${notes}</div></div></div>`;
            item.querySelector(".accordion-header").addEventListener("click", () => {
                const wasActive = item.classList.contains("active");
                document.querySelectorAll(".accordion-item").forEach((a) => a.classList.remove("active"));
                if (!wasActive) item.classList.add("active");
            });
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

    // ---------------- Init ----------------
    async function init() {
        setupNavigation();
        try {
            const res = await fetch(`data/${slug}.json`, { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            state.data = await res.json();
        } catch (e) {
            document.querySelector(".main-content").innerHTML =
                `<div class="page-container active"><div class="card"><div class="no-results">Could not load partner "<b>${esc(slug)}</b>".<br><small>${esc(e.message)} — has it been built? Run <code>python -m extract.build_all</code></small><br><br><a class="badge badge-info" href="index.html">← Back to all partners</a></div></div></div>`;
            return;
        }
        initClientMeta();
        renderOverview();
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
