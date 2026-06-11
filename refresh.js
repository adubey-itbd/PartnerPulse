/* Manual data-sync button (shared by index.html and partner.html).
 *
 * Drives the dev server's sync API: POST /api/refresh kicks off the pipeline
 * (Halo + TeamGPS + AI rebuild via the existing scripts), GET /api/refresh/status
 * is polled for per-step progress. When the cycle finishes the page reloads so
 * the regenerated index.html / data JSONs are picked up.
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

    function setBusy(busy) {
        btn.classList.toggle("syncing", busy);
        btn.disabled = busy;
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
                             s.running ? s.running.label : "Starting…");
                    setBusy(true);
                    pollTimer = setTimeout(poll, 3000);
                    return;
                }
                if (st.status === "done") {
                    var sum = summarize(st);
                    if (sum.done > 0) {
                        // Data changed — reload to pick up regenerated page/caches.
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

    // If a sync is already in flight (other tab / page navigation), resume display.
    fetch("/api/refresh/status", { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (st) { if (st.status === "running") { setBusy(true); poll(); } })
        .catch(function () { /* static hosting — leave the idle button */ });
})();
