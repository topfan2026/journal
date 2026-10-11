/* Draws the background each frame and the realism effects over it.

   Background: the profile's photo/video (backgrounds/ folder, separate night file optional), or a
   built-in scene from scenes.js when there is none. Photos drift slowly (a gentle camera move)
   so they feel alive. Effects come from the profile, else the scene's defaults. */
(function () {
  "use strict";
  const W = 1920, H = 1080;
  const VIDEO = /\.(mp4|webm|m4v|mov)$/i;

  function start(canvas, getConfig, fps) {
    const ctx = canvas.getContext("2d");
    const base = document.createElement("canvas"); base.width = W; base.height = H;
    const bctx = base.getContext("2d");
    const media = {};                 // url -> {el, ready}
    let effects = [], effectsKey = "", last = 0, lastDraw = 0;
    const frame = 1000 / (fps || 30);

    function load(url) {
      if (!url) return null;
      if (media[url]) return media[url];
      const m = { el: null, ready: false, video: VIDEO.test(url) };
      if (m.video) {
        const v = document.createElement("video");
        Object.assign(v, { muted: true, loop: true, playsInline: true, autoplay: true, preload: "auto", src: url });
        v.addEventListener("canplay", () => { m.ready = true; v.play().catch(() => {}); });
        m.el = v;
      } else {
        const img = new Image();
        img.onload = () => { m.ready = true; };
        img.src = url;
        m.el = img;
      }
      media[url] = m;
      return m;
    }

    function pickMedia(cfg) {
      const bg = cfg.background || {};
      const h = new Date().getHours();
      const night = h >= 19 || h < 6;
      const url = (night && bg.night) || bg.day || bg.night;
      const m = load(url);
      return m && m.ready ? m : null;
    }

    function cover(el, w, h, t, still) {
      const iw = el.videoWidth || el.naturalWidth, ih = el.videoHeight || el.naturalHeight;
      if (!iw || !ih) return;
      let k = Math.max(W / iw, H / ih);
      let dx = 0, dy = 0;
      if (still) {                    // slow drift + zoom on photos
        k *= 1.05 + 0.035 * Math.sin(t / 47);
        dx = Math.sin(t / 61) * 24; dy = Math.cos(t / 73) * 14;
      }
      const dw = iw * k, dh = ih * k;
      bctx.drawImage(el, (W - dw) / 2 + dx, (H - dh) / 2 + dy, dw, dh);
    }

    function loop(now) {
      requestAnimationFrame(loop);
      if (now - lastDraw < frame - 2) return;
      lastDraw = now;
      const t = now / 1000, dt = Math.min(0.1, t - (last || t)); last = t;
      const cfg = getConfig();
      const scene = BBScenes.get(cfg.scene);
      const env = { day: BBScenes.daylight(new Date()) };
      const m = pickMedia(cfg);

      if (m) cover(m.el, W, H, t, !m.video);
      else scene.draw(bctx, t, env);

      const names = (cfg.effects && cfg.effects.length ? cfg.effects : m ? ["grain", "vignette"] : scene.effects) || [];
      const area = m ? null : scene.glass || null;
      const key = names.join(",") + "|" + JSON.stringify(area) + "|" + (m ? "media" : cfg.scene);
      if (key !== effectsKey) {
        effectsKey = key;
        effects = BBEffects.ORDER.filter(n => names.includes(n)).map(n => ({ n, fx: BBEffects.create(n, n === "rain-glass" ? area : null) }));
      }

      ctx.drawImage(base, 0, 0);
      let fgDone = false;
      for (const { n, fx } of effects) {
        if (!fx) continue;
        if (n !== "rain-glass" && !fgDone) { if (!m && scene.fg) scene.fg(ctx, t, env); fgDone = true; }
        fx.update(dt, t);
        fx.render(ctx, base, t);
      }
      if (!fgDone && !m && scene.fg) scene.fg(ctx, t, env);
    }
    requestAnimationFrame(loop);
  }

  window.BBRender = { start };
})();
