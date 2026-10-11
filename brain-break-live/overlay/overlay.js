/* Brain Break Live overlay: polls /api/state and draws the study, ambient or trivia layer.
   Everything from chat is inserted with textContent, never as HTML. ?muted=1 silences the music. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const MUTED = params.get("muted") === "1";
  let state = null, offset = 0, profileId = null, lastOk = Date.now();
  let look = { scene: "study-room", background: {}, effects: [] };

  // ---------------------------------------------------------------- stage scaling
  function fit() {
    const k = Math.min(innerWidth / 1920, innerHeight / 1080);
    const stage = $("stage");
    stage.style.transform = `scale(${k})`;
    stage.style.left = `${(innerWidth - 1920 * k) / 2}px`;
    stage.style.top = `${(innerHeight - 1080 * k) / 2}px`;
  }
  addEventListener("resize", fit); fit();
  BBRender.start($("scene"), () => look, 30);

  const now = () => Date.now() / 1000 + offset;
  const mmss = s => {
    s = Math.max(0, Math.ceil(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(x).padStart(2, "0")}`;
  };
  const show = (id, on) => $(id).classList.toggle("hidden", !on);
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function setList(ul, items, build) {
    const key = JSON.stringify(items);
    if (ul.dataset.key === key) return;
    ul.dataset.key = key;
    ul.replaceChildren(...items.map(build));
  }

  // ---------------------------------------------------------------- polling
  async function poll() {
    try {
      const r = await fetch("/api/state", { cache: "no-store" });
      const s = await r.json();
      offset = s.now - Date.now() / 1000;
      state = s; lastOk = Date.now();
      look = { scene: s.profile.scene, background: s.background || {}, effects: s.effects || s.profile.effects || [] };
      applyProfile(s.profile);
    } catch (e) { /* server restarting; keep the last picture */ }
    show("offline", Date.now() - lastOk > 5000);
    setTimeout(poll, 500);
  }

  function applyProfile(p) {
    if (p.id === profileId) return;
    profileId = p.id;
    const [accent, ink] = BBScenes.accent(p.scene);
    document.documentElement.style.setProperty("--accent", accent);
    document.documentElement.style.setProperty("--accent-ink", ink);
    $("channel").textContent = p.name;
    $("headline").textContent = p.headline || "";
    tickerIdx = 0;
    loadMusic();
  }

  // ---------------------------------------------------------------- render loop
  function render() {
    requestAnimationFrame(render);
    if (!state) return;
    const s = state, p = s.profile, t = now();
    const trivia = s.mode === "trivia" && s.trivia;
    document.body.classList.toggle("trivia", !!trivia);
    $("clock").textContent = new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    show("clock", p.clock);
    show("study-layer", !trivia);
    show("trivia-layer", !!trivia);
    if (trivia) renderTrivia(s.trivia, t); else renderStudy(s, t);
    renderBanner(s, t, !!trivia);
    renderToasts(s, t);
    renderTicker(s);
  }

  function renderStudy(s, t) {
    const p = s.profile, st = s.study || {};
    const pomo = st.pomodoro;
    document.body.classList.toggle("has-pomo", !!pomo);
    document.body.classList.toggle("on-break", !!pomo && pomo.phase === "break");
    show("pomo", !!pomo);
    if (pomo) {
      const left = pomo.ends - t, total = (pomo.phase === "focus" ? pomo.focus_minutes : pomo.break_minutes) * 60;
      $("pomo-phase").textContent = pomo.phase === "focus" ? "FOCUS" : "BREAK";
      $("pomo-time").textContent = mmss(left);
      $("ring-fill").style.strokeDashoffset = String(603.2 * (1 - Math.max(0, Math.min(1, left / total))));
      const who = pomo.active ? ` · ${pomo.active} studying with you` : "";
      $("pomo-sub").textContent = pomo.phase === "focus"
        ? `Session #${pomo.session} today${who}` : "Stretch · drink water · rest your eyes";
    }
    show("tasks", !!st.tasks);
    if (st.tasks) {
      show("task-empty", st.tasks.length === 0);
      setList($("task-list"), st.tasks, task => {
        const li = el("li", task.done ? "done" : "");
        li.append(el("span", "who", task.name), el("span", "what", task.text));
        return li;
      });
    }
    show("checkin", st.checkins != null && !pomo);
    if (st.checkins != null) {
      $("checkin-count").textContent = st.checkins;
      const label = $("checkin-label");
      label.replaceChildren(document.createTextNode(`${p.checkin_label || "here tonight"} · type `), el("b", null, p.checkin_command));
    }
    show("markets", !!p.market_clock);
    if (p.market_clock) renderMarkets(t);
    const bq = st.break_question;
    show("breakq", !!bq);
    if (bq) {
      $("breakq-text").textContent = bq.question;
      setList($("breakq-options"), bq.options.map((o, i) => [o, bq.correct == null ? null : i === bq.correct]), ([o, ok]) =>
        el("li", ok === true ? "correct" : ok === false ? "wrong" : "", o));
    }
    show("goal", !!st.goal);
    if (st.goal) {
      $("goal-label").textContent = st.goal.label;
      $("goal-num").textContent = `${st.goal.hours.toLocaleString()} / ${st.goal.target.toLocaleString()} h`;
      $("goal-fill").style.width = `${Math.min(100, (st.goal.hours / st.goal.target) * 100)}%`;
    }
  }

  function renderTrivia(g, t) {
    document.body.classList.remove("has-pomo", "on-break");
    document.body.classList.add("has-side");
    $("t-pack").textContent = g.pack;
    $("t-num").textContent = g.number ? `Question ${g.number}` : "";
    $("t-players").textContent = g.players ? `${g.players} playing` : "";
    show("t-double", g.double || g.double_next);
    $("t-double").textContent = g.double ? "2× POINTS" : "NEXT Q 2×";
    show("t-intro", g.phase === "intro");
    show("t-q", ["question", "locked", "reveal"].includes(g.phase));
    show("t-board", g.phase === "leaderboard" || g.phase === "final");
    if (g.phase === "intro") $("t-intro-title").textContent = `${g.pack} trivia starts in ${mmss(g.phase_ends - t)}`;
    if (g.question) {
      $("t-cat").textContent = g.category || g.pack;
      $("t-question").textContent = g.question;
      const res = g.result || {};
      setList($("t-options"), g.options.map((o, i) => [o, i, g.phase === "reveal" ? i === g.correct : null, (res.counts || [])[i]]),
        ([o, i, ok, n]) => {
          const li = el("li", ok === true ? "correct" : ok === false ? "wrong" : "", o);
          if (ok !== null && n != null) {
            li.append(el("span", "count", String(n)));
            const bar = el("span", "bar"); bar.style.width = `${res.answered ? (n / res.answered) * 100 : 0}%`; li.append(bar);
          }
          return li;
        });
      const left = g.phase === "question" ? g.phase_ends - t : 0;
      const fill = $("t-timer-fill");
      fill.style.width = `${Math.max(0, Math.min(100, (left / g.question_seconds) * 100))}%`;
      fill.classList.toggle("low", left < 6);
      const status = $("t-status");
      if (g.phase === "question") status.replaceChildren(document.createTextNode(`${mmss(left)} left · `), el("b", null, String(g.answered)), document.createTextNode(" answers"));
      else if (g.phase === "locked") status.textContent = "Time's up! Counting answers…";
      else {
        const n = res.correct_count || 0;
        status.replaceChildren(el("b", null, `${n} of ${res.answered || 0}`), document.createTextNode(" got it right"),
          ...(res.fastest ? [document.createTextNode(" · fastest: "), el("b", null, res.fastest)] : []));
      }
    }
    if (g.phase === "leaderboard" || g.phase === "final") {
      $("t-board-title").textContent = g.phase === "final" ? "Final standings — GG everyone!" : `Leaderboard after ${g.number} questions`;
      setList($("t-board-list"), g.leaderboard.slice(0, 6), r => {
        const li = el("li"); li.append(el("span", "name", r.name), el("span", "pts", `${r.points}`)); return li;
      });
    }
    show("t-side-empty", g.leaderboard.length === 0);
    setList($("t-side-list"), g.leaderboard.slice(0, 8), r => {
      const li = el("li"); li.append(el("span", "name", r.name), el("span", "pts", `${r.points}`)); return li;
    });
  }

  function renderBanner(s, t, trivia) {
    const b = $("banner");
    document.body.classList.toggle("has-side", trivia);
    if (trivia || !s.next_show || !s.profile.trivia_enabled) { show("banner", false); return; }
    const until = s.next_show.starts - t;
    if (until > 12 * 3600 || until < 0) { show("banner", false); return; }
    show("banner", true);
    if (until <= 15 * 60) {
      b.replaceChildren(document.createTextNode(`🎬 ${s.next_show.theme} trivia starts in `), el("b", null, mmss(until)), document.createTextNode(" · answer A/B/C/D in chat"));
    } else {
      const at = new Date(s.next_show.starts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      b.replaceChildren(document.createTextNode(`🎬 Tonight: ${s.next_show.theme} trivia at `), el("b", null, at));
    }
  }

  const shownToasts = new Set();
  function renderToasts(s, t) {
    const box = $("toasts");
    const live = (s.events || []).filter(e => t - e.at < 9).slice(-4);
    const key = live.map(e => e.at + e.text).join("|");
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.replaceChildren(...live.reverse().map(e => {
      const d = el("div", `toast ${e.kind}`, e.text);
      if (shownToasts.has(e.at + e.text)) d.style.animation = "none";
      shownToasts.add(e.at + e.text);
      return d;
    }));
  }

  let tickerIdx = 0, tickerAt = 0;
  function renderTicker(s) {
    const p = s.profile;
    const lines = [...(p.ticker || [])];
    if (p.affiliate_line) lines.push(p.affiliate_line);
    if (s.alltime && s.alltime.length) lines.push(`🏆 All-time trivia champ: ${s.alltime[0].name} (${s.alltime[0].points} pts)`);
    if (p.tasks) lines.push("Type !task <what you're doing> · !done when finished · !hours for your total");
    if (!lines.length) { $("ticker-text").textContent = ""; return; }
    if (Date.now() - tickerAt > 12000) {
      tickerAt = Date.now(); tickerIdx = (tickerIdx + 1) % lines.length;
      $("ticker-text").textContent = lines[tickerIdx % lines.length];
    }
  }

  // ---------------------------------------------------------------- market hours
  const MARKETS = [
    { name: "New York", tz: "America/New_York", s: [[9, 30, 16, 0]] },
    { name: "London", tz: "Europe/London", s: [[8, 0, 16, 30]] },
    { name: "Frankfurt", tz: "Europe/Berlin", s: [[9, 0, 17, 30]] },
    { name: "Tokyo", tz: "Asia/Tokyo", s: [[9, 0, 11, 30], [12, 30, 15, 30]] },
    { name: "Hong Kong", tz: "Asia/Hong_Kong", s: [[9, 30, 12, 0], [13, 0, 16, 0]] },
    { name: "Sydney", tz: "Australia/Sydney", s: [[10, 0, 16, 0]] },
  ];
  function zoned(t, tz) {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour12: false, weekday: "short", hour: "numeric", minute: "numeric", second: "numeric" })
      .formatToParts(new Date(t * 1000)).reduce((o, x) => (o[x.type] = x.value, o), {});
    const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(parts.weekday);
    return { wd, sec: (Number(parts.hour) % 24) * 3600 + Number(parts.minute) * 60 + Number(parts.second), hm: `${Number(parts.hour) % 24}:${String(parts.minute).padStart(2, "0")}` };
  }
  function marketState(m, t) {
    const z = zoned(t, m.tz);
    const weekday = z.wd >= 1 && z.wd <= 5;
    const sessions = m.s.map(([a, b, c, d]) => [a * 3600 + b * 60, c * 3600 + d * 60]);
    if (weekday) {
      for (const [o, c] of sessions) if (z.sec >= o && z.sec < c) return { cls: "open", text: `open · closes in ${hmin(c - z.sec)}`, hm: z.hm };
      if (z.sec >= sessions[0][0] && z.sec < sessions[sessions.length - 1][1]) return { cls: "lunch", text: "lunch break", hm: z.hm };
    }
    // next open: walk forward day by day (local market time)
    let secs = 0, wd = z.wd, sec = z.sec;
    for (let i = 0; i < 8; i++) {
      if (wd >= 1 && wd <= 5 && sec < sessions[0][0]) { secs += sessions[0][0] - sec; break; }
      secs += 86400 - sec; sec = 0; wd = (wd + 1) % 7;
    }
    return { cls: "", text: `opens in ${hmin(secs)}`, hm: z.hm };
  }
  function hmin(secs) {
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
    return `${h ? h + "h " : ""}${m}m`;
  }
  function renderMarkets(t) {
    const rows = MARKETS.map(m => ({ m, s: marketState(m, t) }));
    setList($("market-list"), rows.map(r => [r.m.name, r.s.cls, r.s.text, r.s.hm]), ([name, cls, text, hm]) => {
      const li = el("li", cls);
      const label = el("span", null, name); label.append(el("span", "local", hm));
      li.append(el("span", "dot"), label, el("span", "when", text));
      return li;
    });
  }

  // ---------------------------------------------------------------- music
  const player = $("player");
  let tracks = [], queue = [];
  async function loadMusic() {
    try {
      const r = await fetch("/api/music", { cache: "no-store" });
      tracks = (await r.json()).tracks || [];
    } catch (e) { tracks = []; }
    queue = [];
    player.pause();
    show("music", tracks.length > 0);
    if (tracks.length && !MUTED) next();
  }
  function next() {
    if (!tracks.length) return;
    if (!queue.length) queue = [...tracks].sort(() => Math.random() - 0.5);
    const name = queue.shift();
    player.src = `/music/${encodeURIComponent(name)}`;
    player.volume = state ? state.profile.music_volume : 0.6;
    $("track").textContent = name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    player.play().catch(() => { /* autoplay blocked outside OBS: tick "Control audio via OBS" */ });
  }
  player.addEventListener("ended", next);
  player.addEventListener("error", () => setTimeout(next, 2000));

  poll();
  requestAnimationFrame(render);
})();
