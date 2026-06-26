/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        cargo: {
          cloud: '#F5F7FA',
          trust: '#0052CC',
          'trust-hover': '#0747A6',
          'trust-light': '#E6EDF8',
          alert: '#FF5630',
          'alert-light': '#FFEBE6',
          clear: '#36B37E',
          'clear-light': '#E3FCEF',
          warning: '#FF8B00',
          'warning-light': '#FFFAE6',
          deep: '#172B4D',
          mid: '#42526E',
          light: '#97A0AF',
          border: '#DFE1E6',
          surface: '#FFFFFF',
          'navy-50': '#E6EDF8',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
