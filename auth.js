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
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;" +
      "justify-content:center;background:#c9c6ee;font-family:'Plus Jakarta Sans',system-ui,sans-serif;";
    var inputCss = "width:100%;box-sizing:border-box;padding:11px 13px;border:1px solid #d7d5ec;" +
      "border-radius:11px;font-size:14px;";
    var linkBtnCss = "display:block;width:100%;margin-top:10px;padding:11px 16px;border:1px solid #6d5ef0;" +
      "border-radius:12px;background:#fff;color:#6d5ef0;font-weight:600;font-size:14px;cursor:pointer;";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "pp-auth-title");
    overlay.innerHTML =
      '<div style="background:#fff;border-radius:20px;padding:36px 40px;max-width:380px;width:90%;' +
      'box-shadow:0 24px 60px rgba(23,26,44,.18);">' +
      '<div aria-hidden="true" style="width:56px;height:56px;border-radius:16px;background:#6d5ef0;color:#fff;' +
      'font-weight:800;font-size:26px;display:flex;align-items:center;justify-content:center;' +
      'margin:0 auto 18px;">P</div>' +
      '<h1 id="pp-auth-title" style="font-size:20px;margin:0 0 6px;color:#171a2c;text-align:center;">Operational Intelligence</h1>' +
      '<p id="pp-auth-msg" role="status" aria-live="polite" style="font-size:14px;color:#4b5168;margin:0 0 20px;text-align:center;">' +
      'Sign in with your ITBD (@' + ALLOWED_DOMAIN + ') email.</p>' +
      '<label for="pp-email" style="display:block;font-size:13px;color:#4b5168;margin:0 0 4px;">Email</label>' +
      '<input id="pp-email" type="email" autocomplete="username" aria-label="ITBD email address" ' +
      'placeholder="you@' + ALLOWED_DOMAIN + '" style="' + inputCss + 'margin:0 0 10px;" />' +
      '<label for="pp-password" style="display:block;font-size:13px;color:#4b5168;margin:0 0 4px;">Password</label>' +
      '<input id="pp-password" type="password" autocomplete="current-password" aria-label="Password" ' +
      'placeholder="Password" style="' + inputCss + 'margin:0 0 16px;" />' +
      '<button id="pp-auth-btn" style="width:100%;padding:12px 16px;border:0;border-radius:12px;' +
      'background:#6d5ef0;color:#fff;font-weight:600;font-size:15px;cursor:pointer;">Sign in</button>' +
      '<div id="pp-verify-actions" style="display:none;">' +
      '<button id="pp-verified-reload" style="width:100%;padding:12px 16px;border:0;border-radius:12px;' +
      'background:#6d5ef0;color:#fff;font-weight:600;font-size:15px;cursor:pointer;">I\'ve verified - reload</button>' +
      '<button id="pp-resend" style="' + linkBtnCss + '">Resend link</button>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;margin-top:14px;font-size:13px;">' +
      '<a id="pp-toggle" href="#" style="color:#6d5ef0;text-decoration:none;">Create account</a>' +
      '<a id="pp-forgot" href="#" style="color:#6d5ef0;text-decoration:none;">Forgot password?</a>' +
      '</div></div>';
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
    if (el) { el.textContent = text; el.style.color = isError ? "#c0392b" : "#4b5168"; }
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

    lastSyncStamp: function () {
      return firebase.firestore().doc("meta/overview").get().then(function (s) {
        return s.exists ? s.data().generated_at : null;
      });
    },
  };
})();
