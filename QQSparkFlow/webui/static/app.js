(() => {
  "use strict";

  const initIcons = () => {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  };

  const initTheme = () => {
    const root = document.documentElement;
    const saved = localStorage.getItem("qq-sparkflow-theme");
    if (saved) root.setAttribute("data-theme", saved);
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
        root.setAttribute("data-theme", next);
        localStorage.setItem("qq-sparkflow-theme", next);
      });
    });
  };

  const initNav = () => {
    const sidebar = document.getElementById("app-sidebar");
    const backdrop = document.querySelector(".sidebar-backdrop");
    const open = () => document.body.classList.add("nav-open");
    const close = () => document.body.classList.remove("nav-open");
    document.querySelectorAll("[data-nav-toggle]").forEach((btn) => btn.addEventListener("click", open));
    document.querySelectorAll("[data-nav-close]").forEach((btn) => btn.addEventListener("click", close));
    if (backdrop) backdrop.addEventListener("click", close);
  };

  const initConfirm = () => {
    const dialog = document.getElementById("confirm-dialog");
    if (!dialog) return;
    const messageEl = document.getElementById("confirm-message");
    const cancelBtn = dialog.querySelector("[data-confirm-cancel]");
    const acceptBtn = dialog.querySelector("[data-confirm-accept]");
    let pendingForm = null;

    document.addEventListener("submit", (event) => {
      const form = event.target;
      const message = form.getAttribute("data-confirm");
      if (!message) return;
      event.preventDefault();
      pendingForm = form;
      if (messageEl) messageEl.textContent = message;
      dialog.showModal();
    });

    const cancel = () => {
      pendingForm = null;
      dialog.close();
    };
    const accept = () => {
      if (pendingForm) {
        const clone = pendingForm.cloneNode(true);
        clone.removeAttribute("data-confirm");
        clone.style.display = "none";
        document.body.appendChild(clone);
        clone.submit();
      }
      pendingForm = null;
      dialog.close();
    };
    if (cancelBtn) cancelBtn.addEventListener("click", cancel);
    if (acceptBtn) acceptBtn.addEventListener("click", accept);
  };

  const initOverviewPoll = () => {
    const root = document.querySelector("[data-overview-root]");
    if (!root) return;
    const valueEls = document.querySelectorAll("[data-overview-value]");

    const apply = (payload) => {
      const summary = payload.summary || {};
      const schedule = payload.schedule || {};
      const total = summary.total_targets || 0;
      const confirmed = summary.today_confirmed_targets || 0;
      const values = {
        progressPercent: total ? Math.floor((confirmed / total) * 100) + "%" : "100%",
        progress: `${confirmed}/${total}`,
        replied: summary.today_replied_targets || 0,
        attention: summary.today_attention_targets || 0,
        confirmed,
        failed: summary.today_failed_targets || 0,
        pending: summary.today_pending_targets || 0,
        nextTriggerAt: schedule.nextTriggerAt || "-",
        scheduleLabel: schedule.label || "-",
      };
      valueEls.forEach((el) => {
        const key = el.getAttribute("data-overview-value");
        if (key && Object.prototype.hasOwnProperty.call(values, key)) {
          el.textContent = values[key];
        }
      });
    };

    const refresh = async () => {
      try {
        const res = await fetch("/api/ops/overview", { credentials: "same-origin", headers: { Accept: "application/json" } });
        if (!res.ok) return;
        apply(await res.json());
      } catch (err) {
        /* keep last known values */
      }
    };

    setInterval(refresh, 8000);
  };

  document.addEventListener("DOMContentLoaded", () => {
    initIcons();
    initTheme();
    initNav();
    initConfirm();
    initOverviewPoll();
  });
})();
