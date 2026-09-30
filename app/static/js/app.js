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
  // --paper token so app.css stays the one place a colour is defined. The
  // token is a light-dark() pair, which only resolves when used as a real
  // colour, so it is read back through a throwaway element.
  function syncThemeColor() {
    var probe = document.createElement("span");
    probe.style.color = "var(--paper)";
    document.body.appendChild(probe);
    var paper = getComputedStyle(probe).color;
    probe.remove();
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

  /* --- Submit once ------------------------------------------------------------
     A <form data-submit-once> posts once per page load: the button disables
     and shows its data-busy-label with a spinner, and a second Enter or click
     is dropped. A double-click would otherwise send two requests, and the
     second arrives after the first rotated the CSRF token (a 403) or tries
     to create the same thing twice (the server rejects that anyway; this
     just keeps the person from seeing it).

     Listens on document, after initConfirmDialog, so a form still waiting on
     "Are you sure?" (defaultPrevented) is not marked as sent. */

  function initSubmitState() {
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-submit-once")) return;
      if (event.defaultPrevented) return;
      if (form.getAttribute("data-submitting") === "true") {
        event.preventDefault();
        return;
      }
      form.setAttribute("data-submitting", "true");

      var btn = form.querySelector('button[type="submit"]');
      if (!btn) return;
      btn.setAttribute("data-idle-label", btn.textContent);
      btn.disabled = true;
      btn.classList.add("is-busy");
      var spinner = document.createElement("span");
      spinner.className = "btn-spinner";
      spinner.setAttribute("aria-hidden", "true");
      var label = document.createElement("span");
      label.textContent = btn.getAttribute("data-busy-label") || "Sending…";
      btn.replaceChildren(spinner, label);
    });

    // The back/forward cache can bring a page back mid-submit; unlock it so
    // the button isn't stuck on a spinner that will never finish.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      document.querySelectorAll('form[data-submitting="true"]').forEach(function (form) {
        form.removeAttribute("data-submitting");
        var btn = form.querySelector('button[type="submit"]');
        if (!btn) return;
        btn.disabled = false;
        btn.classList.remove("is-busy");
        btn.textContent = btn.getAttribute("data-idle-label") || btn.textContent;
      });
    });
  }

  /* --- Inline email check ------------------------------------------------------
     Catches a malformed address on blur, before the round trip. Uses the
     same .field__error markup and wording as the server's message, so the
     two look identical, and clears on the next keystroke that fixes it
     (including a server-rendered error). The server still checks: the
     browser accepts "a@b", which the server does not. */

  var EMAIL_MESSAGE = "Enter an email address like name@example.com.";

  function initInlineValidation() {
    document.querySelectorAll(".field input[type=email]").forEach(function (input) {
      var field = input.closest(".field");
      var errorId = input.id + "-error";

      function describedBy() {
        return (input.getAttribute("aria-describedby") || "").split(" ").filter(Boolean);
      }

      function showError() {
        var error = document.getElementById(errorId);
        if (!error) {
          error = document.createElement("p");
          error.className = "field__error";
          error.id = errorId;
          field.appendChild(error);
          input.setAttribute("aria-describedby", describedBy().concat(errorId).join(" "));
        }
        error.textContent = EMAIL_MESSAGE;
        input.setAttribute("aria-invalid", "true");
        field.classList.add("field--invalid");
      }

      function clearError() {
        var error = document.getElementById(errorId);
        if (error) error.remove();
        var rest = describedBy().filter(function (id) {
          return id !== errorId;
        });
        if (rest.length) input.setAttribute("aria-describedby", rest.join(" "));
        else input.removeAttribute("aria-describedby");
        input.removeAttribute("aria-invalid");
        field.classList.remove("field--invalid");
      }

      input.addEventListener("blur", function () {
        if (input.value && !input.checkValidity()) showError();
      });

      input.addEventListener("input", function () {
        if (!input.value || input.checkValidity()) clearError();
      });
    });
  }

  /* --- Menus -------------------------------------------------------------------
     <details class="menu"> already opens and closes without JS. This adds
     what people expect of a menu: a click anywhere else closes it, and so
     does Escape (returning focus to its trigger). */

  function initMenus() {
    document.addEventListener("click", function (event) {
      document.querySelectorAll("details.menu[open]").forEach(function (menu) {
        if (!menu.contains(event.target)) menu.open = false;
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      document.querySelectorAll("details.menu[open]").forEach(function (menu) {
        menu.open = false;
        menu.querySelector("summary").focus();
      });
    });
  }

  /* --- Live filter ----------------------------------------------------------------
     A GET form marked [data-live-filter] (the booking page's person and day)
     re-fetches its own URL when a control changes, and swaps the element named
     by data-live-target with the same element from the answer:

       - sends X-Requested-With, so the server returns only the fragment
         (_partials/slot_grid.html) instead of the whole page;
       - debounced: typing a date fires "change" on every segment;
       - AbortController: a newer change cancels the request still in flight,
         so an old day's grid can never land on top of a newer one;
       - anything unexpected (network error, a 404/500 page without the
         target) falls back to a normal submit, which is the no-JS path.

     A 409 or 422 still carries the fragment (with its notice), so it is
     swapped in like any other answer. */

  function initLiveFilter() {
    var form = document.querySelector("form[data-live-filter]");
    if (!form || !window.fetch || !window.AbortController) return;
    var selector = form.getAttribute("data-live-target");
    var target = selector && document.querySelector(selector);
    if (!target) return;

    var controller = null;
    var timer = null;

    function apply() {
      if (controller) controller.abort();
      controller = new AbortController();
      var params = new URLSearchParams(new FormData(form));
      var url = form.getAttribute("action") + "?" + params.toString();
      target.setAttribute("aria-busy", "true");

      fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      })
        .then(function (response) {
          return response.text();
        })
        .then(function (html) {
          var fragment = new DOMParser().parseFromString(html, "text/html");
          // The fragment arrives without its wrapper, so it is the <body>;
          // a full error page would carry the site header instead.
          if (fragment.querySelector(".site-header")) throw new Error("not a fragment");
          target.innerHTML = fragment.body.innerHTML;
          target.removeAttribute("aria-busy");
          // Keep the address bar shareable and the Back button honest. Safari
          // throws after ~100 calls in 30s; a stale URL beats a reload.
          try {
            history.replaceState(null, "", url);
          } catch (e) {}
        })
        .catch(function (error) {
          if (error.name === "AbortError") return;
          form.submit();
        });
    }

    function applySoon() {
      clearTimeout(timer);
      timer = setTimeout(apply, 250);
    }

    form.addEventListener("change", applySoon);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      clearTimeout(timer);
      apply();
    });
  }

  /* --- Slot summary -----------------------------------------------------------------
     Echoes the chosen tile ("10:15 with Jasur · Wed 7 Oct 2026") into the
     sticky Continue bar. Listens on the document so it keeps working after
     the live filter replaces the grid. */

  function initSlotSummary() {
    document.addEventListener("change", function (event) {
      var input = event.target;
      if (!(input instanceof HTMLInputElement) || input.name !== "slot") return;
      var summary = document.querySelector("[data-slot-summary]");
      if (!summary || !input.checked) return;
      summary.textContent = input.getAttribute("data-summary") || "";
      summary.classList.add("is-chosen");
    });
  }

  /* --- Shop clock -----------------------------------------------------------------
     The home page's ticket shows the time it is now at the shop
     ([data-shop-clock data-timezone="Asia/Tashkent"]), so someone booking from
     another timezone sees which clock the free times follow. Formatting only:
     the browser's Intl does the conversion, and nothing is decided from it.
     The server can't render it (the page would show a stale time), so it
     stays hidden until the first tick; an unknown timezone keeps it hidden. */

  function initShopClock() {
    var clock = document.querySelector("[data-shop-clock]");
    if (!clock || !window.Intl) return;
    var wrap = clock.closest("[data-shop-clock-wrap]") || clock;
    var format;
    try {
      format = new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
        timeZone: clock.getAttribute("data-timezone"),
      });
    } catch (e) {
      return;
    }

    function tick() {
      clock.textContent = format.format(new Date());
    }

    tick();
    wrap.hidden = false;
    setInterval(tick, 15000);
  }

  function init() {
    initThemeToggle();
    initNavToggle();
    initConfirmDialog();
    initSubmitState(); // after initConfirmDialog: see its comment
    initInlineValidation();
    initMenus();
    initLiveFilter();
    initSlotSummary();
    initShopClock();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
