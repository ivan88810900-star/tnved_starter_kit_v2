const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

const outPng = path.join(__dirname, 'build-resources', 'icon.png');
fs.mkdirSync(path.dirname(outPng), { recursive: true });

// Бренд-палитра CustomsClear
const colors = {
  bg1: '#071124',
  bg2: '#0b1f3f',
  shield: '#e2ecff',
  shieldGlow: '#8ec5ff',
  docFill: '#102848',
  docStroke: '#7ed0ff',
  lines: '#a7b9d6',
  check: '#1dd17a',
};

const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${colors.bg1}"/>
      <stop offset="100%" stop-color="${colors.bg2}"/>
    </linearGradient>
    <filter id="softGlow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="8" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
  <rect x="0" y="0" width="1024" height="1024" rx="220" fill="url(#bg)"/>
  <rect x="26" y="26" width="972" height="972" rx="200" fill="none" stroke="#17325a" stroke-width="10"/>

  <!-- shield -->
  <path d="M512 185
           C620 240 700 260 800 270
           V515
           C800 675 690 800 512 874
           C334 800 224 675 224 515
           V270
           C324 260 404 240 512 185 Z"
        fill="none" stroke="${colors.shield}" stroke-width="34" stroke-linejoin="round"/>
  <path d="M512 185
           C620 240 700 260 800 270
           V515
           C800 675 690 800 512 874
           C334 800 224 675 224 515
           V270
           C324 260 404 240 512 185 Z"
        fill="none" stroke="${colors.shieldGlow}" stroke-opacity="0.45" stroke-width="10" filter="url(#softGlow)"/>

  <!-- document -->
  <path d="M365 340
           H585
           L690 445
           V700
           H365 Z"
        fill="${colors.docFill}" stroke="${colors.docStroke}" stroke-width="22" stroke-linejoin="round"/>
  <path d="M585 340 V445 H690" fill="none" stroke="${colors.docStroke}" stroke-width="22" stroke-linejoin="round"/>

  <!-- lines -->
  <path d="M410 505 H630" stroke="${colors.lines}" stroke-width="20" stroke-linecap="round"/>
  <path d="M410 565 H590" stroke="${colors.lines}" stroke-width="20" stroke-linecap="round"/>

  <!-- checkmark -->
  <path d="M418 660 L480 720 L625 575" fill="none" stroke="${colors.check}" stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

sharp(Buffer.from(svg))
  .png({ compressionLevel: 9 })
  .resize(1024, 1024)
  .toFile(outPng)
  .then(() => {
    console.log('Wrote', outPng);
  })
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
