/* Pramana deck engine. No dependencies; works from file://.
   Query flags: ?s=7&step=2 (jump), ?still (no motion, final states), ?print (all slides for PDF),
   ?theme=paper, ?embed (presenter preview frame), ?presenter (speaker view). */
(() => {
  "use strict";
  const qs = new URLSearchParams(location.search);
  const root = document.documentElement;
  const BASE = location.href.split(/[?#]/)[0];
  const MODE = qs.has("presenter") ? "presenter" : qs.has("print") ? "print" : qs.has("embed") ? "embed" : "deck";
  const STILL = qs.has("still") || MODE === "print";

  try { const t = localStorage.getItem("pramana-theme"); if (t) root.dataset.theme = t; } catch (e) { /* storage blocked */ }
  if (qs.get("theme")) root.dataset.theme = qs.get("theme");
  if (STILL) root.classList.add("still");
  if (MODE === "print") root.classList.add("print");

  const stage = document.getElementById("stage");
  const slides = [...document.querySelectorAll(".slide")];
  const N = slides.length;
  let cur = 0, step = 0, presenterWin = null;

  /* ---------- helpers ---------- */
  const maxStep = (s) => [...s.querySelectorAll("[data-step]")].reduce((m, e) => Math.max(m, +e.dataset.step), 0);
  const notesOf = (s) => (s.querySelector(".notes") || {}).textContent || "";
  function mulberry(seed) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function stepsOn(el, s) { for (let e = el; e && e !== s; e = e.parentElement) if (e.dataset && e.dataset.step && !e.classList.contains("on")) return false; return true; }
  const svgEl = (tag, attrs, parent) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };

  /* ---------- scaling ---------- */
  function fit() {
    if (MODE === "print" || MODE === "presenter") return;
    const s = Math.min(innerWidth / 1920, innerHeight / 1080);
    stage.style.transformOrigin = "50% 50%";
    stage.style.transform = `translate(-50%, -50%) scale(${s})`;
  }
  addEventListener("resize", fit);

  /* ---------- counters & typewriter ---------- */
  const fmt = (v, dec) => dec ? v.toFixed(dec) : Math.round(v).toLocaleString("en-US");
  function runCounter(el) {
    const target = parseFloat(el.dataset.count), dec = +(el.dataset.dec || 0);
    if (STILL) { el.textContent = fmt(target, dec); return; }
    const t0 = performance.now(), dur = 1400, delay = 250;
    cancelAnimationFrame(el._raf);
    el.textContent = fmt(0, dec);
    const tick = (t) => { const p = Math.min(1, Math.max(0, (t - t0 - delay) / dur)); const e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * e, dec); if (p < 1) el._raf = requestAnimationFrame(tick); };
    el._raf = requestAnimationFrame(tick);
  }
  function runType(el) {
    const full = el.dataset.type;
    if (STILL) { el.textContent = full; return; }
    clearInterval(el._iv); clearTimeout(el._to); el.textContent = "";
    let i = 0;
    el._to = setTimeout(() => { el._iv = setInterval(() => { el.textContent = full.slice(0, ++i); if (i >= full.length) clearInterval(el._iv); }, 34); }, 700);
  }

  /* ---------- the drifting field of real section numbers (title, end) ---------- */
  const NUMS = ["302", "303", "378", "379", "420", "34", "103", "318", "323", "506", "498A", "304B", "120B", "351", "109", "307",
    "326", "411", "317", "3(5)", "115", "85", "80", "61", "149", "147", "354", "376", "64", "406", "316", "319", "324", "325",
    "118", "117", "308", "309", "304", "331", "457", "380", "392", "395", "467", "471", "336", "279", "106", "201"];
  document.querySelectorAll(".numfield").forEach((f, fi) => {
    const r = mulberry(7 + fi), count = f.classList.contains("quiet") ? 30 : 44;
    const placed = [];
    for (let tries = 0; placed.length < count && tries < 2000; tries++) {
      const lx = r() * 94, ty = r() * 90;
      if (lx < 72 && ty > 14 && ty < 84) continue;             // keep the text column clear
      if (placed.some(([x, y]) => Math.abs(x - lx) < 9 && Math.abs(y - ty) < 7)) continue;  // no pile-ups
      placed.push([lx, ty]);
      const sp = document.createElement("span");
      const code = r() < .5 ? "IPC" : "BNS";
      sp.textContent = (r() < .35 ? code + " " : "\u00a7 ") + NUMS[Math.floor(r() * NUMS.length)];
      const dur = 18 + r() * 18;
      sp.style.cssText = `left:${lx}%;top:${ty}%;--fs:${22 + Math.floor(r() * 30)}px;--dur:${dur}s;--delay:${-r() * dur}s;--op:${.16 + r() * .32};--dx:${-40 - r() * 80}px`;
      if (r() < .1) sp.classList.add("hot");
      if (STILL) { sp.style.animation = "none"; sp.style.opacity = (.16 + r() * .26).toFixed(2); }
      f.appendChild(sp);
    }
  });

  /* ---------- the real citation subgraph ---------- */
  const SG = window.SUBGRAPH;
  const ANCHOR = { "ipc:378": [400, 90], "ipc:379": [290, 330], "ipc:411": [400, 575], "bns:303": [820, 210], "bns:317": [820, 520] };
  let layout = null;
  function computeLayout() {
    if (!SG) return null;
    const r = mulberry(42), pos = {}, cites = {};
    SG.nodes.forEach((n) => { if (n.kind === "section") pos[n.id] = ANCHOR[n.id].slice(); });
    SG.edges.forEach((e) => { if (e.kind === "cites") (cites[e.from] = cites[e.from] || []).push(e.to); });
    const cases = SG.nodes.filter((n) => n.kind === "case").map((n) => n.id);
    cases.forEach((c) => { const t = cites[c] || []; const mx = t.reduce((a, s) => a + pos[s][0], 0) / t.length, my = t.reduce((a, s) => a + pos[s][1], 0) / t.length;
      pos[c] = [mx - 60 - r() * 90, my + (r() - .5) * 140]; });
    for (let it = 0; it < 420; it++) {
      cases.forEach((c) => { (cites[c] || []).forEach((s) => { const dx = pos[s][0] - pos[c][0], dy = pos[s][1] - pos[c][1], d = Math.hypot(dx, dy) || 1, f = (d - 118) * .03;
        pos[c][0] += dx / d * f; pos[c][1] += dy / d * f; }); });
      for (let a = 0; a < cases.length; a++) for (let b = a + 1; b < cases.length; b++) {
        const p = pos[cases[a]], q = pos[cases[b]], dx = q[0] - p[0], dy = q[1] - p[1], d = Math.hypot(dx, dy) || .1;
        if (d < 54) { const m = (54 - d) / 2 / d; p[0] -= dx * m; p[1] -= dy * m; q[0] += dx * m; q[1] += dy * m; } }
      cases.forEach((c) => { Object.keys(ANCHOR).forEach((s) => { const dx = pos[c][0] - pos[s][0], dy = pos[c][1] - pos[s][1], d = Math.hypot(dx, dy) || .1, min = s.startsWith("bns") ? 260 : 66;
        if (d < min) { pos[c][0] += dx / d * (min - d) * .5; pos[c][1] += dy / d * (min - d) * .5; } });
        pos[c][0] = Math.min(610, Math.max(30, pos[c][0])); pos[c][1] = Math.min(640, Math.max(20, pos[c][1])); });
    }
    return pos;
  }
  function drawGraph(svg, opts) {
    if (!SG || !svg) return;
    layout = layout || computeLayout();
    const keep = opts.keep ? new Set(opts.keep) : null;
    const gE = svgEl("g", {}, svg), gM = svgEl("g", {}, svg), gN = svgEl("g", {}, svg), gS = svgEl("g", {}, svg);
    let ei = 0, ci = 0;
    const show = (id) => !keep || keep.has(id);
    const casesShown = new Set();
    SG.edges.forEach((e) => {
      if (e.kind !== "cites" || !show(e.to)) return;
      casesShown.add(e.from);
      const a = layout[e.from], b = layout[e.to];
      svgEl("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: "g-edge", style: `--i:${ei++}` }, gE);
    });
    SG.nodes.forEach((n) => {
      if (n.kind !== "case" || !casesShown.has(n.id)) return;
      const p = layout[n.id];
      const c = svgEl("circle", { cx: p[0], cy: p[1], r: 9, class: "g-case" + (/Supreme/.test(n.court) ? " sc" : ""), style: `--i:${ci++}` }, gN);
      svgEl("title", {}, c).textContent = `${n.court}${n.year ? ", " + n.year : ""}`;
    });
    SG.edges.forEach((e) => {
      if (e.kind !== "maps_to" || !show(e.from)) return;
      const a = layout[e.from], b = layout[e.to];
      svgEl("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: "g-map " + (opts.drawMaps ? "drawn" : "dashed"), pathLength: 1 }, gM);
    });
    let si = 0;
    SG.nodes.filter((n) => n.kind === "section").forEach((n) => {
      const p = layout[n.id], rad = n.code === "bns" ? 40 : Math.max(32, Math.min(52, 22 + Math.sqrt(n.cited_by) * 2.4));
      const cls = `g-sec ${n.code}` + (opts.focus === n.id ? " focus" : "") + (keep && !keep.has(n.id) && opts.focus !== n.id ? " fade" : "");
      const g = svgEl("g", { class: cls, style: `--i:${si++}` }, gS);
      svgEl("circle", { cx: p[0], cy: p[1], r: rad }, g);
      svgEl("text", { x: p[0], y: p[1] - 4, style: "font-size:15px;font-weight:500" }, g).textContent = n.code.toUpperCase();
      svgEl("text", { x: p[0], y: p[1] + 20 }, g).textContent = n.section;
      const t = svgEl("text", { x: p[0], y: p[1] + rad + 24, class: "gt" }, g);
      t.textContent = n.title.length > 28 ? n.title.slice(0, 26) + "..." : n.title;
    });
    const lg = svgEl("g", { class: "g-legend", transform: "translate(700 610)" }, svg);
    svgEl("circle", { cx: 0, cy: 0, r: 8, class: "g-case sc", style: "opacity:1;transform:none" }, lg);
    svgEl("text", { x: 16, y: 6 }, lg).textContent = "Supreme Court";
    svgEl("circle", { cx: 0, cy: 28, r: 8, class: "g-case", style: "opacity:1;transform:none" }, lg);
    svgEl("text", { x: 16, y: 34 }, lg).textContent = "High Court";
    svgEl("line", { x1: -8, y1: 56, x2: 10, y2: 56, class: "g-map dashed", style: "opacity:1;stroke-width:3" }, lg);
    svgEl("text", { x: 16, y: 62 }, lg).textContent = "IPC to BNS mapping";
  }
  drawGraph(document.getElementById("g-main"), {});
  drawGraph(document.getElementById("g-bridge"), { keep: ["ipc:378", "ipc:379"], focus: "bns:303", drawMaps: true });

  /* ---------- per-slide hooks (called on every render) ---------- */
  const LANE_X = (c) => c * 421 + 20, ROW_Y = (r) => r * 116;
  const ICON = { ok: '<svg class="ico"><use href="#i-check"/></svg>', bad: '<svg class="ico"><use href="#i-cross"/></svg>' };
  const hooks = {
    journey(s, k) {
      s.querySelectorAll(".tok").forEach((t) => {
        const path = t.dataset.path.split(","), at = path[Math.min(k, path.length - 1)], row = +t.dataset.row;
        t.classList.toggle("gone", at === "-");
        const lane = at === "-" ? +path.find((p) => p !== "-") : +at;
        t.style.transform = `translate(${LANE_X(lane) - 20}px, ${ROW_Y(row)}px)`;
        const res = t.dataset.result;
        const judged = res === "ok" && k >= 2, failed = res === "bad" && k >= 2;
        t.classList.toggle("ok", judged); t.classList.toggle("bad", failed);
        t.classList.toggle("rest", res === "rest" && k >= 1);
        t.querySelector(".verdict").innerHTML = judged ? ICON.ok : failed ? ICON.bad : "";
      });
    },
    bridge(s, k) {
      const g = document.getElementById("g-bridge"); if (!g) return;
      g.classList.toggle("s1", k >= 2); g.classList.toggle("s2", k >= 3);
      g.querySelectorAll(".g-map").forEach((m) => m.classList.toggle("on", k >= 2));
    },
  };

  /* ---------- render one slide at a build step ---------- */
  function render(s, k) {
    s.querySelectorAll("[data-step]").forEach((e) => e.classList.toggle("on", +e.dataset.step <= k));
    const live = s.classList.contains("live");
    s.querySelectorAll("[data-count]").forEach((e) => { const now = live && stepsOn(e, s);
      if (now && !e._done) { e._done = true; runCounter(e); } else if (!now && e._done) { e._done = false; cancelAnimationFrame(e._raf); } });
    s.querySelectorAll("[data-type]").forEach((e) => { const now = live && stepsOn(e, s);
      if (now && !e._done) { e._done = true; runType(e); } else if (!now && e._done) { e._done = false; clearInterval(e._iv); clearTimeout(e._to); e.textContent = ""; } });
    if (hooks[s.id]) hooks[s.id](s, k);
  }

  /* ---------- media placeholders: show a file if it exists ---------- */
  const EXT = { video: ["mp4", "webm", "mov"], image: ["png", "jpg", "jpeg", "webp"] };
  document.querySelectorAll(".media[data-media]").forEach((fig) => {
    const kind = fig.dataset.kind, exts = EXT[kind] || EXT.image;
    const tryExt = (i) => {
      if (i >= exts.length) return;
      const src = `${fig.dataset.media}.${exts[i]}`;
      if (kind === "video") {
        const v = document.createElement("video");
        Object.assign(v, { muted: true, loop: true, playsInline: true, controls: true, preload: "auto" });
        v.addEventListener("loadeddata", () => { fig.prepend(v); fig.classList.add("loaded"); if (fig.closest(".slide.active")) v.play().catch(() => {}); }, { once: true });
        v.addEventListener("error", () => tryExt(i + 1), { once: true });
        v.src = src;
      } else {
        const img = new Image();
        img.onload = () => { img.alt = fig.dataset.caption || ""; fig.prepend(img); fig.classList.add("loaded"); };
        img.onerror = () => tryExt(i + 1);
        img.src = src;
      }
    };
    if (fig.dataset.caption) { const c = document.createElement("div"); c.className = "cap"; c.textContent = fig.dataset.caption; fig.appendChild(c); }
    fig.addEventListener("click", (e) => { if (fig.classList.contains("loaded")) e.stopPropagation(); });
    tryExt(0);
  });

  /* ---------- navigation ---------- */
  const chrome = document.getElementById("chrome");
  function updateChrome() {
    const s = slides[cur];
    chrome.querySelector(".chapter").textContent = s.dataset.chapter || "";
    chrome.querySelector(".count").textContent = `${String(cur + 1).padStart(2, "0")} / ${N}`;
    document.getElementById("progress").style.width = `${(cur / (N - 1)) * 100}%`;
    stage.classList.toggle("bare", s.id === "title" || s.id === "thanks");
    const nb = document.getElementById("nb-body");
    if (nb) { nb.textContent = notesOf(s); document.getElementById("nb-title").textContent = `${cur + 1}. ${s.dataset.title}`;
      const m = maxStep(s); document.getElementById("nb-step").textContent = m ? `build ${step} / ${m}` : ""; }
  }
  function postState() {
    if (presenterWin && !presenterWin.closed) presenterWin.postMessage({ type: "state", i: cur, step }, "*");
    if (MODE === "deck") { try { history.replaceState(null, "", `#${cur + 1}`); } catch (e) { /* file:// may refuse */ } }
  }
  function goto(i, k = 0) {
    i = Math.max(0, Math.min(N - 1, i));
    const prev = slides[cur], next = slides[i];
    if (prev !== next) {
      prev.classList.remove("active", "live"); render(prev, -1);
      prev.querySelectorAll("video").forEach((v) => v.pause());
    }
    cur = i; step = k === "end" ? maxStep(next) : Math.max(0, Math.min(maxStep(next), k));
    next.classList.add("active", "live");
    render(next, step);
    next.querySelectorAll(".media.loaded video").forEach((v) => v.play().catch(() => {}));
    updateChrome(); postState();
  }
  function nextStep() { if (step < maxStep(slides[cur])) { step++; render(slides[cur], step); updateChrome(); postState(); } else if (cur < N - 1) goto(cur + 1, 0); }
  function prevStep() { if (step > 0) { step--; render(slides[cur], step); updateChrome(); postState(); } else if (cur > 0) goto(cur - 1, "end"); }

  /* ---------- print: every slide, final build ---------- */
  if (MODE === "print") {
    slides.forEach((s, i) => {
      s.classList.add("active", "live"); render(s, maxStep(s));
      const f = document.createElement("div"); f.className = "pfoot";
      f.innerHTML = `<span class="brand">Pramana</span><span>${(s.dataset.chapter || "").toUpperCase()}</span><span class="count">${String(i + 1).padStart(2, "0")} / ${N}</span>`;
      if (s.id !== "title" && s.id !== "thanks") s.appendChild(f);
    });
    document.querySelectorAll("[data-count]").forEach((e) => { e.textContent = fmt(parseFloat(e.dataset.count), +(e.dataset.dec || 0)); });
    document.querySelectorAll("[data-type]").forEach((e) => { e.textContent = e.dataset.type; });
    return;
  }

  /* ---------- presenter window ---------- */
  if (MODE === "presenter") { buildPresenter(); return; }
  function buildPresenter() {
    document.getElementById("viewport").style.display = "none";
    ["notesbar", "help", "blackout"].forEach((id) => { const e = document.getElementById(id); if (e) e.remove(); });
    document.body.classList.add("presenter");
    document.title = "Pramana · presenter";
    const wrap = document.createElement("div"); wrap.className = "pv";
    wrap.innerHTML = `<div class="pv-top"><button id="pv-prev">Back</button><button id="pv-next">Next</button>
      <span class="clock" id="pv-clock">00:00</span><button id="pv-reset">Reset timer</button><span id="pv-pos"></span>
      <span id="pv-link" style="margin-left:auto"></span></div>
      <div class="pv-frames"><span class="pv-label">Now</span><div class="pv-frame"><iframe id="pv-cur" title="Current slide"></iframe></div>
      <span class="pv-label" id="pv-next-l">Next</span><div class="pv-frame next"><iframe id="pv-nxt" title="Next slide"></iframe></div></div>
      <div class="pv-notes"><h4 id="pv-title"></h4><div id="pv-notes"></div></div>`;
    document.body.appendChild(wrap);
    const fc = document.getElementById("pv-cur"), fn = document.getElementById("pv-nxt");
    fc.src = BASE + "?embed"; fn.src = BASE + "?embed&still";
    const send = (cmd, extra) => window.opener && window.opener.postMessage(Object.assign({ type: "cmd", cmd }, extra || {}), "*");
    document.getElementById("pv-prev").onclick = () => send("prev");
    document.getElementById("pv-next").onclick = () => send("next");
    let t0 = Date.now();
    document.getElementById("pv-reset").onclick = () => { t0 = Date.now(); };
    setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); document.getElementById("pv-clock").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }, 500);
    addEventListener("keydown", (e) => { if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); send("next"); }
      if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); send("prev"); } });
    let st = { i: 0, step: 0 };
    const show = () => {
      const s = slides[st.i], nx = slides[st.i + 1], m = maxStep(s);
      document.getElementById("pv-title").textContent = `${st.i + 1}. ${s.dataset.title}${m ? `  ·  build ${st.step} / ${m}` : ""}`;
      document.getElementById("pv-notes").textContent = notesOf(s);
      document.getElementById("pv-pos").textContent = `slide ${st.i + 1} / ${N}`;
      const lastBuild = st.step >= m;
      document.getElementById("pv-next-l").textContent = !lastBuild ? "Next: another build on this slide" : nx ? `Next: ${nx.dataset.title}` : "End";
      fc.contentWindow && fc.contentWindow.postMessage({ type: "goto", i: st.i, step: st.step }, "*");
      fn.contentWindow && fn.contentWindow.postMessage(lastBuild ? { type: "goto", i: Math.min(N - 1, st.i + 1), step: 0 } : { type: "goto", i: st.i, step: st.step + 1 }, "*");
    };
    addEventListener("message", (e) => { if (e.data && e.data.type === "state") { st = e.data; show(); } });
    fc.addEventListener("load", show); fn.addEventListener("load", show);
    if (window.opener) window.opener.postMessage({ type: "hello" }, "*");
    else document.getElementById("pv-link").textContent = "Open this view with P from the main deck.";
  }

  /* ---------- embed (presenter preview frames) ---------- */
  if (MODE === "embed") {
    addEventListener("message", (e) => { if (e.data && e.data.type === "goto") goto(e.data.i, e.data.step); });
  }

  /* ---------- keyboard, click, touch ---------- */
  let digits = "";
  const notesbar = document.getElementById("notesbar"), help = document.getElementById("help"), black = document.getElementById("blackout");
  function openPresenter() {
    presenterWin = window.open(BASE + "?presenter", "pramana-presenter", "width=1280,height=780");
    setTimeout(postState, 600);
  }
  if (MODE === "deck") {
    addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key;
      if (/^[0-9]$/.test(k)) { digits += k; return; }
      if (k === "Enter" && digits) { goto(parseInt(digits, 10) - 1, 0); digits = ""; return; }
      digits = "";
      if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"].includes(k)) { e.preventDefault(); black.classList.remove("on"); nextStep(); }
      else if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].includes(k)) { e.preventDefault(); black.classList.remove("on"); prevStep(); }
      else if (k === "Home") goto(0); else if (k === "End") goto(N - 1, "end");
      else if (k === "n" || k === "N") notesbar.classList.toggle("open");
      else if (k === "p" || k === "P") openPresenter();
      else if (k === "f" || k === "F") { if (!document.fullscreenElement) root.requestFullscreen && root.requestFullscreen().catch(() => {}); else document.exitFullscreen(); }
      else if (k === "t" || k === "T") { const v = root.dataset.theme === "paper" ? "" : "paper"; if (v) root.dataset.theme = v; else delete root.dataset.theme;
        try { localStorage.setItem("pramana-theme", v); } catch (err) { /* ignore */ } }
      else if (k === "b" || k === "B" || k === ".") black.classList.toggle("on");
      else if (k === "?" || k === "h" || k === "H") help.classList.toggle("open");
      else if (k === "Escape") { help.classList.remove("open"); notesbar.classList.remove("open"); black.classList.remove("on"); }
    });
    document.getElementById("viewport").addEventListener("click", (e) => { if (e.target.closest("a, button, video, input")) return; nextStep(); });
    let tx = null;
    addEventListener("touchstart", (e) => { tx = e.touches[0].clientX; }, { passive: true });
    addEventListener("touchend", (e) => { if (tx === null) return; const dx = e.changedTouches[0].clientX - tx; if (Math.abs(dx) > 50) (dx < 0 ? nextStep : prevStep)(); tx = null; });
    addEventListener("message", (e) => {
      const d = e.data || {};
      if (d.type === "hello") { presenterWin = e.source; postState(); }
      if (d.type === "cmd") { if (d.cmd === "next") nextStep(); if (d.cmd === "prev") prevStep(); if (d.cmd === "goto") goto(d.i, d.step || 0); }
    });
  }
  if (MODE === "embed") { chrome.style.opacity = ".9"; }

  /* ---------- start ---------- */
  fit();
  let startI = 0, startK = 0;
  if (qs.get("s")) startI = parseInt(qs.get("s"), 10) - 1;
  else if (/^#\d+$/.test(location.hash)) startI = parseInt(location.hash.slice(1), 10) - 1;
  if (qs.get("step")) startK = qs.get("step") === "end" ? "end" : parseInt(qs.get("step"), 10);
  goto(isNaN(startI) ? 0 : startI, startK);
})();
