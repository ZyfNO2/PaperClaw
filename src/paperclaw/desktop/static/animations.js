/* PaperClaw Motion Controller
   Handles boot sequence, ripple effects, number flashes, message entry,
   and other JS-driven micro-interactions. Kept separate from app.js logic.
*/
(() => {
  "use strict";

  const BOOT_DURATION_MS = 1400;
  let booted = false;

  // ======== BOOT SEQUENCE ========
  function runBootSequence() {
    if (booted) return;
    const overlay = document.getElementById("boot-overlay");
    if (!overlay) { booted = true; document.body.classList.add("booted"); return; }

    // Animate boot lines (CSS handles staggered opacity, JS just dismisses)
    setTimeout(() => {
      overlay.classList.add("hidden");
      document.body.classList.add("booted");
      booted = true;
      // Remove overlay from DOM after fade
      setTimeout(() => {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      }, 500);
    }, BOOT_DURATION_MS);
  }

  // ======== RIPPLE EFFECT ========
  function createRipple(event) {
    const el = event.currentTarget;
    if (!el || el.disabled) return;
    // Skip for neo-brutalist / terminal-dark (hard edges)
    const theme = document.documentElement.dataset.theme;
    if (theme === "neo-brutalist") return;

    const rect = el.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 2;
    const x = event.clientX - rect.left - size / 2;
    const y = event.clientY - rect.top - size / 2;

    const ripple = document.createElement("span");
    ripple.className = "ripple";
    ripple.style.width = size + "px";
    ripple.style.height = size + "px";
    ripple.style.left = x + "px";
    ripple.style.top = y + "px";
    el.appendChild(ripple);
    setTimeout(() => ripple.remove(), 550);
  }

  function injectRippleKeyframe() {
    // Keyframe is now in animations.css, no need to inject
  }

  // ======== NUMBER CHANGE FLASH ========
  function flashNumber(el) {
    if (!el) return;
    el.classList.remove("changing");
    // Force reflow
    void el.offsetWidth;
    el.classList.add("changing");
    el.addEventListener("animationend", () => el.classList.remove("changing"), { once: true });
  }

  // ======== MESSAGE ENTRY WITH TYPING EFFECT (for new messages) ========
  function animateMessageEntry(msgEl) {
    if (!msgEl) return;
    msgEl.style.opacity = "0";
    msgEl.style.transform = "translateY(8px)";
    requestAnimationFrame(() => {
      msgEl.style.transition = "opacity 200ms cubic-bezier(0.16,1,0.3,1), transform 200ms cubic-bezier(0.16,1,0.3,1)";
      msgEl.style.opacity = "1";
      msgEl.style.transform = "translateY(0)";
      setTimeout(() => {
        msgEl.style.transition = "";
        msgEl.style.opacity = "";
        msgEl.style.transform = "";
      }, 250);
    });
  }

  // ======== MISSION LOG AUTO-SCROLL SMOOTH ========
  function smoothScrollToBottom(container) {
    if (!container) return;
    const isNearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 40;
    if (isNearBottom) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  }

  // ======== SIDEBAR TOGGLE ANIMATION ENHANCEMENT ========
  function setupSidebarToggle() {
    const toggle = document.getElementById("sidebar-toggle");
    const app = document.getElementById("app");
    if (!toggle || !app) return;
    toggle.addEventListener("click", () => {
      app.classList.toggle("sidebar-collapsed");
      toggle.textContent = app.classList.contains("sidebar-collapsed") ? "→" : "←";
    });
  }

  // ======== SETTINGS / PRODUCT PANEL BACKDROP ========
  function setupPanelBackdrop() {
    // Add subtle backdrop click already handled in app.js, add enter animation
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((m) => {
        if (m.type === "attributes" && m.attributeName === "hidden") {
          const panel = m.target;
          if (!panel.hasAttribute("hidden")) {
            panel.style.display = "grid";
            requestAnimationFrame(() => {
              panel.style.opacity = "1";
            });
          } else {
            panel.style.opacity = "0";
          }
        }
      });
    });
    ["settings-panel", "product-panel"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el, { attributes: true, attributeFilter: ["hidden"] });
    });
  }

  // ======== TOAST SLIDE ========
  function setupToastAnimation() {
    const toast = document.getElementById("toast");
    if (!toast) return;
    const observer = new MutationObserver(() => {
      if (!toast.hasAttribute("hidden")) {
        requestAnimationFrame(() => {
          toast.style.transform = "translateY(0)";
          toast.style.opacity = "1";
        });
      } else {
        toast.style.transform = "";
        toast.style.opacity = "";
      }
    });
    observer.observe(toast, { attributes: true, attributeFilter: ["hidden"] });
  }

  // ======== KEYBOARD SHORTCUT VISUAL FEEDBACK ========
  function setupKeyboardFeedback() {
    document.addEventListener("keydown", (e) => {
      // Ctrl+K search focus flash
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        const search = document.getElementById("global-search");
        if (search) {
          search.focus();
          const label = search.closest(".search");
          if (label) {
            label.style.transition = "box-shadow 0.1s, border-color 0.1s";
            label.style.boxShadow = "var(--pc-shadow-focus)";
            setTimeout(() => { label.style.boxShadow = ""; label.style.transition = ""; }, 300);
          }
        }
      }
      // Enter on composer
      if (e.key === "Enter" && !e.shiftKey && document.activeElement?.id === "task") {
        const sendBtn = document.getElementById("send-button");
        if (sendBtn) {
          sendBtn.style.transform = "scale(0.94)";
          setTimeout(() => { sendBtn.style.transform = ""; }, 120);
        }
      }
    });
  }

  // ======== BUTTON PRESS DEPTH (physical feel) ========
  function setupButtonDepth() {
    const pressables = document.querySelectorAll(".btn, .chip, .send-btn, .ghost-btn, .tool-chip, .side-toggle, .icon-btn, .workspace");
    pressables.forEach((btn) => {
      btn.addEventListener("pointerdown", createRipple);
    });
  }

  // ======== METRIC VALUE OBSERVER (flash on change) ========
  function observeMetrics() {
    const metricIds = ["model-calls", "tool-calls", "last-sequence"];
    metricIds.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      let last = el.textContent;
      const observer = new MutationObserver(() => {
        if (el.textContent !== last) {
          last = el.textContent;
          flashNumber(el);
        }
      });
      observer.observe(el, { childList: true, characterData: true, subtree: true });
    });
  }

  // ======== MISSION LOG NEW MESSAGE OBSERVER ========
  function setupMissionLogObserver() {
    const log = document.getElementById("mission-log");
    if (!log) return;
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((m) => {
        m.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.classList?.contains("msg")) {
            animateMessageEntry(node);
            smoothScrollToBottom(log);
          }
        });
      });
    });
    observer.observe(log, { childList: true });
  }

  // ======== TIMELINE NEW EVENT OBSERVER ========
  function setupTimelineObserver() {
    const timeline = document.getElementById("timeline");
    if (!timeline) return;
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((m) => {
        m.addedNodes.forEach((node) => {
          if (node.nodeType === 1 && node.classList?.contains("event-row")) {
            node.style.opacity = "0";
            node.style.transform = "translateX(-8px)";
            requestAnimationFrame(() => {
              node.style.transition = "opacity 200ms cubic-bezier(0.16,1,0.3,1), transform 200ms cubic-bezier(0.16,1,0.3,1)";
              node.style.opacity = "1";
              node.style.transform = "translateX(0)";
              setTimeout(() => {
                node.style.transition = "";
                node.style.opacity = "";
                node.style.transform = "";
              }, 250);
            });
          }
        });
      });
    });
    observer.observe(timeline, { childList: true });
  }

  // ======== THEME SWITCH SMOOTHING ========
  function setupThemeTransition() {
    const select = document.getElementById("theme-select");
    if (!select) return;
    // Add a brief cross-fade class during theme switch
    select.addEventListener("change", () => {
      document.body.style.transition = "opacity 150ms ease";
      document.body.style.opacity = "0.6";
      requestAnimationFrame(() => {
        setTimeout(() => {
          document.body.style.opacity = "1";
          setTimeout(() => { document.body.style.transition = ""; }, 200);
        }, 80);
      });
    });
  }

  // ======== PROGRESS BAR ANIMATION ON START ========
  function setupProgressObserver() {
    const bar = document.getElementById("progress-bar");
    if (!bar) return;
    let lastWidth = bar.style.width || "0%";
    const observer = new MutationObserver(() => {
      if (bar.style.width !== lastWidth && bar.style.width !== "0%") {
        bar.style.transition = "width 400ms cubic-bezier(0.19,1,0.22,1)";
        lastWidth = bar.style.width;
      }
    });
    observer.observe(bar, { attributes: true, attributeFilter: ["style"] });
  }

  // ======== INIT ========
  function init() {
    injectRippleKeyframe();
    runBootSequence();

    // Wait for DOM content if needed
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        setupButtonDepth();
        setupSidebarToggle();
        setupPanelBackdrop();
        setupToastAnimation();
        setupKeyboardFeedback();
        observeMetrics();
        setupThemeTransition();
        setupProgressObserver();
        setupMissionLogObserver();
        setupTimelineObserver();
      });
    } else {
      setupButtonDepth();
      setupSidebarToggle();
      setupPanelBackdrop();
      setupToastAnimation();
      setupKeyboardFeedback();
      observeMetrics();
      setupThemeTransition();
      setupProgressObserver();
      setupMissionLogObserver();
      setupTimelineObserver();
    }
  }

  init();

  // Expose for app.js integration
  window.PCMotion = {
    animateMessageEntry,
    flashNumber,
    smoothScrollToBottom
  };
})();
