/* "Last sync" data-freshness label (shared by index.html and partner.html).
 *
 * The manual "Sync Data" button was REMOVED when the pipeline moved to a
 * scheduled Cloud Run Job (nightly 21:00 America/New_York) — there is no
 * in-app sync anymore; data refreshes itself. See docs/Cloud-Pipeline-SOP.md.
 *
 * This script now only renders data freshness into #sync-stamp, from
 * portfolio.generated_at:
 *   prod  → PP_AUTH.lastSyncStamp()  (Firestore meta/overview.generated_at)
 *   local → data/_index.json portfolio.generated_at
 */
(function () {
    "use strict";

    var stamp = document.getElementById("sync-stamp");
    if (!stamp) return;

    var getStamp = (window.PP_AUTH && window.PP_AUTH.lastSyncStamp)
        ? window.PP_AUTH.lastSyncStamp()
        : fetch("data/_index.json", { cache: "no-store" })
            .then(function (r) { return r.json(); })
            .then(function (ix) { return ix && ix.portfolio && ix.portfolio.generated_at; });

    getStamp
        .then(function (gen) {
            var d = new Date(gen);
            if (!gen || isNaN(d)) return;
            stamp.textContent = "Last sync: " + d.toLocaleString("en-US", {
                day: "2-digit", month: "short", hour: "numeric", minute: "2-digit"
            });
            stamp.title = "Data generated " + d.toLocaleString();
        })
        .catch(function () { /* static hosting without data/ — leave empty */ });
})();
