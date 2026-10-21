/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#0a0d12', 900: '#0f131a', 850: '#141922', 800: '#1a202b', 700: '#252d3a', 600: '#344052', 500: '#56637a', 400: '#8592a8', 300: '#b4bfd0', 100: '#e6ebf2' },
        up: '#22c55e',
        down: '#ef4444',
        accent: '#3b82f6',
        warn: '#f59e0b',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: { '2xs': ['10px', '14px'] },
    },
  },
  plugins: [],
};
