// Colour theme of the viewer: dark by default (DESIGN §2; an astronomical image reads best on black),
// light as a switch. The choice is remembered; `data-theme="light"` on <html> turns on the light tokens
// of mockup.css. The image and the sky stay black in both: only the frame around them changes.
// A one-line script in <head> sets the attribute before the first paint, so there is no flash.
(() => {
  "use strict";

  const STORAGE_KEY = "viewer-theme";
  const root = document.documentElement;
  const t = (key) => (window.i18n ? window.i18n.t(key) : key);
  const ICON_SUN = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3"/>' +
    '<path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/></svg>';
  const ICON_MOON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.2 9.8A5.6 5.6 0 0 1 6.2 2.8a5.6 5.6 0 1 0 7 7z"/></svg>';

  const current = () => (root.dataset.theme === "light" ? "light" : "dark");

  // Every switch shows the theme it would turn on: a sun while dark, a moon while light
  function label() {
    const light = current() === "light";
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.innerHTML = light ? ICON_MOON : ICON_SUN;
      const name = t(light ? "theme.to_dark" : "theme.to_light");
      btn.setAttribute("aria-label", name);
      btn.dataset.tip = name;
    });
  }

  function set(theme, { remember = true } = {}) {
    if (theme === "light") root.dataset.theme = "light";
    else delete root.dataset.theme;
    if (remember) { try { localStorage.setItem(STORAGE_KEY, current()); } catch { /* private window */ } }
    label();
    document.dispatchEvent(new CustomEvent("theme:change", { detail: { theme: current() } }));
  }

  window.theme = { set, get current() { return current(); } };

  label();
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => set(current() === "light" ? "dark" : "light")));
  document.addEventListener("i18n:change", label);
})();
