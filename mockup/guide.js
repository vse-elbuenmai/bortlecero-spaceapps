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
  //   idle       nothing asked yet, or the conversation is resting (floats twice, then rests)
  //   thinking   waiting for the answer (sways with three dots until it arrives)
  //   talking    the answer is being written out (bobs and moves its mouth while it types)
  //   happy | explaining | excited | curious | sorry   chosen by Gemini for each answer (play once)
  const MOODS = {
    idle: { faces: ["smile"] },
    thinking: { faces: ["cute"] },
    talking: { faces: ["open", "smile", "oh", "smile"], every: 150 },
    happy: { faces: ["open"] },
    explaining: { faces: ["calm"] },
    excited: { faces: ["joy"] },
    curious: { faces: ["oh"] },
    sorry: { faces: ["calm"] },
  };

  const MAX_HISTORY = 10; // turns sent back for context; the server accepts at most 10
  const TYPE_MS_PER_CHAR = 18;
  const TYPE_MAX_MS = 4000;

  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const loopback = new Set(["localhost", "127.0.0.1", "[::1]"]);

  const tabs = [$("tab-search"), $("tab-guide")];
  const character = $("guide-character");
  const face = $("guide-face");
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

  function setMood(mood) {
    const { faces, every } = MOODS[mood] || MOODS.explaining;
    clearInterval(faceTimer);
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
