// PartnerPulse — portfolio (all partners) overview + charts
(function () {
    "use strict";
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    // Palette (matches styles.css)
    const C = {
        primary: "#6366f1", success: "#10b981", warning: "#f59e0b", danger: "#ef4444",
        muted: "#94a3b8", grid: "rgba(148,163,184,0.18)", text: "#475569",
    };
    const FONT = "'Plus Jakarta Sans', sans-serif";

    let partners = [];
    let pf = {};            // portfolio aggregates
    let ragFilter = "All";
    let sortKey = "risk_score";
    let sortDir = -1;
    let charts = {};

    function ragClass(rag) {
        const r = (rag || "").toLowerCase();
        return r === "red" ? "badge-danger" : r === "amber" ? "badge-warning" : r === "green" ? "badge-success" : "badge-outline";
    }
    function bandClass(band) {
        const b = (band || "").toLowerCase();
        return (b === "critical" || b === "high") ? "badge-danger" : b === "medium" ? "badge-warning" : b === "low" ? "badge-success" : "badge-outline";
    }
    function riskColor(s) {
        if (s == null) return C.muted;
        if (s >= 70) return C.danger;
        if (s >= 45) return C.warning;
        if (s >= 25) return "#eab308";
        return C.success;
    }
    function trendBadge(t) {
        const x = (t || "").toLowerCase();
        if (x === "declining") return `<span class="badge badge-danger">▼ Declining</span>`;
        if (x === "improving") return `<span class="badge badge-success">▲ Improving</span>`;
        if (x === "stable") return `<span class="badge badge-outline">▬ Stable</span>`;
        return `<span class="badge badge-outline">—</span>`;
    }

    // ---------------- Nav ----------------
    function setupNav() {
        document.querySelectorAll(".nav-link-item").forEach((item) => {
            item.addEventListener("click", (e) => {
                e.preventDefault();
                const view = item.getAttribute("data-view");
                document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
                item.closest(".nav-item").classList.add("active");
                document.querySelectorAll(".page-container").forEach((p) => p.classList.toggle("active", p.id === `view-${view}`));
                $("view-title").textContent = view === "partners" ? "Partner 360" : "Executive Overview";
                // Charts need a resize nudge when their container becomes visible.
                if (view === "overview") Object.values(charts).forEach((c) => c && c.resize());
            });
        });
    }

    // ---------------- KPIs ----------------
    function renderKPIs() {
        const valid = partners.filter((p) => !p.error);
        const scored = valid.filter((p) => p.risk_score != null);
        const avg = scored.length ? Math.round(scored.reduce((s, p) => s + p.risk_score, 0) / scored.length) : 0;
        const high = scored.filter((p) => p.risk_score >= 45).length;
        const declining = valid.filter((p) => (p.sentiment_trend || "").toLowerCase() === "declining").length;
        const sips = valid.filter((p) => p.sip_ticket).length;

        const cards = [
            { label: "Partners Tracked", value: valid.length, cls: "primary" },
            { label: "Avg Churn Risk", value: avg, cls: avg >= 45 ? "danger" : avg >= 25 ? "warning" : "success" },
            { label: "High Risk (≥45)", value: high, cls: "danger" },
            { label: "Active SIPs / Declining", value: `${sips} / ${declining}`, cls: "warning" },
        ];
        $("kpi-grid").innerHTML = cards.map((c) => `
            <div class="kpi-card">
                <div class="kpi-icon-wrapper ${c.cls}">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" style="width:24px;height:24px;"><path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" /></svg>
                </div>
                <div class="kpi-info"><span class="kpi-label">${c.label}</span><span class="kpi-value">${c.value}</span></div>
            </div>`).join("");
    }

    // ---------------- Charts ----------------
    function renderTrendChart() {
        const t = pf.sentiment_trend || [];
        const ctx = $("trendChart");
        if (!ctx || !t.length) return;
        charts.trend = new Chart(ctx, {
            data: {
                labels: t.map((w) => w.label),
                datasets: [
                    {
                        type: "line", label: "CSAT positive %", yAxisID: "y",
                        data: t.map((w) => w.csat_positive_pct),
                        borderColor: C.success, backgroundColor: "rgba(16,185,129,0.12)",
                        borderWidth: 2, tension: 0.35, fill: true, spanGaps: true,
                        pointRadius: 3, pointBackgroundColor: C.success,
                    },
                    {
                        type: "bar", label: "Reviews", yAxisID: "y1",
                        data: t.map((w) => w.csat_total),
                        backgroundColor: "rgba(99,102,241,0.25)", borderRadius: 4, barThickness: 14,
                    },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: { legend: { labels: { font: { family: FONT }, usePointStyle: true, boxWidth: 8 } } },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { family: FONT, size: 10 }, color: C.muted } },
                    y: { position: "left", min: 0, max: 100, grid: { color: C.grid }, ticks: { font: { family: FONT, size: 10 }, color: C.muted, callback: (v) => v + "%" }, title: { display: true, text: "CSAT +%", font: { family: FONT, size: 10 }, color: C.muted } },
                    y1: { position: "right", min: 0, grid: { drawOnChartArea: false }, ticks: { font: { family: FONT, size: 10 }, color: C.muted }, title: { display: true, text: "Reviews", font: { family: FONT, size: 10 }, color: C.muted } },
                },
            },
        });
    }

    function renderRiskDonut() {
        const d = pf.risk_distribution || { High: 0, Watch: 0, Healthy: 0 };
        const ctx = $("riskDonut");
        if (!ctx) return;
        const vals = [d.High || 0, d.Watch || 0, d.Healthy || 0];
        const cols = [C.danger, C.warning, C.success];
        const labels = ["High (≥45)", "Watch (25–44)", "Healthy (<25)"];
        charts.donut = new Chart(ctx, {
            type: "doughnut",
            data: { labels, datasets: [{ data: vals, backgroundColor: cols, borderWidth: 2, borderColor: "#fff", hoverOffset: 6 }] },
            options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { display: false } } },
        });
        $("donut-legend").innerHTML = labels.map((l, i) => `
            <div class="legend-item"><span class="legend-dot" style="background:${cols[i]};"></span>${l} <b style="margin-left:auto;">${vals[i]}</b></div>`).join("");
    }

    function renderSourceChart() {
        const m = pf.feedback_mix || { csat: {}, nps: {} };
        const ctx = $("sourceChart");
        if (!ctx) return;
        charts.source = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ["CSAT", "NPS"],
                datasets: [
                    { label: "Positive / Promoter", data: [m.csat.Positive || 0, m.nps.Promoter || 0], backgroundColor: C.success, borderRadius: 4 },
                    { label: "Neutral / Passive", data: [m.csat.Neutral || 0, m.nps.Passive || 0], backgroundColor: C.muted, borderRadius: 4 },
                    { label: "Negative / Detractor", data: [m.csat.Negative || 0, m.nps.Detractor || 0], backgroundColor: C.danger, borderRadius: 4 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { labels: { font: { family: FONT, size: 11 }, usePointStyle: true, boxWidth: 8 } } },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: { font: { family: FONT }, color: C.text } },
                    y: { stacked: true, grid: { color: C.grid }, ticks: { font: { family: FONT, size: 10 }, color: C.muted } },
                },
            },
        });
    }

    function renderDriversChart() {
        const d = pf.top_drivers || [];
        const ctx = $("driversChart");
        if (!ctx || !d.length) return;
        charts.drivers = new Chart(ctx, {
            type: "bar",
            data: {
                labels: d.map((x) => x.theme),
                datasets: [{
                    label: "Relative weight",
                    data: d.map((x) => x.score),
                    backgroundColor: d.map((x) => x.score >= 0.66 ? C.danger : x.score >= 0.4 ? C.warning : "#22c55e"),
                    borderRadius: 5, barThickness: 18,
                }],
            },
            options: {
                indexAxis: "y", responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `weight ${c.raw} · ${d[c.dataIndex].count} mentions` } } },
                scales: {
                    x: { min: 0, max: 1, grid: { color: C.grid }, ticks: { font: { family: FONT, size: 10 }, color: C.muted } },
                    y: { grid: { display: false }, ticks: { font: { family: FONT, size: 11 }, color: C.text } },
                },
            },
        });
    }

    // ---------------- Partner 360 table ----------------
    function sortedFiltered() {
        let rows = partners.filter((p) => !p.error);
        if (ragFilter !== "All") rows = rows.filter((p) => (p.rag || "") === ragFilter);
        rows.sort((a, b) => {
            let va = a[sortKey], vb = b[sortKey];
            if (va == null) va = sortDir === -1 ? -Infinity : Infinity;
            if (vb == null) vb = sortDir === -1 ? -Infinity : Infinity;
            if (typeof va === "string") return sortDir * va.localeCompare(vb);
            return sortDir * (va - vb);
        });
        return rows;
    }

    function renderTable() {
        const rows = sortedFiltered();
        const body = $("portfolio-body");
        if (!rows.length) { body.innerHTML = `<tr><td colspan="9" class="no-results">No partners match.</td></tr>`; return; }
        body.innerHTML = "";
        rows.forEach((p) => {
            const tr = document.createElement("tr");
            tr.className = "portfolio-row";
            tr.addEventListener("click", () => { location.href = `partner.html?partner=${encodeURIComponent(p.slug)}`; });
            const s = p.risk_score;
            tr.innerHTML = `
                <td><div class="pt-name"><span class="pt-avatar">${esc((p.name || "?").charAt(0))}</span><div><div style="font-weight:600;">${esc(p.name)}</div><div style="font-size:0.74rem;color:var(--text-muted);">#${esc(p.client_id)} ${p.vip ? "· ⭐ VIP" : ""}</div></div></div></td>
                <td><span class="badge ${ragClass(p.rag)}">${esc(p.rag || "—")}</span></td>
                <td>${esc(p.cancel_risk || "—")}</td>
                <td><div class="risk-cell"><div class="risk-bar-bg"><div class="risk-bar-fill" style="width:${s == null ? 0 : s}%;background:${riskColor(s)};"></div></div><span class="risk-num" style="color:${riskColor(s)};">${s == null ? "—" : s}</span><span class="badge ${bandClass(p.risk_band)}" style="font-size:0.62rem;">${esc(p.risk_band || "")}</span></div></td>
                <td>${trendBadge(p.sentiment_trend)}</td>
                <td>${p.csat_positive_pct != null ? p.csat_positive_pct + "%" : "—"} <span style="color:var(--text-muted);font-size:0.72rem;">(${p.csat_total || 0})</span></td>
                <td>${p.nps_promoters || 0}${p.nps_detractors ? ` <span style="color:var(--danger);font-size:0.72rem;">-${p.nps_detractors}</span>` : ""}</td>
                <td><span style="font-size:0.8rem;color:var(--text-secondary);">${esc(p.service_line || "—")}</span></td>
                <td><span class="row-arrow">→</span></td>`;
            body.appendChild(tr);
        });
    }

    function renderRiskCards() {
        const top = sortedFiltered().filter((p) => p.risk_score != null).slice(0, 3);
        $("risk-cards").innerHTML = top.map((p) => `
            <a class="risk-card" href="partner.html?partner=${encodeURIComponent(p.slug)}">
                <div class="risk-card-head"><span style="font-family:var(--font-heading);font-weight:700;">${esc(p.name)}</span><span class="risk-card-score" style="color:${riskColor(p.risk_score)};">${p.risk_score}</span></div>
                <div style="display:flex;gap:6px;margin:8px 0;flex-wrap:wrap;"><span class="badge ${ragClass(p.rag)}">${esc(p.rag || "—")}</span><span class="badge ${bandClass(p.risk_band)}">${esc(p.risk_band || "")}</span>${trendBadge(p.sentiment_trend)}</div>
                <p class="risk-card-summary">${esc(p.summary || "")}</p>
            </a>`).join("") || `<div class="no-results">No scored partners.</div>`;
    }

    function setupControls() {
        document.querySelectorAll("#rag-filters .filter-pill").forEach((pill) => {
            pill.addEventListener("click", () => {
                document.querySelectorAll("#rag-filters .filter-pill").forEach((p) => p.classList.remove("active"));
                pill.classList.add("active");
                ragFilter = pill.getAttribute("data-rag");
                renderTable(); renderRiskCards();
            });
        });
        document.querySelectorAll(".portfolio-table th[data-sort]").forEach((th) => {
            th.style.cursor = "pointer";
            th.addEventListener("click", () => {
                const key = th.getAttribute("data-sort");
                if (sortKey === key) sortDir *= -1;
                else { sortKey = key; sortDir = (key === "name" || key === "service_line") ? 1 : -1; }
                document.querySelectorAll(".portfolio-table th").forEach((h) => h.classList.remove("sorted-asc", "sorted-desc"));
                th.classList.add(sortDir === -1 ? "sorted-desc" : "sorted-asc");
                renderTable();
            });
        });
    }

    function renderFooter() {
        const valid = partners.filter((p) => !p.error).length;
        $("partner-count").textContent = `${valid} partners`;
        const gen = pf.generated_at ? new Date(pf.generated_at) : null;
        if (gen && !isNaN(gen)) $("last-sync").textContent = "Last sync: " + gen.toLocaleString("en-US", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
        $("overview-footnote").textContent = "Churn scores are produced by Azure gpt-5.4 from HALO PSA risk flags, TeamGPS CSAT/NPS, and NLP over service-review transcripts & decks. Bulk ticket SLA/status is intentionally excluded as it is an end-customer metric, not a partner-churn signal.";
    }

    async function init() {
        setupNav();
        try {
            const res = await fetch("data/_index.json", { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const idx = await res.json();
            partners = idx.partners || [];
            pf = idx.portfolio || {};
        } catch (e) {
            $("kpi-grid").innerHTML = `<div class="no-results" style="grid-column:1/-1;">Could not load portfolio index.<br><small>${esc(e.message)} — run <code>python -m extract.build_all</code></small></div>`;
            return;
        }
        renderKPIs();
        renderTrendChart();
        renderRiskDonut();
        renderSourceChart();
        renderDriversChart();
        setupControls();
        renderTable();
        renderRiskCards();
        renderFooter();
    }
    document.addEventListener("DOMContentLoaded", init);
})();
