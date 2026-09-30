// Navbat: site-wide behaviour, loaded on every page from base.html.
//
// Everything here is progressive enhancement. With JS off the site still
// works: the theme follows the OS, every nav link is visible, and a form
// marked data-confirm simply submits. Nothing in this file owns a business
// rule; the server checks everything again.
(function () {
  "use strict";

  /* --- Theme ----------------------------------------------------------------
     The saved choice is applied before first paint by the inline script in
     base.html; this only handles the toggle button. With no saved choice,
     html has no data-theme and CSS follows prefers-color-scheme. */

  var STORAGE_KEY = "navbat-theme";

  function currentTheme() {
    var explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  // The <meta name="theme-color"> tags follow the OS scheme; once the reader
  // overrides it, both are rewritten with the page colour, read from the
  // --paper token so app.css stays the one place a colour is defined.
  function syncThemeColor() {
    var paper = getComputedStyle(document.documentElement).getPropertyValue("--paper").trim();
    if (!paper) return;
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (tag) {
      tag.setAttribute("content", paper);
    });
  }

  function initThemeToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;

    function syncLabel() {
      btn.setAttribute(
        "aria-label",
        currentTheme() === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
      syncThemeColor();
    }

    syncLabel();
    // A back/forward-cache restore re-applies the saved theme (inline script)
    // without re-running this file, so the label is re-synced here too.
    window.addEventListener("pageshow", syncLabel);

    btn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (e) {
        // Private mode: the choice just won't survive a reload.
      }
      syncLabel();
    });

    // With no saved choice, keep following the OS if it changes.
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        if (!document.documentElement.getAttribute("data-theme")) syncLabel();
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }
  }

  /* --- Mobile nav -----------------------------------------------------------
     Only shows and hides .nav-links; the collapse itself is CSS, gated on
     html.has-js. Closes on Escape, and on pageshow so a bfcache restore never
     brings the page back with the menu open. */

  function initNavToggle() {
    var btn = document.getElementById("nav-toggle");
    var panel = document.getElementById("nav-links");
    if (!btn || !panel) return;

    function setOpen(open) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      panel.classList.toggle("is-open", open);
    }

    btn.addEventListener("click", function () {
      setOpen(btn.getAttribute("aria-expanded") !== "true");
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && btn.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        btn.focus();
      }
    });

    window.addEventListener("pageshow", function () {
      setOpen(false);
    });
  }

  /* --- Confirm dialog --------------------------------------------------------
     Any <form data-confirm="Cancel this booking?"> asks first. Optional:
       data-confirm-body  one sentence under the question
       data-confirm-yes   the confirming button's label ("Yes, cancel it")
       data-confirm-no    the going-back button's label ("No, keep it")
     Text is set with textContent, never as HTML.

     "Yes" submits with form.submit(), which does not fire the submit event
     again, so it cannot loop. No, Escape or a click on the backdrop closes
     the dialog. Without <dialog> support the form just submits, and the
     server's own checks still apply. */

  function initConfirmDialog() {
    var dialog = document.getElementById("confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;

    var title = dialog.querySelector("[data-confirm-title]");
    var body = dialog.querySelector("[data-confirm-body]");
    var yes = dialog.querySelector("[data-confirm-yes]");
    var no = dialog.querySelector("[data-confirm-no]");
    var pending = null;

    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm")) return;
      event.preventDefault();
      pending = form;
      title.textContent = form.getAttribute("data-confirm") || "Are you sure?";
      var text = form.getAttribute("data-confirm-body");
      body.textContent = text || "";
      body.hidden = !text;
      yes.textContent = form.getAttribute("data-confirm-yes") || "Yes, continue";
      no.textContent = form.getAttribute("data-confirm-no") || "No, go back";
      yes.disabled = false;
      dialog.showModal();
      no.focus();
    });

    no.addEventListener("click", function () {
      dialog.close();
    });

    yes.addEventListener("click", function () {
      if (!pending) return;
      yes.disabled = true; // a second click must not post twice
      pending.submit();
    });

    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });

    dialog.addEventListener("close", function () {
      pending = null;
    });
  }

  function init() {
    initThemeToggle();
    initNavToggle();
    initConfirmDialog();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
