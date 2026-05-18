const fs = require('fs');
const path = require('path');
const pngToIco = require('png-to-ico');

const base = path.join(__dirname, 'build-resources');
const pngPath = path.join(base, 'icon.png');
const icoPath = path.join(base, 'icon.ico');

if (!fs.existsSync(pngPath)) {
  console.error('Missing', pngPath);
  process.exit(1);
}

pngToIco(pngPath)
  .then((buf) => {
    fs.writeFileSync(icoPath, buf);
    console.log('Wrote', icoPath);
  })
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
