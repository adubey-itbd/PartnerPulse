/* Shared auth gate + Firestore data layer for the Firebase deployment.
 * Loaded by index.html and partner.html before their page scripts.
 *
 * PRODUCTION (Firebase Hosting): enforces email/password sign-in restricted to
 * @itbd.net (ITBD is on Microsoft 365, not Google Workspace, so there is no
 * Google identity to federate). The domain is checked client-side, but the real
 * boundary is email verification: the verify link lands in the @itbd.net mailbox,
 * and firestore.rules deny all reads until email_verified is true. It then reads
 * all dashboard data from Cloud Firestore via the Web SDK. Data is sharded:
 *   meta/overview                   portfolio rollups + coverage
 *   partners/{slug}                 summary doc (Exec Overview)
 *   partners/{slug}/detail/profile  client meta + AI + CSAT/NPS stats
 *   partners/{slug}/{transcripts|decks|calls|csat|nps|actions}/{id}
 *
 * LOCAL DEV (server.py on localhost): NO auth; data is read straight from the
 * data/*.json caches exactly as before, so the build/serve workflow is
 * unchanged. loadPartner just returns the local blob (same shape).
 *
 * Mode auto-detects: localhost, an unconfigured FIREBASE_CONFIG, or a missing
 * Firebase SDK all fall back to DEV. Pages use it as:
 *     await window.PP_AUTH.ready();
 *     const data = await window.PP_AUTH.loadOverview();        // index.html
 *     const data = await window.PP_AUTH.loadPartner(slug);     // partner.js
 */
