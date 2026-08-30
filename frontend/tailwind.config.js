/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        paper: '#FFFFFF',
        'paper-alt': '#F6F7F9',
        panel: '#FCFCFD',
        line: '#E4E7EC',
        'line-strong': '#CDD3DB',
        ink: '#0C1526',
        'ink-2': '#4C5768',
        'ink-3': '#8A93A3',
        brand: '#1447E6',
        'brand-ink': '#0E33AD',
        'brand-tint': '#EEF2FE',
        pos: '#0F8F5F',
        'pos-tint': '#E7F5EF',
        neg: '#C13333',
        'neg-tint': '#FBEBEB',
      },
      fontFamily: {
        serif: ['var(--font-newsreader)', 'Newsreader', 'serif'],
        sans: ['var(--font-inter)', 'Inter', 'sans-serif'],
        mono: ['var(--font-mono)', 'IBM Plex Mono', 'monospace'],
      },
      borderRadius: {
        s: '6px',
        m: '10px',
        l: '16px',
      },
      transitionTimingFunction: {
        ketsa: 'cubic-bezier(.2,.7,.2,1)',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '.3' },
        },
        'ticker-scroll': {
          from: { transform: 'translateX(0)' },
          to: { transform: 'translateX(-50%)' },
        },
        'reveal-up': {
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-ring': {
          '0%': { opacity: '.55', transform: 'scale(1)' },
          '100%': { opacity: '0', transform: 'scale(3.4)' },
        },
      },
      animation: {
        'pulse-dot': 'pulse-dot 2s infinite',
        'pulse-dot-fast': 'pulse-dot 1.6s infinite',
        'pulse-ring': 'pulse-ring 2.2s ease-out infinite',
        'ticker-scroll': 'ticker-scroll 42s linear infinite',
      },
    },
  },
  plugins: [],
};
