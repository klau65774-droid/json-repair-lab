/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        lab: {
          bg: '#0A0D12',
          panel: '#11161F',
          raised: '#151C27',
          border: '#1E2736',
          sapphire: '#3B82F6',
          emerald: '#10B981',
          amber: '#F59E0B',
          cyan: '#06B6D4',
          rose: '#F43F5E',
          text: '#E5EAF2',
          muted: '#7F8B9D',
          faint: '#4B586B',
        },
      },
      fontFamily: {
        sans: ['Inter', 'IBM Plex Sans', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 0 rgba(255,255,255,0.015)',
      },
    },
  },
  plugins: [],
};
