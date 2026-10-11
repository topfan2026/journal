/* Built-in backgrounds, used when a profile has no photo/video background.
   Each scene has:
     draw(ctx, t, env)  what is behind the glass / the main picture (effects can blur and refract it)
     fg(ctx, t, env)    optional: things in the room in front of the glass, drawn after rain-glass
     glass              optional {x, y, w, h}: where rain-glass applies (default: whole screen)
     effects            the realism layers it uses by default (see effects.js)
   env.day is 0 (night) .. 1 (midday) from the local hour. */
(function () {
  "use strict";
  const W = 1920, H = 1080;
  const rand = (seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647)(42);
  const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k));
  const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

  function daylight(date) {
    const h = date.getHours() + date.getMinutes() / 60;
    if (h < 5 || h >= 21) return 0;
    if (h < 9) return (h - 5) / 4;
    if (h < 17) return 1;
    return 1 - (h - 17) / 4;
  }

  function sky(ctx, x, y, w, h, day) {
    const top = mix([6, 9, 24], [92, 156, 222], day);
    const mid = mix([22, 24, 52], [160, 200, 236], day);
    const low = mix([70, 46, 70], [250, 216, 178], day);  // city glow at night, haze by day
    const g = ctx.createLinearGradient(0, y, 0, y + h);
    g.addColorStop(0, rgb(top)); g.addColorStop(0.55, rgb(mid)); g.addColorStop(1, rgb(low));
    ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
  }

  const STARS = Array.from({ length: 260 }, () => ({ x: rand() * W, y: rand() * H * 0.7, r: rand() * 1.5 + 0.3, p: rand() * 6 }));
  function stars(ctx, t, alpha, box) {
    if (alpha <= 0.02) return;
    for (const s of STARS) {
      const x = box ? box.x + (s.x / W) * box.w : s.x, y = box ? box.y + (s.y / H) * box.h : s.y;
      ctx.fillStyle = `rgba(255,255,255,${alpha * (0.55 + 0.45 * Math.sin(t * 1.3 + s.p))})`;
      ctx.fillRect(x, y, s.r, s.r);
    }
  }

  function glow(ctx, x, y, r, c, a) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, rgba(c, a)); g.addColorStop(0.25, rgba(c, a * 0.45)); g.addColorStop(1, rgba(c, 0));
    ctx.fillStyle = g; ctx.fillRect(x - r, y - r, r * 2, r * 2);
  }

  /* A night city street seen from a window: three building layers with lit windows, street lamps,
     and traffic. Laid out in a 1920x1080 frame and scaled into any box. Through fogged glass it
     turns into realistic bokeh. */
  const CITY = (() => {
    const WARM = [[255, 204, 140], [255, 186, 110], [255, 226, 180]], COOL = [[170, 205, 255], [210, 225, 255]];
    const layers = [
      { base: 760, hMin: 260, hMax: 620, wMin: 70, wMax: 150, shade: [26, 28, 52], lit: 0.18, win: 6 },
      { base: 840, hMin: 220, hMax: 560, wMin: 90, wMax: 190, shade: [17, 18, 36], lit: 0.32, win: 8 },
      { base: 940, hMin: 160, hMax: 460, wMin: 130, wMax: 260, shade: [10, 11, 22], lit: 0.45, win: 11 },
    ].map(L => {
      const bs = []; let x = -40;
      while (x < W + 60) {
        const w = L.wMin + rand() * (L.wMax - L.wMin), h = L.hMin + rand() * (L.hMax - L.hMin);
        const wins = [], gx = L.win + 8, gy = L.win * 1.6 + 8;
        for (let wy = L.base - h + 20; wy < L.base - 20; wy += gy)
          for (let wx = x + 12; wx < x + w - 12 - L.win; wx += gx)
            if (rand() < L.lit) wins.push({ x: wx, y: wy, c: rand() < 0.85 ? WARM[(rand() * 3) | 0] : COOL[(rand() * 2) | 0], p: rand() * 400 });
        bs.push({ x, w, h, wins, ant: rand() < 0.25 }); x += w + rand() * 14;
      }
      return { ...L, bs };
    });
    const lamps = Array.from({ length: 9 }, (_, i) => ({ x: 80 + i * 225 + rand() * 40 }));
    const cars = Array.from({ length: 10 }, (_, i) => ({ x: rand() * W, lane: i % 2, v: 90 + rand() * 120 }));

    function draw(ctx, t, day, box) {
      box = box || { x: 0, y: 0, w: W, h: H };
      ctx.save();
      ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
      ctx.translate(box.x, box.y); ctx.scale(box.w / W, box.h / H);
      sky(ctx, 0, 0, W, H, day);
      stars(ctx, t, 0.9 - day * 1.5);
      const night = 1 - day;
      for (const L of layers) {
        ctx.fillStyle = rgb(mix(L.shade, [92, 104, 128], day * 0.7));
        for (const b of L.bs) ctx.fillRect(b.x, L.base - b.h, b.w, b.h + 400);
        if (night > 0.1) for (const b of L.bs) {
          for (const w of b.wins) {
            if (Math.sin(t * 0.03 + w.p) < -0.9) continue;     // lights go on and off slowly
            ctx.fillStyle = rgba(w.c, 0.95 * night);
            ctx.fillRect(w.x, w.y, L.win, L.win * 1.4);
          }
          if (b.ant) {                                          // aircraft warning light
            const on = Math.sin(t * 2.4 + b.x) > 0.55;
            if (on) glow(ctx, b.x + b.w / 2, L.base - b.h - 8, 14, [255, 60, 50], 0.9 * night);
          }
        }
      }
      // street
      ctx.fillStyle = rgb(mix([8, 8, 14], [70, 72, 80], day)); ctx.fillRect(0, 940, W, 140);
      const road = ctx.createLinearGradient(0, 960, 0, 1080);
      road.addColorStop(0, rgba([255, 190, 120], 0.10 * night)); road.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = road; ctx.fillRect(0, 960, W, 120);
      for (const l of lamps) {
        ctx.fillStyle = "#07070b"; ctx.fillRect(l.x - 3, 850, 6, 110);
        glow(ctx, l.x, 852, 70, [255, 176, 92], 0.85 * night + 0.05);
        glow(ctx, l.x, 975, 120, [255, 170, 90], 0.18 * night);
      }
      for (const c of cars) {
        c.x = c.lane ? (c.x + c.v * 0.033) % (W + 200) : ((c.x - c.v * 0.033) % (W + 200) + W + 200) % (W + 200);
        const x = c.x - 100, y = c.lane ? 1012 : 990;
        const col = c.lane ? [255, 50, 40] : [255, 248, 225];
        glow(ctx, x, y, c.lane ? 26 : 40, col, 0.9 * night + 0.1);
        glow(ctx, x + (c.lane ? -26 : 26), y, c.lane ? 26 : 40, col, 0.9 * night + 0.1);
      }
      ctx.restore();
    }
    return { draw };
  })();

  // ------------------------------------------------------------------ scenes
  const scenes = {};

  /* cosy desk in front of a rainy window */
  const STUDY_WIN = { x: 560, y: 110, w: 800, h: 600 };
  scenes["study-room"] = {
    glass: STUDY_WIN,
    effects: ["rain-glass", "dust", "grain", "vignette"],
    draw(ctx, t, env) {
      const day = env.day;
      const wall = ctx.createLinearGradient(0, 0, 0, H);
      wall.addColorStop(0, rgb(mix([30, 23, 30], [104, 90, 84], day)));
      wall.addColorStop(1, rgb(mix([17, 12, 18], [72, 60, 56], day)));
      ctx.fillStyle = wall; ctx.fillRect(0, 0, W, H);
      CITY.draw(ctx, t, day, STUDY_WIN);
    },
    fg(ctx, t, env) {
      const day = env.day, w = STUDY_WIN;
      // light from the window falling into the room
      const spill = ctx.createLinearGradient(0, w.y + w.h, 0, H);
      spill.addColorStop(0, rgba(mix([90, 110, 170], [255, 240, 210], day), 0.10)); spill.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = spill; ctx.fillRect(w.x - 120, w.y + w.h, w.w + 240, H - w.y - w.h);
      // frame, sill, mullions
      const wood = mix([44, 32, 28], [128, 104, 88], day);
      ctx.strokeStyle = rgb(wood); ctx.lineWidth = 26; ctx.strokeRect(w.x, w.y, w.w, w.h);
      ctx.lineWidth = 14; ctx.beginPath();
      ctx.moveTo(w.x + w.w / 2, w.y); ctx.lineTo(w.x + w.w / 2, w.y + w.h);
      ctx.moveTo(w.x, w.y + w.h * 0.45); ctx.lineTo(w.x + w.w, w.y + w.h * 0.45); ctx.stroke();
      ctx.fillStyle = rgb(mix(wood, [0, 0, 0], 0.25)); ctx.fillRect(w.x - 40, w.y + w.h + 8, w.w + 80, 18);
      // lamp light pooling on wall and desk
      glow(ctx, 1500, 690, 640, [255, 186, 106], (0.5 - day * 0.32) + Math.sin(t * 2.1) * 0.008);
      // desk
      const desk = ctx.createLinearGradient(0, 820, 0, H);
      desk.addColorStop(0, rgb(mix([46, 30, 21], [116, 82, 56], day))); desk.addColorStop(1, rgb(mix([20, 13, 9], [70, 48, 32], day)));
      ctx.fillStyle = desk; ctx.fillRect(0, 820, W, H - 820);
      ctx.fillStyle = rgb(mix([62, 42, 30], [140, 102, 72], day)); ctx.fillRect(0, 806, W, 16);
      // lamp
      ctx.fillStyle = "#16110e";
      ctx.fillRect(1494, 600, 10, 210); ctx.fillRect(1440, 800, 120, 10);
      ctx.beginPath(); ctx.moveTo(1420, 610); ctx.lineTo(1580, 610); ctx.lineTo(1540, 540); ctx.lineTo(1460, 540); ctx.closePath(); ctx.fill();
      ctx.fillStyle = `rgba(255,214,150,${0.75 - day * 0.4})`; ctx.fillRect(1428, 606, 144, 5);
      glow(ctx, 1500, 640, 90, [255, 220, 160], 0.35 - day * 0.2);
      // books with lamp-lit edges
      for (const [bx, bw, bh, c] of [[300, 60, 168, [120, 52, 48]], [362, 44, 150, [52, 80, 110]], [408, 70, 176, [150, 120, 70]], [480, 38, 140, [70, 100, 74]]]) {
        const col = mix(mix(c, [0, 0, 0], 0.55), c, day * 0.8 + 0.1);
        ctx.fillStyle = rgb(col); ctx.fillRect(bx, 808 - bh, bw, bh);
        ctx.fillStyle = "rgba(0,0,0,0.25)"; ctx.fillRect(bx + bw - 6, 808 - bh, 6, bh);
        ctx.fillStyle = "rgba(255,230,190,0.12)"; ctx.fillRect(bx + 8, 808 - bh + 20, bw - 16, 4);
      }
      // mug with steam
      ctx.fillStyle = rgb(mix([66, 66, 76], [222, 222, 230], day * 0.8 + 0.1)); ctx.fillRect(1180, 730, 80, 78);
      ctx.fillStyle = "rgba(255,200,140,0.18)"; ctx.fillRect(1238, 730, 22, 78);
      ctx.strokeStyle = rgb(mix([66, 66, 76], [222, 222, 230], day * 0.8 + 0.1)); ctx.lineWidth = 10;
      ctx.beginPath(); ctx.arc(1264, 768, 20, -1.4, 1.4); ctx.stroke();
      ctx.lineWidth = 6;
      for (let i = 0; i < 3; i++) {
        ctx.strokeStyle = `rgba(255,255,255,${0.10 + 0.05 * Math.sin(t + i)})`;
        ctx.beginPath();
        for (let y = 0; y < 130; y += 5) {
          const x = 1200 + i * 20 + Math.sin(y / 18 + t * 1.4 + i) * (6 + y / 14);
          y === 0 ? ctx.moveTo(x, 722 - y) : ctx.lineTo(x, 722 - y);
        }
        ctx.stroke();
      }
      // plant
      ctx.fillStyle = "#3a2a20"; ctx.fillRect(700, 740, 90, 68);
      for (let i = 0; i < 9; i++) {
        const a = -2.0 + i * 0.27 + Math.sin(t * 0.5 + i) * 0.025;
        ctx.fillStyle = rgb(mix([18 + i * 3, 46 + i * 4, 30], [56 + i * 4, 120 + i * 5, 72], day));
        ctx.beginPath(); ctx.ellipse(745 + Math.cos(a) * 62, 728 + Math.sin(a) * 62, 56, 15, a, 0, 7); ctx.fill();
      }
    },
  };

  /* rain streaming down a big window, the city out of focus behind it */
  scenes["rain-window"] = {
    effects: ["rain-glass", "lightning", "grain", "vignette"],
    draw(ctx, t, env) { CITY.draw(ctx, t, env.day * 0.7); },
    fg(ctx) {
      ctx.fillStyle = "#0b0a0e";
      ctx.fillRect(0, 0, W, 22); ctx.fillRect(0, H - 22, W, 22); ctx.fillRect(0, 0, 22, H); ctx.fillRect(W - 22, 0, 22, H);
      ctx.fillRect(W / 2 - 8, 0, 16, H);
    },
  };

  /* fireplace in a dark room */
  scenes["fireplace"] = (() => {
    const sparks = Array.from({ length: 70 }, () => ({ x: 960 + (rand() - 0.5) * 300, y: 820 - rand() * 300, v: 40 + rand() * 80, p: rand() * 9 }));
    let last = 0;
    return {
      effects: ["grain", "vignette"],
      draw(ctx, t) {
        const dt = Math.min(0.1, t - last); last = t;
        const flick = 0.85 + Math.sin(t * 9) * 0.05 + Math.sin(t * 13.7) * 0.04 + Math.sin(t * 3.1) * 0.06;
        ctx.fillStyle = "#0d0807"; ctx.fillRect(0, 0, W, H);
        glow(ctx, 960, 780, 1200, [255, 130, 55], 0.42 * flick);
        ctx.fillStyle = "#2a1712"; ctx.fillRect(560, 360, 800, 600);
        for (let y = 372; y < 960; y += 28) for (let x = 560 + ((y / 28) % 2) * 30; x < 1360; x += 60) {
          ctx.fillStyle = `rgba(0,0,0,${0.18 + ((x * 7 + y) % 5) * 0.03})`; ctx.fillRect(x, y, 56, 24);
        }
        ctx.fillStyle = "#3a2018"; ctx.fillRect(520, 330, 880, 46);
        ctx.fillStyle = "#070404"; ctx.beginPath(); ctx.moveTo(680, 960); ctx.lineTo(680, 560); ctx.quadraticCurveTo(960, 470, 1240, 560); ctx.lineTo(1240, 960); ctx.fill();
        for (let i = 0; i < 9; i++) {
          const cx = 800 + i * 40, hgt = (150 + 90 * Math.sin(t * 3 + i * 1.7) + 50 * Math.sin(t * 7.3 + i)) * flick;
          const g = ctx.createLinearGradient(0, 880 - hgt, 0, 880);
          g.addColorStop(0, "rgba(255,230,140,0)"); g.addColorStop(0.35, "rgba(255,170,60,0.7)"); g.addColorStop(1, "rgba(255,80,20,0.95)");
          ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(cx - 46, 880);
          ctx.quadraticCurveTo(cx - 40 + Math.sin(t * 5 + i) * 14, 880 - hgt * 0.6, cx + Math.sin(t * 4 + i) * 18, 880 - hgt);
          ctx.quadraticCurveTo(cx + 40 + Math.sin(t * 6 + i) * 14, 880 - hgt * 0.6, cx + 46, 880); ctx.fill();
        }
        glow(ctx, 960, 860, 260, [255, 200, 120], 0.35 * flick);
        ctx.fillStyle = "#24140e"; ctx.fillRect(760, 878, 400, 26); ctx.fillRect(800, 860, 320, 22);
        for (const s of sparks) {
          s.y -= s.v * dt; s.x += Math.sin(t * 2 + s.p) * 0.6;
          if (s.y < 520) { s.y = 860; s.x = 960 + (rand() - 0.5) * 300; }
          ctx.fillStyle = `rgba(255,190,90,${(s.y - 520) / 340})`; ctx.fillRect(s.x, s.y, 3, 3);
        }
        ctx.fillStyle = "#120b09"; ctx.fillRect(0, 960, W, 120);
      },
    };
  })();

  /* ocean horizon with sun or moon */
  scenes["ocean"] = {
    effects: ["grain", "vignette"],
    draw(ctx, t, env) {
      const day = env.day;
      sky(ctx, 0, 0, W, 620, day);
      stars(ctx, t, 1 - day * 1.6, { x: 0, y: 0, w: W, h: 860 });
      const orbY = 480 - day * 300, orbC = day > 0.25 ? [255, 236, 190] : [230, 236, 255];
      glow(ctx, 1340, orbY, 280, orbC, 0.5);
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
    },
  };

  /* night city skyline in the rain */
  scenes["night-city"] = {
    effects: ["rain", "grain", "vignette"],
    draw(ctx, t, env) { CITY.draw(ctx, t, env.day * 0.8); },
  };

  /* slow drifting starfield with a planet */
  scenes["space"] = (() => {
    const deep = Array.from({ length: 500 }, () => ({ x: rand() * W, y: rand() * H, z: 0.2 + rand() * 0.8, p: rand() * 9 }));
    return {
      effects: ["grain"],
      draw(ctx, t) {
        ctx.fillStyle = "#04040b"; ctx.fillRect(0, 0, W, H);
        for (const [x, y, r, c] of [[500, 300, 700, [80, 40, 140]], [1500, 760, 800, [20, 80, 140]], [1100, 200, 500, [140, 40, 90]]]) glow(ctx, x, y, r, c, 0.32);
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
      },
    };
  })();

  const ACCENTS = {
    "study-room": ["#ffb86b", "#1b1206"], "rain-window": ["#8ec5ff", "#06121f"], "fireplace": ["#ff9a52", "#1f0c02"],
    "ocean": ["#6fe0d6", "#03201d"], "night-city": ["#c49bff", "#160827"], "space": ["#ff8fc8", "#2a0619"],
  };

  window.BBScenes = {
    names: Object.keys(scenes),
    get: name => scenes[name] || scenes["study-room"],
    daylight,
    accent: name => ACCENTS[name] || ACCENTS["study-room"],
  };
})();
