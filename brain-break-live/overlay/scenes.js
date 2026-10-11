/* Animated backgrounds, drawn on a 1920x1080 canvas. No images, video or fonts needed.
   Each scene gets (ctx, t seconds, env) where env.day is 0 (night) .. 1 (midday) from the local hour. */
(function () {
  "use strict";
  const W = 1920, H = 1080;
  const rand = (seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647)(42);
  const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k));
  const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

  function daylight(date) {
    const h = date.getHours() + date.getMinutes() / 60;
    // 0 before 5:00 and after 21:00, ramps through dawn/dusk, 1 between 9:00 and 17:00
    if (h < 5 || h >= 21) return 0;
    if (h < 9) return (h - 5) / 4;
    if (h < 17) return 1;
    return 1 - (h - 17) / 4;
  }

  function skyGradient(ctx, x, y, w, h, day) {
    const top = mix([8, 10, 28], [92, 156, 222], day);
    const mid = mix([28, 24, 58], [168, 204, 236], day);
    const low = mix([62, 38, 72], [255, 214, 170], Math.max(0, 1 - Math.abs(day - 0.45) * 2.2) * 0.9 + day * 0.1);
    const g = ctx.createLinearGradient(0, y, 0, y + h);
    g.addColorStop(0, rgb(top)); g.addColorStop(0.6, rgb(mid)); g.addColorStop(1, rgb(low));
    ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
  }

  const STARS = Array.from({ length: 260 }, () => ({ x: rand() * W, y: rand() * H * 0.75, r: rand() * 1.6 + 0.3, p: rand() * 6 }));
  function stars(ctx, t, alpha, clip) {
    if (alpha <= 0.02) return;
    for (const s of STARS) {
      if (clip && !clip(s)) continue;
      const tw = 0.55 + 0.45 * Math.sin(t * 1.3 + s.p);
      ctx.fillStyle = `rgba(255,255,255,${alpha * tw})`;
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 7); ctx.fill();
    }
  }

  function makeRain(n, speed, len) {
    return Array.from({ length: n }, () => ({ x: rand() * W, y: rand() * H, v: speed * (0.7 + rand() * 0.6), l: len * (0.6 + rand() * 0.8) }));
  }
  function rain(ctx, drops, dt, alpha, clip) {
    ctx.strokeStyle = `rgba(200,215,255,${alpha})`; ctx.lineWidth = 1.4; ctx.beginPath();
    for (const d of drops) {
      d.y += d.v * dt; d.x -= d.v * dt * 0.08;
      if (d.y > H) { d.y = -d.l; d.x = rand() * W * 1.1; }
      if (clip && !clip(d)) continue;
      ctx.moveTo(d.x, d.y); ctx.lineTo(d.x - d.l * 0.08, d.y + d.l);
    }
    ctx.stroke();
  }

  // City skyline shared by a few scenes: building rects + lit windows
  function makeSkyline(baseY, layers) {
    return layers.map((L, li) => {
      const bs = []; let x = -20;
      while (x < W + 40) {
        const w = L.wMin + rand() * (L.wMax - L.wMin), h = L.hMin + rand() * (L.hMax - L.hMin);
        const wins = [];
        for (let wy = baseY - h + 18; wy < baseY - 14; wy += 22) for (let wx = x + 10; wx < x + w - 12; wx += 18)
          if (rand() < L.lit) wins.push({ x: wx, y: wy, p: rand() * 100, c: rand() < 0.8 ? [255, 214, 140] : [170, 210, 255] });
        bs.push({ x, w, h, wins }); x += w + L.gap * rand();
      }
      return { bs, shade: L.shade, li };
    });
  }
  function skyline(ctx, t, city, baseY, day) {
    for (const layer of city) {
      ctx.fillStyle = rgb(mix(layer.shade, [70, 84, 110], day * 0.6));
      for (const b of layer.bs) {
        ctx.fillRect(b.x, baseY - b.h, b.w, b.h + 400);
        if (day < 0.75) for (const wn of b.wins) {
          const on = Math.sin(t * 0.05 + wn.p) > -0.85;
          if (!on) continue;
          ctx.fillStyle = rgba(wn.c, (0.85 - day) * (layer.li ? 0.95 : 0.55));
          ctx.fillRect(wn.x, wn.y, 8, 11);
        }
        ctx.fillStyle = rgb(mix(layer.shade, [70, 84, 110], day * 0.6));
      }
    }
  }

  // ------------------------------------------------------------------ scenes
  const scenes = {};

  /* cosy desk in front of a window, rain on the glass */
  scenes["study-room"] = (() => {
    const drops = makeRain(260, 900, 28);
    const city = makeSkyline(700, [
      { wMin: 50, wMax: 120, hMin: 120, hMax: 300, gap: 12, lit: 0.25, shade: [22, 24, 44] },
      { wMin: 70, wMax: 150, hMin: 60, hMax: 200, gap: 20, lit: 0.35, shade: [14, 15, 30] }]);
    const win = { x: 560, y: 110, w: 800, h: 600 };
    const inWin = p => p.x > win.x && p.x < win.x + win.w && p.y > win.y && p.y < win.y + win.h;
    let last = 0;
    return (ctx, t, env) => {
      const dt = Math.min(0.1, t - last); last = t;
      const day = env.day;
      // wall
      const wall = ctx.createLinearGradient(0, 0, 0, H);
      wall.addColorStop(0, rgb(mix([28, 22, 30], [96, 84, 80], day)));
      wall.addColorStop(1, rgb(mix([16, 12, 18], [70, 58, 54], day)));
      ctx.fillStyle = wall; ctx.fillRect(0, 0, W, H);
      // window view
      ctx.save(); ctx.beginPath(); ctx.rect(win.x, win.y, win.w, win.h); ctx.clip();
      skyGradient(ctx, win.x, win.y, win.w, win.h, day);
      stars(ctx, t, 1 - day * 1.6, inWin);
      skyline(ctx, t, city, 700, day);
      rain(ctx, drops, dt, 0.35, inWin);
      ctx.restore();
      // frame + mullions
      ctx.strokeStyle = rgb(mix([40, 30, 28], [120, 100, 86], day)); ctx.lineWidth = 26;
      ctx.strokeRect(win.x, win.y, win.w, win.h);
      ctx.lineWidth = 14; ctx.beginPath();
      ctx.moveTo(win.x + win.w / 2, win.y); ctx.lineTo(win.x + win.w / 2, win.y + win.h);
      ctx.moveTo(win.x, win.y + win.h * 0.45); ctx.lineTo(win.x + win.w, win.y + win.h * 0.45); ctx.stroke();
      // lamp glow
      const glowA = 0.55 - day * 0.35 + Math.sin(t * 2.1) * 0.01;
      const glow = ctx.createRadialGradient(1500, 690, 10, 1500, 690, 620);
      glow.addColorStop(0, `rgba(255,190,110,${glowA})`); glow.addColorStop(1, "rgba(255,190,110,0)");
      ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
      // desk
      ctx.fillStyle = rgb(mix([34, 22, 16], [92, 64, 44], day)); ctx.fillRect(0, 820, W, 260);
      ctx.fillStyle = rgb(mix([52, 34, 24], [128, 92, 64], day)); ctx.fillRect(0, 806, W, 22);
      // lamp
      ctx.fillStyle = "#1b1512";
      ctx.fillRect(1494, 600, 10, 210); ctx.fillRect(1440, 800, 120, 12);
      ctx.beginPath(); ctx.moveTo(1420, 610); ctx.lineTo(1580, 610); ctx.lineTo(1540, 540); ctx.lineTo(1460, 540); ctx.closePath(); ctx.fill();
      ctx.fillStyle = `rgba(255,214,150,${0.7 - day * 0.4})`; ctx.fillRect(1430, 606, 140, 6);
      // books
      const books = [[300, 60, [120, 52, 48]], [362, 44, [52, 80, 110]], [408, 70, [150, 120, 70]], [480, 38, [70, 100, 74]]];
      for (const [bx, bw, c] of books) { ctx.fillStyle = rgb(mix(mix(c, [0, 0, 0], 0.55), c, day)); ctx.fillRect(bx, 640, bw, 168); }
      // mug + steam
      ctx.fillStyle = rgb(mix([60, 60, 70], [220, 220, 228], day * 0.8 + 0.1)); ctx.fillRect(1180, 730, 80, 78);
      ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 10; ctx.beginPath(); ctx.arc(1264, 768, 20, -1.4, 1.4); ctx.stroke();
      ctx.strokeStyle = "rgba(255,255,255,0.18)"; ctx.lineWidth = 5;
      for (let i = 0; i < 3; i++) {
        ctx.beginPath();
        for (let y = 0; y < 120; y += 6) {
          const x = 1200 + i * 20 + Math.sin(y / 18 + t * 1.6 + i) * 8;
          y === 0 ? ctx.moveTo(x, 720 - y) : ctx.lineTo(x, 720 - y);
        }
        ctx.stroke();
      }
      // plant
      ctx.fillStyle = "#3a2a20"; ctx.fillRect(700, 740, 90, 70);
      ctx.fillStyle = rgb(mix([24, 54, 36], [62, 128, 78], day));
      for (let i = 0; i < 7; i++) {
        const a = -1.9 + i * 0.32 + Math.sin(t * 0.6 + i) * 0.03;
        ctx.beginPath(); ctx.ellipse(745 + Math.cos(a) * 60, 730 + Math.sin(a) * 60, 52, 16, a, 0, 7); ctx.fill();
      }
    };
  })();

  /* big rainy window, blurry city lights */
  scenes["rain-window"] = (() => {
    const drops = makeRain(700, 1100, 34);
    const beads = Array.from({ length: 160 }, () => ({ x: rand() * W, y: rand() * H, r: 2 + rand() * 6, v: rand() < 0.15 ? 30 + rand() * 90 : 0 }));
    const bokeh = Array.from({ length: 70 }, () => ({ x: rand() * W, y: 520 + rand() * 480, r: 20 + rand() * 60, c: rand() < 0.6 ? [255, 190, 110] : rand() < 0.5 ? [120, 180, 255] : [255, 110, 120], p: rand() * 9 }));
    let last = 0;
    return (ctx, t, env) => {
      const dt = Math.min(0.1, t - last); last = t;
      const day = env.day * 0.6;
      skyGradient(ctx, 0, 0, W, H, day);
      ctx.fillStyle = `rgba(10,14,30,${0.55 - day * 0.3})`; ctx.fillRect(0, 0, W, H);
      for (const b of bokeh) {
        const a = (0.16 + 0.06 * Math.sin(t * 0.5 + b.p)) * (1 - day);
        const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r);
        g.addColorStop(0, rgba(b.c, a)); g.addColorStop(1, rgba(b.c, 0));
        ctx.fillStyle = g; ctx.fillRect(b.x - b.r, b.y - b.r, b.r * 2, b.r * 2);
      }
      rain(ctx, drops, dt, 0.22);
      for (const d of beads) {
        d.y += d.v * dt; if (d.y > H + 10) { d.y = -10; d.x = rand() * W; }
        ctx.fillStyle = "rgba(220,235,255,0.20)"; ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, 7); ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,0.35)"; ctx.beginPath(); ctx.arc(d.x - d.r * 0.3, d.y - d.r * 0.3, d.r * 0.3, 0, 7); ctx.fill();
      }
      ctx.fillStyle = "#0c0b10"; ctx.fillRect(0, 0, W, 26); ctx.fillRect(0, H - 26, W, 26); ctx.fillRect(0, 0, 26, H); ctx.fillRect(W - 26, 0, 26, H); ctx.fillRect(W / 2 - 9, 0, 18, H);
    };
  })();

  /* fireplace in a dark room */
  scenes["fireplace"] = (() => {
    const sparks = Array.from({ length: 70 }, () => ({ x: 960 + (rand() - 0.5) * 300, y: 820 - rand() * 300, v: 40 + rand() * 80, p: rand() * 9 }));
    let last = 0;
    return (ctx, t) => {
      const dt = Math.min(0.1, t - last); last = t;
      const flick = 0.85 + Math.sin(t * 9) * 0.05 + Math.sin(t * 13.7) * 0.04 + Math.sin(t * 3.1) * 0.06;
      ctx.fillStyle = "#0d0807"; ctx.fillRect(0, 0, W, H);
      const room = ctx.createRadialGradient(960, 780, 40, 960, 780, 1200);
      room.addColorStop(0, `rgba(255,140,60,${0.42 * flick})`); room.addColorStop(0.5, `rgba(120,50,20,${0.22 * flick})`); room.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = room; ctx.fillRect(0, 0, W, H);
      // mantel + bricks
      ctx.fillStyle = "#2a1712"; ctx.fillRect(560, 360, 800, 600);
      ctx.fillStyle = "#3a2018"; ctx.fillRect(520, 330, 880, 46);
      ctx.fillStyle = "#070404"; ctx.beginPath(); ctx.moveTo(680, 960); ctx.lineTo(680, 560); ctx.quadraticCurveTo(960, 470, 1240, 560); ctx.lineTo(1240, 960); ctx.fill();
      // flames
      for (let i = 0; i < 9; i++) {
        const cx = 800 + i * 40, hgt = (150 + 90 * Math.sin(t * 3 + i * 1.7) + 50 * Math.sin(t * 7.3 + i)) * flick;
        const g = ctx.createLinearGradient(0, 880 - hgt, 0, 880);
        g.addColorStop(0, "rgba(255,230,140,0)"); g.addColorStop(0.35, "rgba(255,170,60,0.7)"); g.addColorStop(1, "rgba(255,80,20,0.95)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(cx - 46, 880);
        ctx.quadraticCurveTo(cx - 40 + Math.sin(t * 5 + i) * 14, 880 - hgt * 0.6, cx + Math.sin(t * 4 + i) * 18, 880 - hgt);
        ctx.quadraticCurveTo(cx + 40 + Math.sin(t * 6 + i) * 14, 880 - hgt * 0.6, cx + 46, 880); ctx.fill();
      }
      ctx.fillStyle = "#24140e"; ctx.fillRect(760, 878, 400, 26); ctx.fillRect(800, 860, 320, 22);
      for (const s of sparks) {
        s.y -= s.v * dt; s.x += Math.sin(t * 2 + s.p) * 0.6;
        if (s.y < 520) { s.y = 860; s.x = 960 + (rand() - 0.5) * 300; }
        ctx.fillStyle = `rgba(255,190,90,${(s.y - 520) / 340})`; ctx.fillRect(s.x, s.y, 3, 3);
      }
      ctx.fillStyle = "#120b09"; ctx.fillRect(0, 960, W, 120);
    };
  })();

  /* ocean horizon with sun or moon */
  scenes["ocean"] = (() => (ctx, t, env) => {
    const day = env.day;
    skyGradient(ctx, 0, 0, W, 620, day);
    stars(ctx, t, 1 - day * 1.6, s => s.y < 600);
    const orbY = 480 - day * 300, orbC = day > 0.25 ? [255, 236, 190] : [230, 236, 255];
    const halo = ctx.createRadialGradient(1340, orbY, 10, 1340, orbY, 260);
    halo.addColorStop(0, rgba(orbC, 0.5)); halo.addColorStop(1, rgba(orbC, 0));
    ctx.fillStyle = halo; ctx.fillRect(0, 0, W, 620);
    ctx.fillStyle = rgb(orbC); ctx.beginPath(); ctx.arc(1340, orbY, 54, 0, 7); ctx.fill();
    for (let i = 0; i < 9; i++) {
      const y0 = 600 + i * 56, amp = 6 + i * 3, sp = 0.4 + i * 0.12;
      ctx.fillStyle = rgb(mix(mix([10, 22, 48], [40, 110, 160], day), [4, 10, 24], i / 12));
      ctx.beginPath(); ctx.moveTo(0, H);
      for (let x = 0; x <= W; x += 24) ctx.lineTo(x, y0 + Math.sin(x / (140 + i * 30) + t * sp + i) * amp);
      ctx.lineTo(W, H); ctx.fill();
    }
    ctx.fillStyle = rgba(orbC, 0.25);
    for (let i = 0; i < 26; i++) {
      const y = 620 + i * 16, w = 160 - i * 4 + Math.sin(t * 2 + i) * 30;
      ctx.fillRect(1340 - w / 2 + Math.sin(t + i) * 10, y, w, 3);
    }
  })();

  /* night city skyline */
  scenes["night-city"] = (() => {
    const city = makeSkyline(1080, [
      { wMin: 60, wMax: 140, hMin: 300, hMax: 640, gap: 10, lit: 0.3, shade: [20, 22, 44] },
      { wMin: 90, wMax: 190, hMin: 180, hMax: 460, gap: 18, lit: 0.42, shade: [10, 11, 24] }]);
    return (ctx, t, env) => {
      const day = env.day * 0.8;
      skyGradient(ctx, 0, 0, W, H, day);
      stars(ctx, t, 1 - day * 1.6);
      const moon = ctx.createRadialGradient(420, 220, 0, 420, 220, 200);
      moon.addColorStop(0, `rgba(235,240,255,${0.9 - day})`); moon.addColorStop(0.25, `rgba(235,240,255,${0.25 - day * 0.2})`); moon.addColorStop(1, "rgba(235,240,255,0)");
      ctx.fillStyle = moon; ctx.fillRect(0, 0, W, 600);
      skyline(ctx, t, city, 1080, day);
      const blink = Math.sin(t * 3) > 0.6 ? 0.9 : 0.15;
      ctx.fillStyle = `rgba(255,60,60,${blink})`;
      for (const b of city[0].bs.filter((_, i) => i % 5 === 0)) ctx.fillRect(b.x + b.w / 2 - 3, 1080 - b.h - 10, 6, 6);
    };
  })();

  /* slow drifting starfield with a planet */
  scenes["space"] = (() => {
    const deep = Array.from({ length: 500 }, () => ({ x: rand() * W, y: rand() * H, z: 0.2 + rand() * 0.8, p: rand() * 9 }));
    return (ctx, t) => {
      ctx.fillStyle = "#04040b"; ctx.fillRect(0, 0, W, H);
      for (const [x, y, r, c] of [[500, 300, 700, [80, 40, 140]], [1500, 760, 800, [20, 80, 140]], [1100, 200, 500, [140, 40, 90]]]) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, rgba(c, 0.32)); g.addColorStop(1, rgba(c, 0));
        ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      }
      for (const s of deep) {
        const x = (s.x - t * 6 * s.z + W * 10) % W;
        ctx.fillStyle = `rgba(255,255,255,${s.z * (0.6 + 0.4 * Math.sin(t + s.p))})`;
        ctx.fillRect(x, s.y, s.z * 2.2, s.z * 2.2);
      }
      const px = 1450, py = 380, pr = 190;
      const pg = ctx.createRadialGradient(px - 70, py - 80, 20, px, py, pr);
      pg.addColorStop(0, "#f2b27a"); pg.addColorStop(0.6, "#a0503a"); pg.addColorStop(1, "#2a0f14");
      ctx.fillStyle = pg; ctx.beginPath(); ctx.arc(px, py, pr, 0, 7); ctx.fill();
      ctx.strokeStyle = "rgba(255,220,180,0.45)"; ctx.lineWidth = 8;
      ctx.beginPath(); ctx.ellipse(px, py, pr * 1.75, pr * 0.38, -0.32, 0.15, Math.PI - 0.15, true); ctx.stroke();
    };
  })();

  // ------------------------------------------------------------------ runner
  const ACCENTS = {
    "study-room": ["#ffb86b", "#1b1206"], "rain-window": ["#8ec5ff", "#06121f"], "fireplace": ["#ff9a52", "#1f0c02"],
    "ocean": ["#6fe0d6", "#03201d"], "night-city": ["#c49bff", "#160827"], "space": ["#ff8fc8", "#2a0619"],
  };

  window.BBScenes = {
    names: Object.keys(scenes),
    accent: name => ACCENTS[name] || ACCENTS["study-room"],
    start(canvas, getScene, fps) {
      const ctx = canvas.getContext("2d");
      const frame = 1000 / (fps || 30);
      let lastDraw = 0;
      const loop = now => {
        requestAnimationFrame(loop);
        if (now - lastDraw < frame - 2) return;
        lastDraw = now;
        const draw = scenes[getScene()] || scenes["study-room"];
        draw(ctx, now / 1000, { day: daylight(new Date()) });
      };
      requestAnimationFrame(loop);
    },
  };
})();