(function () {
  "use strict";

  var cfg = window.FIREBASE_CONFIG || {};
  var host = location.hostname;
  var isLocal = host === "localhost" || host === "127.0.0.1" || host === "";
  var configured = cfg.apiKey && cfg.apiKey.indexOf("REPLACE") !== 0;
  var ALLOWED_DOMAIN = "itbd.net";
  var DEV = isLocal || !configured || typeof firebase === "undefined";

  // Subcollection name -> the key partner.js expects on the assembled object.
  var SECTIONS = {
    transcripts: "transcripts",
    decks: "decks",
    calls: "historical_calls",
    csat: "csat_comments",
    nps: "nps_comments",
    actions: "action_items",
  };

  function jget(file) {
    return fetch("data/" + file, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  if (DEV) {
    window.PP_AUTH = {
      mode: "dev",
      ready: function () { return Promise.resolve(null); },
      loadOverview: function () { return jget("_overview.json"); },
      loadCsatRecon: function () { return jget("_csat_recon.json"); },
      loadPartner: function (slug) { return jget(slug + ".json"); },
      lastSyncStamp: function () {
        return jget("_index.json").then(function (ix) {
          return ix && ix.portfolio && ix.portfolio.generated_at;
        });
      },
    };
    return;
  }

  firebase.initializeApp(cfg);
  var auth = firebase.auth();

  function validDomain(email) {
    return new RegExp("^[^@]+@" + ALLOWED_DOMAIN.replace(/\./g, "\\.") + "$", "i")
      .test((email || "").trim());
  }

  // --- sign-in overlay (created lazily once the body exists) ---
  // mode: "signin" | "signup" | "verify" (post-signup, pending verification).
  var overlay = null, mode = "signin", lastEmail = "";
  var MIN_PASSWORD = 12;
  function applyMode() {
    if (!overlay) return;
    var btn = overlay.querySelector("#pp-auth-btn");
    var toggle = overlay.querySelector("#pp-toggle");
    var forgot = overlay.querySelector("#pp-forgot");
    var pwField = overlay.querySelector("#pp-password");
    var verifyBox = overlay.querySelector("#pp-verify-actions");
    if (mode === "verify") {
      btn.style.display = "none";
      pwField.style.display = "none";
      forgot.style.display = "none";
      verifyBox.style.display = "block";
      toggle.textContent = "Back to sign in";
    } else {
      btn.style.display = "";
      pwField.style.display = "";
      forgot.style.display = "";
      verifyBox.style.display = "none";
      btn.textContent = (mode === "signup") ? "Create account" : "Sign in";
      pwField.setAttribute("autocomplete", (mode === "signup") ? "new-password" : "current-password");
      toggle.textContent = (mode === "signup") ? "Have an account? Sign in" : "Create account";
    }
  }
  function buildOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "pp-auth-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "pp-auth-title");
    // ITBD brand palette (sampled from the logo): cyan-blue #08A8D8, deeper blue
    // #0C8FC0, lime-green accent #B8D030, ink #0F2C3A. Styles are scoped to the
    // overlay id so they can't leak into the dashboard. Element IDs are unchanged
    // so the sign-in / sign-up / verify logic above keeps working.
    overlay.innerHTML =
      '<style>' +
      '#pp-auth-overlay{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;' +
      'justify-content:center;padding:24px;box-sizing:border-box;' +
      "font-family:'Plus Jakarta Sans',system-ui,-apple-system,'Segoe UI',sans-serif;" +
      'background:radial-gradient(1100px 620px at 12% 8%, rgba(184,208,48,.22), transparent 55%),' +
      'radial-gradient(900px 700px at 100% 100%, rgba(8,168,216,.55), transparent 52%),' +
      'linear-gradient(135deg,#0c93c4 0%,#0d6f9e 55%,#0a5980 100%);}' +
      '#pp-auth-overlay *{box-sizing:border-box;}' +
      '#pp-auth-overlay .pp-card{position:relative;background:#fff;border-radius:18px;' +
      'padding:42px 40px 28px;max-width:404px;width:100%;overflow:hidden;' +
      'box-shadow:0 30px 70px rgba(7,40,60,.32),0 4px 14px rgba(7,40,60,.14);}' +
      '#pp-auth-overlay .pp-card::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;' +
      'background:linear-gradient(90deg,#08a8d8 0%,#3bbfe0 48%,#b8d030 100%);}' +
      '#pp-auth-overlay .pp-logo{display:block;height:48px;width:auto;margin:4px auto 22px;}' +
      '#pp-auth-overlay .pp-title{font-size:20px;font-weight:700;letter-spacing:-.01em;' +
      'margin:0 0 6px;color:#0f2c3a;text-align:center;}' +
      '#pp-auth-overlay #pp-auth-msg{font-size:14px;line-height:1.45;color:#5a6b75;' +
      'margin:0 0 24px;text-align:center;}' +
      '#pp-auth-overlay .pp-label{display:block;font-size:13px;font-weight:600;color:#3c4a52;margin:0 0 6px;}' +
      '#pp-auth-overlay .pp-input{width:100%;padding:12px 14px;border:1.5px solid #dfe6ea;border-radius:10px;' +
      'font-size:14px;color:#0f2c3a;background:#fbfcfd;outline:none;' +
      'transition:border-color .15s,box-shadow .15s,background .15s;}' +
      '#pp-auth-overlay .pp-input::placeholder{color:#9aa7ae;}' +
      '#pp-auth-overlay .pp-input:focus{border-color:#08a8d8;background:#fff;box-shadow:0 0 0 3px rgba(8,168,216,.18);}' +
      '#pp-auth-overlay .pp-btn{width:100%;padding:13px 16px;border:0;border-radius:10px;color:#fff;' +
      'font-weight:700;font-size:15px;letter-spacing:.01em;cursor:pointer;' +
      'background:linear-gradient(135deg,#08a8d8 0%,#0c8fc0 100%);box-shadow:0 6px 16px rgba(8,168,216,.35);' +
      'transition:transform .12s,box-shadow .12s,filter .12s;}' +
      '#pp-auth-overlay .pp-btn:hover{filter:brightness(1.05);transform:translateY(-1px);box-shadow:0 9px 22px rgba(8,168,216,.45);}' +
      '#pp-auth-overlay .pp-btn:active{transform:translateY(0);box-shadow:0 4px 12px rgba(8,168,216,.35);}' +
      '#pp-auth-overlay .pp-btn-secondary{display:block;width:100%;margin-top:10px;padding:12px 16px;' +
      'border:1.5px solid #08a8d8;border-radius:10px;background:#fff;color:#0a90c0;font-weight:600;' +
      'font-size:14px;cursor:pointer;transition:background .12s;}' +
      '#pp-auth-overlay .pp-btn-secondary:hover{background:#f0fafd;}' +
      '#pp-auth-overlay .pp-links{display:flex;justify-content:space-between;margin-top:18px;font-size:13px;}' +
      '#pp-auth-overlay .pp-link{color:#0a90c0;font-weight:600;text-decoration:none;}' +
      '#pp-auth-overlay .pp-link:hover{color:#08a8d8;text-decoration:underline;}' +
      '#pp-auth-overlay .pp-foot{margin-top:22px;padding-top:15px;border-top:1px solid #eef2f4;' +
      'text-align:center;font-size:11.5px;letter-spacing:.02em;color:#93a1a8;}' +
      '</style>' +
      '<div class="pp-card">' +
      '<img class="pp-logo" src="assets/itbd-logo.webp" alt="IT By Design" width="138" height="48" />' +
      '<h1 id="pp-auth-title" class="pp-title">Operational Intelligence</h1>' +
      '<p id="pp-auth-msg" role="status" aria-live="polite">' +
      'Sign in with your ITBD (@' + ALLOWED_DOMAIN + ') email.</p>' +
      '<label for="pp-email" class="pp-label">Email</label>' +
      '<input id="pp-email" class="pp-input" type="email" autocomplete="username" aria-label="ITBD email address" ' +
      'placeholder="you@' + ALLOWED_DOMAIN + '" style="margin:0 0 14px;" />' +
      '<label for="pp-password" class="pp-label">Password</label>' +
      '<input id="pp-password" class="pp-input" type="password" autocomplete="current-password" aria-label="Password" ' +
      'placeholder="Password" style="margin:0 0 18px;" />' +
      '<button id="pp-auth-btn" class="pp-btn">Sign in</button>' +
      '<div id="pp-verify-actions" style="display:none;">' +
      '<button id="pp-verified-reload" class="pp-btn">I\'ve verified - reload</button>' +
      '<button id="pp-resend" class="pp-btn-secondary">Resend link</button>' +
      '</div>' +
      '<div class="pp-links">' +
      '<a id="pp-toggle" class="pp-link" href="#">Create account</a>' +
      '<a id="pp-forgot" class="pp-link" href="#">Forgot password?</a>' +
      '</div>' +
      '<div class="pp-foot">Authorized @' + ALLOWED_DOMAIN + ' users only &middot; Secured by Firebase</div>' +
      '</div>';
    document.body.appendChild(overlay);
    overlay.querySelector("#pp-auth-btn").addEventListener("click", submit);
    overlay.querySelector("#pp-toggle").addEventListener("click", function (e) {
      e.preventDefault();
      mode = (mode === "signin") ? "signup" : "signin";
      applyMode();
      setMsg(mode === "signup"
        ? "Create an account with your @" + ALLOWED_DOMAIN + " email — we'll send a verification link."
        : "Sign in with your ITBD (@" + ALLOWED_DOMAIN + ") email.");
    });
    overlay.querySelector("#pp-forgot").addEventListener("click", function (e) {
      e.preventDefault(); resetPassword();
    });
    overlay.querySelector("#pp-resend").addEventListener("click", function (e) {
      e.preventDefault(); resendVerification();
    });
    overlay.querySelector("#pp-verified-reload").addEventListener("click", function (e) {
      e.preventDefault(); location.reload();
    });
    overlay.querySelector("#pp-password").addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });
    overlay.querySelector("#pp-email").addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });
    applyMode();
    return overlay;
  }
  function withBody(fn) {
    if (document.body) fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }
  function setMsg(text, isError) {
    var el = document.getElementById("pp-auth-msg");
    if (el) { el.textContent = text; el.style.color = isError ? "#c0392b" : "#5a6b75"; }
  }
  function showOverlay(message, isError) {
    withBody(function () {
      buildOverlay().style.display = "flex";
      if (message) setMsg(message, isError);
      var email = document.getElementById("pp-email");
      if (email && mode !== "verify") { try { email.focus(); } catch (_) {} }
    });
  }
  function hideOverlay() { if (overlay) overlay.style.display = "none"; }

  function creds() {
    return {
      email: ((document.getElementById("pp-email") || {}).value || "").trim(),
      password: (document.getElementById("pp-password") || {}).value || "",
    };
  }

  function friendly(e) {
    var code = (e && e.code) || "";
    if (code === "auth/wrong-password" || code === "auth/invalid-credential") return "Incorrect email or password.";
    if (code === "auth/user-not-found") return "Incorrect email or password.";
    if (code === "auth/email-already-in-use") return "That email already has an account — sign in instead.";
    if (code === "auth/too-many-requests") return "Too many attempts. Try again in a few minutes.";
    if (code === "auth/weak-password") return "Password must be at least " + MIN_PASSWORD + " characters.";
    return (e && e.message) || "Something went wrong.";
  }

  // After a successful sign-up, switch to the verify view instead of dead-ending
  // in signup mode: the user must click the emailed link, then sign in.
  function enterVerifyMode(email) {
    lastEmail = email;
    mode = "verify";
    applyMode();
    setMsg("We emailed a verification link to " + email +
      ". Open it, then come back and sign in.");
  }

  // The verified / unverified / wrong-domain gate lives in onAuthStateChanged.
  function submit() {
    if (mode === "verify") return;
    var c = creds();
    if (!validDomain(c.email)) { setMsg("Use your @" + ALLOWED_DOMAIN + " email address.", true); return; }
    if (c.password.length < MIN_PASSWORD) {
      setMsg("Password must be at least " + MIN_PASSWORD + " characters.", true); return;
    }
    setMsg(mode === "signup" ? "Creating account..." : "Signing in...");
    if (mode === "signup") {
      auth.createUserWithEmailAndPassword(c.email, c.password).then(function (res) {
        var user = res && res.user;
        if (user) { user.sendEmailVerification().catch(function () {}); }
        // Don't keep an unverified session around; show the verify view.
        auth.signOut().catch(function () {});
        enterVerifyMode(c.email);
      }).catch(function (e) { setMsg(friendly(e), true); });
    } else {
      auth.signInWithEmailAndPassword(c.email, c.password)
        .catch(function (e) { setMsg(friendly(e), true); });
    }
  }

  function resendVerification() {
    // Re-authenticate transiently to obtain a user we can (re)send from.
    var c = creds();
    var email = lastEmail || c.email;
    var pw = c.password;
    if (!pw) {
      setMsg("Enter your password above, then choose Resend link.", true);
      return;
    }
    setMsg("Resending verification link...");
    auth.signInWithEmailAndPassword(email, pw).then(function (res) {
      var user = res && res.user;
      var done = user ? user.sendEmailVerification() : Promise.resolve();
      return done.then(function () {
        auth.signOut().catch(function () {});
        setMsg("Verification link re-sent to " + email + ". Open it, then sign in.");
      });
    }).catch(function (e) { setMsg(friendly(e), true); });
  }

  function resetPassword() {
    var c = creds();
    if (!validDomain(c.email)) { setMsg("Enter your @" + ALLOWED_DOMAIN + " email first.", true); return; }
    // Neutral response either way — never reveal whether the account exists, and
    // never tell a typo'd address to "create an account".
    var neutral = "If an account exists for " + c.email +
      ", a password-reset link has been sent. Check your inbox, then sign in.";
    function backToSignin() {
      if (mode !== "signin") { mode = "signin"; applyMode(); }
    }
    auth.sendPasswordResetEmail(c.email).then(function () {
      backToSignin(); setMsg(neutral);
    }).catch(function (e) {
      var code = (e && e.code) || "";
      // user-not-found / invalid-email leak existence — collapse to the neutral
      // message; only surface genuinely actionable errors (e.g. rate limiting).
      if (code === "auth/user-not-found" || code === "auth/invalid-email") {
        backToSignin(); setMsg(neutral);
      } else {
        setMsg(friendly(e), true);
      }
    });
  }

  var readyPromise = new Promise(function (resolve) {
    auth.onAuthStateChanged(function (user) {
      if (!user) { showOverlay(); return; }
      var email = (user.email || "").toLowerCase();
      if (!validDomain(email)) {
        auth.signOut();
        showOverlay("Access is restricted to @" + ALLOWED_DOMAIN + " addresses.", true);
      } else if (!user.emailVerified) {
        // Prove mailbox ownership before granting access (firestore.rules also
        // require email_verified). Best-effort (re)send, then drop the session
        // and show the verify view (Resend / I've-verified-reload actions).
        user.sendEmailVerification().catch(function () {});
        auth.signOut();
        withBody(function () {
          buildOverlay().style.display = "flex";
          enterVerifyMode(email);
        });
      } else {
        hideOverlay();
        resolve(user);
      }
    });
  });

  function docs(snap) { return snap.docs.map(function (d) { return d.data(); }); }

  window.PP_AUTH = {
    mode: "prod",
    ready: function () { return readyPromise; },

    // Exec Overview: portfolio meta + every partner summary doc, reassembled
    // into the shape index.html expects (the old _overview.json feed).
    loadOverview: function () {
      var db = firebase.firestore();
      return Promise.all([
        db.doc("meta/overview").get(),
        db.collection("partners").get(),
      ]).then(function (res) {
        var meta = res[0].exists ? res[0].data() : {};
        return Object.assign({}, meta, { partners: docs(res[1]) });
      });
    },

    // Partner 360: the profile singleton + every detail subcollection,
    // reassembled into the shape partner.js expects (the old {slug}.json blob).
    // Each subcollection is ordered by the `_i` field the pipeline writes.
    loadPartner: function (slug) {
      var db = firebase.firestore();
      var base = db.collection("partners").doc(slug);
      var names = Object.keys(SECTIONS);
      var reads = [base.get(), base.collection("detail").doc("profile").get()]
        .concat(names.map(function (n) { return base.collection(n).orderBy("_i").get(); }));
      return Promise.all(reads).then(function (r) {
        if (!r[0].exists && !r[1].exists) throw new Error("partner not found: " + slug);
        var data = Object.assign({}, r[1].exists ? r[1].data() : {});
        names.forEach(function (n, i) { data[SECTIONS[n]] = docs(r[i + 2]); });
        return data;
      });
    },

    // CSAT Reconciliation view: the whole feed lives in a single meta doc.
    loadCsatRecon: function () {
      return firebase.firestore().doc("meta/csatRecon").get().then(function (s) {
        return s.exists ? s.data() : null;
      });
    },

    lastSyncStamp: function () {
      return firebase.firestore().doc("meta/overview").get().then(function (s) {
        return s.exists ? s.data().generated_at : null;
      });
    },
  };
})();
