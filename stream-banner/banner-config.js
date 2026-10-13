// Banner settings. Edit with editor.html (easiest) or in Notepad, then save.
// The banner in OBS reloads this file every second, so changes appear by themselves.
// Images (logo, promo pictures) must be in this same folder; write just the file name.
window.BANNER = {
  "font": "'Segoe UI', Inter, Arial, sans-serif",
  "top": {
    "show": true,
    "height": 96,
    "background": "#0b1120",
    "opacity": 0.88,
    "accent": "#22c55e",
    "textColor": "#ffffff",
    "textSize": 34,
    "logo": "",
    "badge": "LIVE",
    "mode": "rotate",
    "seconds": 8,
    "speed": 110,
    "messages": [
      "AI Stock Scanner · live every trading morning",
      "Pre-market movers, updated in real time",
      "Try the scanner free at aialgopro.com"
    ],
    "images": [],
    "clock": true,
    "clockZone": "America/New_York",
    "clockLabel": "NY",
    "marketStatus": true
  },
  "bottom": {
    "show": true,
    "height": 78,
    "background": "#0b1120",
    "opacity": 0.88,
    "accent": "#22c55e",
    "textColor": "#e5e7eb",
    "textSize": 30,
    "logo": "",
    "badge": "",
    "mode": "scroll",
    "seconds": 8,
    "speed": 110,
    "messages": [
      "👍 Like & subscribe for the scanner every morning",
      "🔔 Turn on notifications so you never miss the open",
      "🌐 aialgopro.com",
      "Not financial advice. For education only."
    ],
    "images": [],
    "clock": false,
    "clockZone": "America/New_York",
    "clockLabel": "NY",
    "marketStatus": false
  },
  "shimmer": true,
  "callouts": [
    {
      "text": "🔔 Subscribe for the scanner every morning!",
      "position": "top-right", "animation": "slide", "look": "box", "effect": "sparkles",
      "color": "#22c55e", "size": 44, "duration": 8, "every": 10
    },
    {
      "text": "🚀 BREAKOUT!",
      "position": "center", "animation": "pop", "look": "neon", "effect": "rockets",
      "color": "#22c55e", "size": 110, "duration": 5, "every": 0
    },
    {
      "text": "NEW HIGH OF DAY 📈",
      "position": "center", "animation": "drop", "look": "ribbon", "effect": "confetti",
      "color": "#facc15", "size": 84, "duration": 5, "every": 0
    }
  ],
  "covers": []
};
