// PartnerPulse — portfolio (all partners) overview
(function () {
    "use strict";
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    let partners = [];
    let ragFilter = "All";
    let sortKey = "risk_score";
    let sortDir = -1; // -1 desc, 1 asc

    function ragClass(rag) {
        const r = (rag || "").toLowerCase();
        if (r === "red") return "badge-danger";
        if (r === "amber") return "badge-warning";
        if (r === "green") return "badge-success";
        return "badge-outline";
    }
    function bandClass(band) {
        const b = (band || "").toLowerCase();
        if (b === "critical" || b === "high") return "badge-danger";
        if (b === "medium") return "badge-warning";
        if (b === "low") return "badge-success";
        return "badge-outline";
    }
    function riskColor(score) {
        if (score == null) return "var(--text-muted)";
        if (score >= 70) return "var(--danger)";
        if (score >= 45) return "var(--warning)";
        if (score >= 25) return "#eab308";
        return "var(--success)";
    }
    function trendBadge(t) {
        const x = (t || "").toLowerCase();
        if (x === "declining") return `<span class="badge badge-danger">▼ Declining</span>`;
        if (x === "improving") return `<span class="badge badge-success">▲ Improving</span>`;
        if (x === "stable") return `<span class="badge badge-outline">▬ Stable</span>`;
        return `<span class="badge badge-outline">—</span>`;
    }

    function renderKPIs() {
        const valid = partners.filter((p) => !p.error);
        const scored = valid.filter((p) => p.risk_score != null);
        const avg = scored.length ? Math.round(scored.reduce((s, p) => s + p.risk_score, 0) / scored.length) : 0;
        const highRisk = scored.filter((p) => p.risk_score >= 45).length;
        const sips = valid.filter((p) => p.sip_ticket).length;
        const declining = valid.filter((p) => (p.sentiment_trend || "").toLowerCase() === "declining").length;

        const cards = [
            { label: "Partners Tracked", value: valid.length, cls: "primary", icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M18 18.72a9.094 9.094 0 0 0 3.741-.479 3 3 0 0 0-4.682-2.72m.94 3.198.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0 1 12 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 0 1 6 18.719m12 0a5.971 5.971 0 0 0-.941-3.197m0 0A5.995 5.995 0 0 0 12 12.75a5.995 5.995 0 0 0-5.058 2.772m0 0a3 3 0 0 0-4.681 2.72 8.986 8.986 0 0 0 3.74.477m.94-3.197a5.971 5.971 0 0 0-.94 3.197M15 6.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm6 3a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm-13.5 0a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Z" />' },
            { label: "Avg Churn Risk", value: avg, cls: avg >= 45 ? "danger" : avg >= 25 ? "warning" : "success", icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />' },
            { label: "High Risk (≥45)", value: highRisk, cls: "danger", icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />' },
            { label: "Active SIPs / Declining", value: `${sips} / ${declining}`, cls: "warning", icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18 9 11.25l4.306 4.307a11.95 11.95 0 0 1 5.814-5.518l2.74-1.22m0 0-5.94-2.281m5.94 2.28-2.28 5.941" />' },
        ];
        $("kpi-grid").innerHTML = cards.map((c) => `
            <div class="kpi-card">
                <div class="kpi-icon-wrapper ${c.cls}">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" style="width:24px;height:24px;">${c.icon}</svg>
                </div>
                <div class="kpi-info"><span class="kpi-label">${c.label}</span><span class="kpi-value">${c.value}</span></div>
            </div>`).join("");
    }

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
            const score = p.risk_score;
            tr.innerHTML = `
                <td><div class="pt-name"><span class="pt-avatar">${esc((p.name || "?").charAt(0))}</span><div><div style="font-weight:600;">${esc(p.name)}</div><div style="font-size:0.74rem;color:var(--text-muted);">#${esc(p.client_id)} ${p.vip ? "· ⭐ VIP" : ""}</div></div></div></td>
                <td><span class="badge ${ragClass(p.rag)}">${esc(p.rag || "—")}</span></td>
                <td>${esc(p.cancel_risk || "—")}</td>
                <td>
                    <div class="risk-cell">
                        <div class="risk-bar-bg"><div class="risk-bar-fill" style="width:${score == null ? 0 : score}%;background:${riskColor(score)};"></div></div>
                        <span class="risk-num" style="color:${riskColor(score)};">${score == null ? "—" : score}</span>
                        <span class="badge ${bandClass(p.risk_band)}" style="font-size:0.62rem;">${esc(p.risk_band || "")}</span>
                    </div>
                </td>
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
                <div class="risk-card-head">
                    <span style="font-family:var(--font-heading);font-weight:700;">${esc(p.name)}</span>
                    <span class="risk-card-score" style="color:${riskColor(p.risk_score)};">${p.risk_score}</span>
                </div>
                <div style="display:flex;gap:6px;margin:8px 0;">
                    <span class="badge ${ragClass(p.rag)}">${esc(p.rag || "—")}</span>
                    <span class="badge ${bandClass(p.risk_band)}">${esc(p.risk_band || "")}</span>
                    ${trendBadge(p.sentiment_trend)}
                </div>
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

    async function init() {
        try {
            const res = await fetch("data/_index.json", { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const idx = await res.json();
            partners = idx.partners || [];
        } catch (e) {
            $("portfolio-body").innerHTML = `<tr><td colspan="9" class="no-results">Could not load portfolio index.<br><small>${esc(e.message)} — run <code>python -m extract.build_all</code></small></td></tr>`;
            return;
        }
        const gen = partners.find((p) => p._generated_at);
        $("generated-at").textContent = `${partners.filter((p) => !p.error).length} partners`;
        renderKPIs();
        setupControls();
        renderTable();
        renderRiskCards();
    }
    document.addEventListener("DOMContentLoaded", init);
})();
