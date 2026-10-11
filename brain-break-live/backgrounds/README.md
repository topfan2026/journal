# Backgrounds

Put a photo or a looping video here and name it in a profile to replace the built-in drawn scene:

```json
"background": "cozy-desk.mp4",
"background_night": "cozy-desk-night.mp4",
"effects": ["rain-glass", "dust", "grain", "vignette"]
```

- Formats: `.jpg` `.png` `.webp` (photos drift slowly so they feel alive) or `.mp4` `.webm` (looped, muted).
  If an `.mp4` stays black in OBS, convert it to `.webm`.
- `background_night` (optional) is used from 19:00 to 06:00.
- 1920x1080 or larger looks best. Keep videos short loops (10-60 s) so they stay small.
- Effects: `rain-glass` (rain running down a window, very realistic over a city or street at
  night), `rain`, `snow`, `dust`, `lightning`, `grain`, `vignette`. Leave `effects` out to get
  `grain` + `vignette`.

Where to get footage you may use on a monetised YouTube stream: Pexels and Pixabay (free licences
that allow this; read the licence page), paid stock sites, footage you film yourself, or art you
commission or generate on a plan that grants commercial use. Don't use clips from films, other
streamers or random wallpapers.

Files in this folder are not committed to git.
