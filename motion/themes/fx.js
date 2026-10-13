// Small helpers shared by every template: palette injection, theme motion settings, word splitting.
// Deterministic only (no timers / randomness) — HyperFrames renders frame by frame.
(() => {
  const PALETTE = ["accent", "accent2", "bg", "panel", "text", "muted"];
  window.HF = {
    /** Apply palette variables, return {root, dur (composition length), M (theme motion)}. */
    setup(rootId) {
      const root = document.getElementById(rootId || "root");
      const v = window.__hyperframes.getVariables();
      // Palette arrives as c_<name> so it can never collide with a content prop (e.g. a callout's "text").
      // HyperFrames also publishes every prop as a CSS variable (--<id>), so palette CSS names must not match
      // any prop id: the "text" color is --ink (callout and kinetic have a "text" prop).
      const CSS_NAME = { text: "ink" };
      for (const k of PALETTE) if (v["c_" + k]) root.style.setProperty("--" + (CSS_NAME[k] || k), v["c_" + k]);
      const css = getComputedStyle(root);
      const read = (name, fallback) => (css.getPropertyValue(name) || "").trim() || fallback;
      const M = {
        ease: read("--ease", "power3.out"),
        easeIn: read("--ease-in", "power2.in"),
        pop: read("--ease-pop", "back.out(1.8)"),
        dur: parseFloat(read("--dur", "0.5")),
        stagger: parseFloat(read("--stagger", "0.07")),
        enter: parseFloat(read("--enter", "120")),
      };
      return { root, v, dur: parseFloat(root.dataset.duration), M };
    },
    /** Replace an element's text with one span per word (class "w") for staggered reveals. */
    words(el, text) {
      el.innerHTML = "";
      for (const word of String(text || "").split(/\s+/).filter(Boolean)) {
        const s = document.createElement("span");
        s.className = "w";
        s.textContent = word;
        el.appendChild(s);
      }
      return el.querySelectorAll(".w");
    },
    /** Set text, or remove the element when the text is empty. Returns true if kept. */
    text(id, value) {
      const el = document.getElementById(id);
      if (!el) return false;
      if (value === undefined || value === null || String(value).trim() === "") { el.remove(); return false; }
      el.textContent = value;
      return true;
    },
    /** Slow drift of the stage decorations so full-screen cards never feel frozen. */
    drift(tl, dur) {
      // --drift (per theme): 1 = full glow drift, 0 = structural decorations (stripes, rules) stay put.
      const k = parseFloat(getComputedStyle(document.getElementById("root")).getPropertyValue("--drift"));
      const s = Number.isFinite(k) ? k : 1;
      if (!s) return;
      tl.fromTo(".hf-deco-grid", { y: 0 }, { y: 80 * s, duration: dur, ease: "none" }, 0);
      tl.fromTo(".hf-deco-a", { x: 0, y: 0 }, { x: 160 * s, y: 90 * s, duration: dur, ease: "sine.inOut" }, 0);
      tl.fromTo(".hf-deco-b", { x: 0, y: 0 }, { x: -140 * s, y: -60 * s, duration: dur, ease: "sine.inOut" }, 0);
    },
  };
})();
