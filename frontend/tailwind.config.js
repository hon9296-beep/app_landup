/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#6366f1', hover: '#4f46e5' },
        accent:  '#10b981',
        danger:  '#ef4444',
        border:  'rgba(148,163,184,0.2)',
        text: {
          main:  '#f8fafc',
          muted: '#94a3b8',
        },
      },
    },
  },
  plugins: [],
}
