# Stream banner

Top and bottom bars for your YouTube live stream (promo text, logo, promo images or a QR code,
LIVE badge, New York clock, US market open/closed). The middle is fully transparent, so the trading
chart you stream stays visible.

| File | What it is |
|---|---|
| `banner.html` | The overlay you add to OBS |
| `banner-config.js` | Your text, images and colours (the banner reloads it every 5 seconds) |
| `editor.html` | Change everything with a live preview over a sample chart |

No install and no program to run: OBS opens `banner.html` straight from this folder.

## Add it to OBS (once)

1. Open the scene that shows your chart (the `OBS_SCENE` your live bot uses).
2. **Sources → + → Browser**, name it "Banner".
3. Tick **Local file**, **Browse…** and pick `banner.html` in this folder.
4. Width and Height = your OBS canvas size (**Settings → Video → Base (Canvas) Resolution**, e.g.
   1920×1080, or 2560×1080 / 3440×1440 on an ultrawide). Leave the rest as it is.
5. In the Sources list, drag **Banner** to the **top** so it sits above the chart.
6. Right-click **Banner → Transform → Fit to screen** (Ctrl+F) so it fills the whole canvas.

The bars always stretch edge to edge, whatever the screen shape; their height follows the
canvas height (the sizes in the editor are for a 1080-pixel-tall stream).

If the bars cover the chart's price or time labels, fit the chart between them: right-click the chart
source → **Transform → Edit Transform**, set *Position* Y to the top bar height (96 by default) and the
*Bounding box* height to 1080 minus both bars (1080 − 96 − 78 = **906**), with *Bounding box type*
"Scale to inner bounds".

## Change the text, colours or images

1. Double-click `editor.html` (Chrome or Edge works best).
2. Edit: messages (one per line), one-at-a-time or scrolling ticker, bar height, colours, how see-through
   the bars are, the red badge, a logo, promo images, clock and market status. The preview updates as
   you type.
3. Click **Save** and choose `banner-config.js` in this folder (the first time only). The stream shows
   the change within 5 seconds; you don't touch OBS.

**Images:** copy the picture (logo, promo, QR code) into this folder first, then type its file name
(e.g. `logo.png`) in the editor. Several images in "Images (right)" rotate.

You can also edit `banner-config.js` in Notepad; keep the quotes and commas as they are.

The market status follows regular New York hours (pre-market 4:00–9:30, open 9:30–16:00,
after-hours 16:00–20:00, Monday to Friday). It doesn't know exchange holidays.
