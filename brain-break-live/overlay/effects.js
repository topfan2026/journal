/* Realism layers drawn over the background (a photo, a video or a built-in scene).

   rain-glass  water on a window: fogged glass, drops that act as lenses (each shows the scene
               behind it upside down), big drops sliding down and wiping clear trails that fog
               over again
   rain        falling rain in three depth layers
   snow        drifting snow
   dust        dust motes floating in the light
   lightning   an occasional flash (pairs well with rain)
   grain       film grain
   vignette    darker corners

   Every effect is created once per area and then gets update(dt, t) + render(ctx, base, t).
   `base` is the sharp background canvas (1920x1080). */
(function () {
  "use strict";
  const W = 1920, H = 1080;
  const rnd = Math.random;
  const canvas = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
  const FILTER = "filter" in canvas(1, 1).getContext("2d");

  // ---------------------------------------------------------------- shared sprites
  const DROP = (() => {          // shading for a lens drop: dark rim, bright glint top-left, caustic bottom
    const c = canvas(128, 128), g = c.getContext("2d");
    let gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, "rgba(255,255,255,0)"); gr.addColorStop(0.62, "rgba(0,0,0,0.04)");
    gr.addColorStop(0.88, "rgba(0,0,0,0.38)"); gr.addColorStop(1, "rgba(0,0,0,0.12)");
    g.fillStyle = gr; g.beginPath(); g.arc(64, 64, 64, 0, 7); g.fill();
    gr = g.createRadialGradient(44, 38, 0, 44, 38, 20);
    gr.addColorStop(0, "rgba(255,255,255,0.75)"); gr.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
    g.strokeStyle = "rgba(255,255,255,0.22)"; g.lineWidth = 5;
    g.beginPath(); g.arc(64, 64, 50, 0.35 * Math.PI, 0.75 * Math.PI); g.stroke();
    return c;
  })();
  const SPECK = (() => {         // a tiny bead of water
    const c = canvas(16, 16), g = c.getContext("2d");
    const gr = g.createRadialGradient(8, 8, 0, 8, 8, 8);
    gr.addColorStop(0, "rgba(255,255,255,0.10)"); gr.addColorStop(0.7, "rgba(0,0,0,0.22)"); gr.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = gr; g.fillRect(0, 0, 16, 16);
    g.fillStyle = "rgba(255,255,255,0.55)"; g.beginPath(); g.arc(6, 6, 1.6, 0, 7); g.fill();
    return c;
  })();
  const FLAKE = (() => {
    const c = canvas(32, 32), g = c.getContext("2d");
    const gr = g.createRadialGradient(16, 16, 0, 16, 16, 16);
    gr.addColorStop(0, "rgba(255,255,255,0.95)"); gr.addColorStop(0.4, "rgba(255,255,255,0.5)"); gr.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = gr; g.fillRect(0, 0, 32, 32);
    return c;
  })();
  const MOTE = (() => {
    const c = canvas(32, 32), g = c.getContext("2d");
    const gr = g.createRadialGradient(16, 16, 0, 16, 16, 16);
    gr.addColorStop(0, "rgba(255,236,200,0.9)"); gr.addColorStop(0.3, "rgba(255,220,170,0.35)"); gr.addColorStop(1, "rgba(255,220,170,0)");
    g.fillStyle = gr; g.fillRect(0, 0, 32, 32);
    return c;
  })();

  // ---------------------------------------------------------------- rain on glass
  function rainGlass(area) {
    const { x: ax, y: ay, w: aw, h: ah } = area;
    const scale = (aw * ah) / (W * H);
    const BIG = Math.round(16 + 70 * scale), SMALL = Math.round(250 + 1300 * scale);
    const mask = canvas(aw, ah), mctx = mask.getContext("2d");
    const tmp = canvas(aw, ah), tctx = tmp.getContext("2d");
    const fog = canvas(W / 2, H / 2), fctx = fog.getContext("2d");
    const tiny = FILTER ? null : canvas(W / 16, H / 16);
    const big = [], small = [];
    const spawnBig = (top) => ({
      x: ax + rnd() * aw, y: top ? ay - 10 : ay + rnd() * ah, r: 2.5 + Math.pow(rnd(), 2.2) * 10,
      vy: 0, moving: false, wob: rnd() * 7, px: 0, py: 0,
    });
    const spawnSmall = (x, y, r) => ({ x: x ?? ax + rnd() * aw, y: y ?? ay + rnd() * ah, r: r ?? 0.7 + Math.pow(rnd(), 2) * 2.4 });
    for (let i = 0; i < BIG; i++) big.push(spawnBig(false));
    for (let i = 0; i < SMALL; i++) small.push(spawnSmall());

    function update(dt, t) {
      // new rain landing on the glass
      for (let n = rnd() < (60 * scale + 10) * dt ? 1 + (rnd() * 3 | 0) : 0; n > 0; n--) {
        small[(rnd() * small.length) | 0] = spawnSmall();
      }
      if (big.length < BIG && rnd() < dt * 3) big.push(spawnBig(rnd() < 0.3));
      // the glass fogs over again behind sliding drops
      mctx.globalCompositeOperation = "destination-out";
      mctx.fillStyle = `rgba(0,0,0,${Math.min(1, dt * 0.09)})`;
      mctx.fillRect(0, 0, aw, ah);
      mctx.globalCompositeOperation = "source-over";
      mctx.strokeStyle = "#fff"; mctx.lineCap = "round";

      for (let i = big.length - 1; i >= 0; i--) {
        const b = big[i];
        if (!b.moving) {
          if (b.r > 5.5 && rnd() < dt * 0.05 * (b.r / 8)) { b.moving = true; b.vy = 20; }
          continue;
        }
        b.px = b.x; b.py = b.y;
        b.vy = Math.min(b.vy + 260 * dt * (b.r / 10), 60 + b.r * 22);
        if (rnd() < dt * 0.7) b.vy *= 0.05;                       // drops stall and lurch
        b.y += b.vy * dt;
        b.x += Math.sin(t * 2.3 + b.wob) * 0.35 * (b.r / 8);
        mctx.lineWidth = b.r * 1.5;
        mctx.beginPath(); mctx.moveTo(b.px - ax, b.py - ay); mctx.lineTo(b.x - ax, b.y - ay); mctx.stroke();
        for (let j = small.length - 1; j >= 0; j--) {              // swallow the beads in its path
          const s = small[j], dx = s.x - b.x, dy = s.y - b.y;
          if (dx * dx + dy * dy < b.r * b.r * 1.4) { small[j] = spawnSmall(); b.r = Math.min(15, b.r + 0.04); }
        }
        if (rnd() < dt * 6) small[(rnd() * small.length) | 0] = spawnSmall(b.x + (rnd() - 0.5) * b.r, b.y - b.r * 1.6, b.r * (0.12 + rnd() * 0.12));
        if (b.y - b.r > ay + ah) big.splice(i, 1);
      }
    }

    function render(ctx, base) {
      // fogged glass: the scene blurred and slightly milky
      if (FILTER) {
        fctx.filter = "blur(7px)";
        fctx.drawImage(base, 0, 0, W / 2, H / 2);
        fctx.filter = "none";
      } else {
        const tc = tiny.getContext("2d");
        tc.drawImage(base, 0, 0, tiny.width, tiny.height);
        fctx.imageSmoothingQuality = "high";
        fctx.drawImage(tiny, 0, 0, W / 2, H / 2);
      }
      ctx.drawImage(fog, ax / 2, ay / 2, aw / 2, ah / 2, ax, ay, aw, ah);
      ctx.fillStyle = "rgba(180,196,220,0.07)";
      ctx.fillRect(ax, ay, aw, ah);
      // clear trails left by sliding drops
      tctx.globalCompositeOperation = "copy";
      tctx.drawImage(base, ax, ay, aw, ah, 0, 0, aw, ah);
      tctx.globalCompositeOperation = "destination-in";
      tctx.drawImage(mask, 0, 0);
      tctx.globalCompositeOperation = "source-over";
      ctx.drawImage(tmp, ax, ay);
      // beads
      for (const s of small) ctx.drawImage(SPECK, s.x - s.r, s.y - s.r, s.r * 2, s.r * 2);
      // lens drops: each shows a wide, upside-down view of the scene behind it
      for (const b of big) {
        if (b.y + b.r < ay || b.y - b.r > ay + ah) continue;
        const rx = b.r, ry = b.r * (b.moving ? 1.3 : 1.08);
        const k = 7, sw = Math.min(W, rx * 2 * k), sh = Math.min(H, ry * 2 * k);
        const sx = Math.max(0, Math.min(W - sw, b.x - sw / 2)), sy = Math.max(0, Math.min(H - sh, b.y - sh / 2));
        ctx.save();
        ctx.beginPath(); ctx.ellipse(b.x, b.y, rx, ry, 0, 0, 7); ctx.clip();
        ctx.translate(b.x, b.y); ctx.scale(-1, -1);
        ctx.drawImage(base, sx, sy, sw, sh, -rx, -ry, rx * 2, ry * 2);
        ctx.restore();
        ctx.drawImage(DROP, b.x - rx, b.y - ry, rx * 2, ry * 2);
      }
    }
    return { update, render };
  }

  // ---------------------------------------------------------------- falling rain
  function rain() {
    const layers = [
      { n: 260, v: 1500, len: 34, w: 1.6, a: 0.22 },
      { n: 380, v: 1150, len: 24, w: 1.1, a: 0.16 },
      { n: 520, v: 850, len: 14, w: 0.8, a: 0.11 },
    ].map(L => ({ ...L, d: Array.from({ length: L.n }, () => ({ x: rnd() * W * 1.1, y: rnd() * H })) }));
    const wind = 0.12;
    return {
      update(dt) {
        for (const L of layers) for (const d of L.d) {
          d.y += L.v * dt; d.x -= L.v * dt * wind;
          if (d.y > H) { d.y = -L.len - rnd() * 100; d.x = rnd() * W * 1.15; }
        }
      },
      render(ctx) {
        for (const L of layers) {
          ctx.strokeStyle = `rgba(210,222,240,${L.a})`; ctx.lineWidth = L.w; ctx.beginPath();
          for (const d of L.d) { ctx.moveTo(d.x, d.y); ctx.lineTo(d.x + L.len * wind, d.y - L.len); }
          ctx.stroke();
        }
      },
    };
  }

  // ---------------------------------------------------------------- snow
  function snow() {
    const flakes = Array.from({ length: 420 }, () => ({ x: rnd() * W, y: rnd() * H, z: 0.25 + rnd() * 0.75, p: rnd() * 7 }));
    return {
      update(dt, t) {
        for (const f of flakes) {
          f.y += (25 + 70 * f.z) * dt; f.x += (Math.sin(t * 0.6 + f.p) * 18 + 10) * f.z * dt;
          if (f.y > H + 10) { f.y = -10; f.x = rnd() * W; }
          if (f.x > W + 10) f.x = -10;
        }
      },
      render(ctx) {
        for (const f of flakes) {
          const s = 3 + f.z * 9;
          ctx.globalAlpha = 0.35 + f.z * 0.6;
          ctx.drawImage(FLAKE, f.x - s / 2, f.y - s / 2, s, s);
        }
        ctx.globalAlpha = 1;
      },
    };
  }

  // ---------------------------------------------------------------- dust in the light
  function dust() {
    const motes = Array.from({ length: 70 }, () => ({ x: rnd() * W, y: rnd() * H, vx: 0, vy: 0, s: 2 + rnd() * 5, p: rnd() * 7 }));
    return {
      update(dt) {
        for (const m of motes) {
          m.vx += (rnd() - 0.5) * 12 * dt; m.vy += (rnd() - 0.52) * 12 * dt;
          m.vx *= 0.99; m.vy *= 0.99;
          m.x = (m.x + m.vx * dt + W) % W; m.y = (m.y + m.vy * dt + H) % H;
        }
      },
      render(ctx, base, t) {
        ctx.globalCompositeOperation = "screen";
        for (const m of motes) {
          ctx.globalAlpha = 0.15 + 0.25 * (0.5 + 0.5 * Math.sin(t * 0.8 + m.p));
          ctx.drawImage(MOTE, m.x - m.s, m.y - m.s, m.s * 2, m.s * 2);
        }
        ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
      },
    };
  }

  // ---------------------------------------------------------------- lightning
  function lightning() {
    let next = 20 + rnd() * 60, flash = 0, t0 = 0;
    return {
      update(dt, t) {
        if (t > next) { flash = 1; t0 = t; next = t + 35 + rnd() * 110; }
        if (flash) { const e = t - t0; flash = e > 0.9 ? 0 : (e < 0.08 ? 1 : e < 0.16 ? 0.25 : e < 0.24 ? 0.85 : Math.max(0, 0.85 - (e - 0.24) * 1.3)); }
      },
      render(ctx) {
        if (!flash) return;
        ctx.fillStyle = `rgba(215,225,255,${flash * 0.35})`;
        ctx.fillRect(0, 0, W, H);
      },
    };
  }

  // ---------------------------------------------------------------- grain + vignette
  function grain() {
    const tiles = Array.from({ length: 4 }, () => {
      const c = canvas(256, 256), g = c.getContext("2d"), img = g.createImageData(256, 256);
      for (let i = 0; i < img.data.length; i += 4) {
        const v = 128 + (rnd() - 0.5) * 255;
        img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255;
      }
      g.putImageData(img, 0, 0);
      return c;
    });
    let frame = 0;
    return {
      update() { frame++; },
      render(ctx) {
        const tile = tiles[frame % tiles.length];
        const pat = ctx.createPattern(tile, "repeat");
        ctx.save();
        ctx.globalCompositeOperation = "overlay"; ctx.globalAlpha = 0.06;
        ctx.translate(-(rnd() * 256) | 0, -(rnd() * 256) | 0);
        ctx.fillStyle = pat; ctx.fillRect(0, 0, W + 256, H + 256);
        ctx.restore();
      },
    };
  }

  function vignette() {
    const c = canvas(W, H), g = c.getContext("2d");
    const gr = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 1.05);
    gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(1, "rgba(0,0,0,0.55)");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    return { update() {}, render(ctx) { ctx.drawImage(c, 0, 0); } };
  }

  const FACTORIES = { "rain-glass": rainGlass, rain, snow, dust, lightning, grain, vignette };
  // drawing order: glass first (it replaces what is behind it), then things in the room, then the lens
  const ORDER = ["rain-glass", "rain", "snow", "dust", "lightning", "grain", "vignette"];

  window.BBEffects = {
    names: ORDER,
    ORDER,
    create(name, area) { return FACTORIES[name] ? FACTORIES[name](area || { x: 0, y: 0, w: W, h: H }) : null; },
  };
})();
