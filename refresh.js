/* Manual data-sync button (shared by index.html and partner.html).
 *
 * Drives the dev server's sync API: POST /api/refresh kicks off the pipeline
 * (Halo + TeamGPS + AI rebuild via the existing scripts), GET /api/refresh/status
 * is polled for per-step progress. While the cycle runs, a progress panel under
 * the button lists every step and the live activity streamed from the pipeline
 * ("Logically: syncing TeamGPS CSAT…", "running AI churn analysis…", …). When
 * the cycle finishes the page reloads so the regenerated index.html / data
 * JSONs are picked up.
 *
 * Degrades gracefully: if the page is served without the API (plain file host),
 * the button reports that sync is unavailable.
 */
(function () {
    "use strict";

    var btn = document.getElementById("sync-btn");
    if (!btn) return;
    var labelEl = btn.querySelector(".sync-label");
    var pollTimer = null;

    // "Last sync" timestamp next to the button — data freshness comes from
    // portfolio.generated_at in data/_index.json (rewritten by every build/
    // reindex), so it survives server restarts and counts CLI builds too.
    var stamp = document.createElement("span");
    stamp.className = "sync-stamp";
    btn.parentNode.insertBefore(stamp, btn);

    function showLastSync() {
        fetch("data/_index.json", { cache: "no-store" })
            .then(function (r) { return r.json(); })
            .then(function (ix) {
                var gen = ix && ix.portfolio && ix.portfolio.generated_at;
                var d = new Date(gen);
                if (!gen || isNaN(d)) return;
                stamp.textContent = "Last sync: " + d.toLocaleString("en-US", {
                    day: "2-digit", month: "short", hour: "numeric", minute: "2-digit"
                });
                stamp.title = "Data generated " + d.toLocaleString();
            })
            .catch(function () { /* static hosting without data/ — leave empty */ });
    }
    showLastSync();

    // Progress panel (created lazily, anchored under the button).
    var panel = document.createElement("div");
    panel.className = "sync-panel";
    panel.hidden = true;
    document.body.appendChild(panel);

    function positionPanel() {
        var r = btn.getBoundingClientRect();
        panel.style.top = (r.bottom + 8) + "px";
        panel.style.right = Math.max(8, window.innerWidth - r.right) + "px";
    }

    var STEP_ICONS = { ok: "✓", failed: "✕", running: "⟳", pending: "·" };

    function renderPanel(st) {
        panel.textContent = "";
        var title = document.createElement("div");
        title.className = "sync-panel-title";
        title.textContent = st.status === "done" ? "Sync finished" : "Syncing data…";
        panel.appendChild(title);
        st.steps.forEach(function (s) {
            var row = document.createElement("div");
            row.className = "sync-step " + s.status;
            var icon = document.createElement("span");
            icon.className = "sync-step-icon";
            icon.textContent = STEP_ICONS[s.status] || STEP_ICONS.pending;
            var body = document.createElement("span");
            body.className = "sync-step-body";
            var name = document.createElement("div");
            name.className = "sync-step-name";
            name.textContent = s.label;
            body.appendChild(name);
            if (s.detail && (s.status === "running" || s.status === "failed")) {
                var detail = document.createElement("div");
                detail.className = "sync-step-detail";
                detail.textContent = s.detail;
                body.appendChild(detail);
            }
            row.appendChild(icon);
            row.appendChild(body);
            panel.appendChild(row);
        });
        positionPanel();
        panel.hidden = false;
    }

    function hidePanel() { panel.hidden = true; }

    function setBusy(busy) {
        btn.classList.toggle("syncing", busy);
        btn.disabled = busy;
        if (!busy) hidePanel();
    }

    function setLabel(text, title) {
        labelEl.textContent = text;
        btn.title = title || "";
    }

    function summarize(st) {
        var done = st.steps.filter(function (s) { return s.status === "ok"; }).length;
        var failed = st.steps.filter(function (s) { return s.status === "failed"; });
        var running = st.steps.filter(function (s) { return s.status === "running"; })[0];
        return { done: done, failed: failed, running: running, total: st.steps.length };
    }

    function poll() {
        fetch("/api/refresh/status", { cache: "no-store" })
            .then(function (r) { return r.json(); })
            .then(function (st) {
                if (st.status === "running") {
                    var s = summarize(st);
                    var pos = Math.min(s.done + s.failed.length + 1, s.total);
                    setLabel("Syncing " + pos + "/" + s.total + "…",
                             st.activity || (s.running ? s.running.label : "Starting…"));
                    setBusy(true);
                    renderPanel(st);
                    pollTimer = setTimeout(poll, 2000);
                    return;
                }
                if (st.status === "done") {
                    var sum = summarize(st);
                    if (sum.done > 0) {
                        // Data changed — reload to pick up regenerated page/caches.
                        renderPanel(st);
                        setLabel(sum.failed.length
                            ? "Synced " + sum.done + "/" + sum.total + " — reloading…"
                            : "Synced — reloading…");
                        setTimeout(function () { location.reload(); }, 1200);
                        return;
                    }
                    setBusy(false);
                    setLabel("Sync failed — retry",
                             st.steps.map(function (s) {
                                 return s.label + ": " + (s.detail || s.status);
                             }).join("\n"));
                    return;
                }
                setBusy(false);
                setLabel("Sync Data");
            })
            .catch(function () {
                setBusy(false);
                setLabel("Sync unavailable", "The dashboard is not being served by server.py");
            });
    }

    btn.addEventListener("click", function () {
        if (btn.classList.contains("syncing")) return;
        if (!window.confirm(
            "Start a full data sync?\n\nThis pulls live HaloPSA + TeamGPS data and re-runs " +
            "the AI churn analysis. It can take several minutes and the page will reload " +
            "when it finishes.")) return;
        setBusy(true);
        setLabel("Starting…");
        fetch("/api/refresh", { method: "POST" })
            .then(function (r) {
                if (r.status === 409) { setLabel("Sync already running…"); }
                poll();
            })
            .catch(function () {
                setBusy(false);
                setLabel("Sync unavailable", "The dashboard is not being served by server.py");
            });
    });

    window.addEventListener("resize", function () {
        if (!panel.hidden) positionPanel();
    });

    // If a sync is already in flight (other tab / page navigation), resume display.
    fetch("/api/refresh/status", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (st) { if (st.status === "running") { setBusy(true); poll(); } })
        .catch(function () { /* static hosting — leave the idle button */ });
})();
