// Sky guide: the "02 / Don't know where to start?" tab of the search panel (DESIGN §7.14).
// The page sends the question to our own API (POST /api/v1/assistant), which adds the guide's
// instructions and calls Google Gemini. The Gemini key lives only on the server, never here.
(() => {
  "use strict";

  // ---------- The character ----------
  // Six faces cut from the team's AI-generated character sheet (watermarked "AI-generated").
  const FACES = {
    open: "guide/stacy-open.webp",   // big smile, mouth open
    smile: "guide/stacy-smile.webp", // gentle smile
    calm: "guide/stacy-calm.webp",   // small, calm smile
    oh: "guide/stacy-oh.webp",       // little "o" mouth
    cute: "guide/stacy-cute.webp",   // ":3" mouth, small eyes
    joy: "guide/stacy-joy.webp",     // eyes closed, big laugh
  };
  // Which face each mood shows. "talking" cycles its faces so the mouth moves while it types.
  // The body's movement for each mood lives in sky.css ([data-mood]).
  //   idle       nothing asked yet, or resting: breathes and makes a random gesture every few seconds
  //   thinking   waiting for the answer (sways with three dots until it arrives)
  //   talking    the answer is being written out (a gentle bob; the mouth opens and closes)
  //   happy | explaining | excited | curious | sorry   chosen by Gemini for each answer (play once,
  //              then back to idle after REST_AFTER_MS)
  const MOODS = {
    idle: { faces: ["smile"] },
    thinking: { faces: ["cute"] },
    talking: { faces: ["open", "smile"], every: 260 },
    happy: { faces: ["open"] },
    explaining: { faces: ["calm"] },
    excited: { faces: ["joy"] },
    curious: { faces: ["oh"] },
    sorry: { faces: ["calm"] },
  };
  // Idle gestures: a CSS class on #guide-fidget (sky.css) and, for some, a face for a moment.
  // "blink" flashes the closed-eyes face, the closest the sheet has to a blink.
  const FIDGETS = [
    { cls: "fidget-wiggle", ms: 900 },
    { cls: "fidget-hop", ms: 700, face: "open" },
    { cls: "fidget-look", ms: 1600, face: "oh" },
    { cls: "fidget-twirl", ms: 1200 },
    { cls: "fidget-stretch", ms: 1000, face: "cute" },
    { cls: "", ms: 160, face: "joy" },
  ];
  const FIDGET_GAP_MS = [2500, 5000]; // random pause between gestures
  const REST_AFTER_MS = 4000;         // after an answer's reaction, go back to idle

  const MAX_HISTORY = 10; // turns sent back for context; the server accepts at most 10
  const TYPE_MS_PER_CHAR = 18;
  const TYPE_MAX_MS = 4000;

  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const loopback = new Set(["localhost", "127.0.0.1", "[::1]"]);

  const tabs = [$("tab-search"), $("tab-guide")];
  const character = $("guide-character");
  const face = $("guide-face");
  const fidget = $("guide-fidget");
  const log = $("guide-log");
  const form = $("guide-form");
  const input = $("guide-input");
  const send = $("guide-send");
  if (!tabs[0] || !tabs[1] || !form) return;

  const history = [];
  let busy = false;
  let apiBasePromise = null;

  // ---------- Tabs ----------
  function selectTab(tab, focus = false) {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
    }
    if (focus) tab.focus();
    if (tab === tabs[1] && !busy) setMood("idle");
    // A collapsed panel opens when a tab is chosen (sky.js owns the Hide / Search button)
    if ($("search-body").hidden) $("search-toggle").click();
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (step) {
        e.preventDefault();
        selectTab(tabs[(i + step + tabs.length) % tabs.length], true);
      } else if (e.key === "Home" || e.key === "End") {
        e.preventDefault();
        selectTab(tabs[e.key === "Home" ? 0 : tabs.length - 1], true);
      }
    });
  });

  // ---------- Character reactions ----------
  Object.values(FACES).forEach((src) => { new Image().src = src; }); // no flicker on the first swap
  let faceTimer = 0;
  let fidgetTimer = 0;
  let restTimer = 0;
  let lastFidget = -1;

  const guideVisible = () => !document.hidden && !$("panel-guide").hidden && !$("search-body").hidden;

  function stopFidgets() {
    clearTimeout(fidgetTimer);
    fidget.className = "guide-fidget";
  }

  // While idle, wait a few seconds, play one gesture, and repeat. Nothing runs while the tab
  // is hidden or the panel is closed, and never with reduced motion.
  function scheduleFidget() {
    clearTimeout(fidgetTimer);
    if (reduceMotion.matches || character.dataset.mood !== "idle") return;
    const [min, max] = FIDGET_GAP_MS;
    fidgetTimer = setTimeout(() => {
      if (character.dataset.mood !== "idle") return;
      if (!guideVisible()) return scheduleFidget();
      let pick;
      do pick = Math.floor(Math.random() * FIDGETS.length); while (pick === lastFidget);
      lastFidget = pick;
      const { cls, ms, face: f } = FIDGETS[pick];
      fidget.className = "guide-fidget";
      void fidget.offsetWidth;
      if (cls) fidget.classList.add(cls);
      if (f) face.src = FACES[f];
      fidgetTimer = setTimeout(() => {
        if (character.dataset.mood !== "idle") return;
        fidget.className = "guide-fidget";
        face.src = FACES[MOODS.idle.faces[0]];
        scheduleFidget();
      }, ms);
    }, min + Math.random() * (max - min));
  }

  function setMood(mood) {
    const { faces, every } = MOODS[mood] || MOODS.explaining;
    clearInterval(faceTimer);
    clearTimeout(restTimer);
    stopFidgets();
    face.src = FACES[faces[0]];
    if (faces.length > 1 && every && !reduceMotion.matches) {
      let i = 0;
      faceTimer = setInterval(() => {
        i = (i + 1) % faces.length;
        face.src = FACES[faces[i]];
      }, every);
    }
    // Restart the body's animation even when the same mood comes twice in a row
    character.dataset.mood = "";
    void character.offsetWidth;
    character.dataset.mood = mood;
    if (mood === "idle") scheduleFidget();
    else if (mood !== "thinking" && mood !== "talking") {
      restTimer = setTimeout(() => { if (!busy) setMood("idle"); }, REST_AFTER_MS);
    }
  }

  // ---------- Conversation ----------
  function addMessage(role, text) {
    const p = document.createElement("p");
    p.className = `guide-msg guide-msg-${role}`;
    p.textContent = text;
    log.append(p);
    log.scrollTop = log.scrollHeight;
    return p;
  }

  // Writes the answer out little by little while the character "talks"
  function typeOut(el, text) {
    if (reduceMotion.matches) {
      el.textContent = text;
      return Promise.resolve();
    }
    const perChar = Math.min(TYPE_MS_PER_CHAR, TYPE_MAX_MS / text.length);
    const start = performance.now();
    return new Promise((resolve) => {
      const step = (now) => {
        const shown = Math.min(text.length, Math.ceil((now - start) / perChar));
        el.textContent = text.slice(0, shown);
        log.scrollTop = log.scrollHeight;
        if (shown < text.length) requestAnimationFrame(step);
        else resolve();
      };
      requestAnimationFrame(step);
    });
  }

  // Same API as the blink viewer: apiBaseUrl in viewer-config.json. On a local page,
  // ?api=http://localhost:8000 points the guide at a local server for testing.
  function apiBase() {
    apiBasePromise ??= (async () => {
      const local = location.protocol === "http:" && loopback.has(location.hostname);
      const override = new URLSearchParams(location.search).get("api");
      let raw = local && override ? override : "";
      if (!raw) {
        const res = await fetch("viewer-config.json", { redirect: "error" });
        raw = res.ok ? (await res.json()).apiBaseUrl || "" : "";
      }
      const base = new URL(raw || location.origin, location.origin);
      const allowed = base.protocol === "https:" || (base.protocol === "http:" && loopback.has(base.hostname));
      if (!allowed) throw new Error("Disallowed API protocol");
      return base.href.replace(/\/?$/, "/");
    })();
    return apiBasePromise;
  }

  async function ask(message) {
    const base = await apiBase();
    const res = await fetch(new URL("api/v1/assistant", base), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: history.slice(-MAX_HISTORY) }),
      signal: AbortSignal.timeout(30000),
      redirect: "error",
    });
    if (res.ok) return res.json();
    const { detail } = await res.json().catch(() => ({}));
    const error = new Error(detail?.message || `HTTP ${res.status}`);
    error.status = res.status;
    error.code = detail?.code;
    throw error;
  }

  function errorText(error) {
    if (error.code === "assistant_disabled") return "I'm not set up on this server yet, so I can't answer for now.";
    if (error.code === "daily_limit") return "I've answered all the questions I can for today. Come back tomorrow!";
    if (error.status === 429) return "That's a lot of questions! Give me a minute and try again.";
    if (error.status === 422) return "That question is a bit long for me. Try it in fewer words (500 characters at most).";
    return "I couldn't reach my notes right now. Please try again in a moment.";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message || busy) return;
    busy = true;
    send.disabled = true;
    addMessage("user", message);
    input.value = "";
    setMood("thinking");
    try {
      const { reply, mood } = await ask(message);
      history.push({ role: "user", text: message }, { role: "model", text: reply });
      setMood("talking");
      await typeOut(addMessage("model", ""), reply);
      setMood(mood || "explaining");
    } catch (error) {
      addMessage("error", errorText(error));
      setMood("sorry");
    } finally {
      busy = false;
      send.disabled = false;
      input.focus();
    }
  });

  // Enter sends, Shift+Enter makes a new line
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // Quick questions only fill the box, so the visitor can edit them before sending
  document.querySelectorAll(".guide-quick [data-prompt]").forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = btn.dataset.prompt;
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
  });

  setMood("idle");
})();
