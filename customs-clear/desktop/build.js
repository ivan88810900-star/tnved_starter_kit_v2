#!/usr/bin/env node
/**
 * Сборка десктоп-приложения CustomsClear для macOS и Windows.
 * Использование:
 *   node build.js [mac|win] [--frontend-only]
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const frontendDir = path.join(root, 'frontend');
const backendDir = path.join(root, 'backend');
const staticDir = path.join(backendDir, 'static');
const desktopDir = __dirname;
const buildResourcesDir = path.join(desktopDir, 'build-resources');

const args = process.argv.slice(2);
const platformArg = args.find((a) => a === 'mac' || a === 'win');
const platform = platformArg || (process.platform === 'darwin' ? 'mac' : 'win');
const frontendOnly = args.includes('--frontend-only');

console.log('=== CustomsClear Desktop Build ===');
console.log('Platform:', platform);
console.log('Frontend only:', frontendOnly ? 'yes' : 'no');

const cleanNpmEnv = {
  ...process.env,
};
delete cleanNpmEnv.npm_config_devdir;
delete cleanNpmEnv.NPM_CONFIG_DEVDIR;

const run = (cmd, cwd) =>
  execSync(cmd, {
    cwd,
    stdio: 'inherit',
    env: cleanNpmEnv,
  });

// 0. Иконки (чтобы не было default Electron icon)
console.log('\n0. Generating app icons...');
if (!fs.existsSync(buildResourcesDir)) fs.mkdirSync(buildResourcesDir, { recursive: true });
run('node scripts-generate-icon.js', desktopDir);
run('node scripts-generate-ico.js', desktopDir);
if (process.platform === 'darwin') {
  const icns = path.join(buildResourcesDir, 'icon.icns');
  if (!fs.existsSync(icns)) {
    const iconset = path.join(buildResourcesDir, 'icon.iconset');
    if (fs.existsSync(iconset)) fs.rmSync(iconset, { recursive: true, force: true });
    fs.mkdirSync(iconset, { recursive: true });
    const png = path.join(buildResourcesDir, 'icon.png');
    // iconutil требует набор размеров
    for (const s of [16, 32, 64, 128, 256, 512]) {
      run(`sips -z ${s} ${s} "${png}" --out "${path.join(iconset, `icon_${s}x${s}.png`)}" >/dev/null`, desktopDir);
      const s2 = s * 2;
      run(`sips -z ${s2} ${s2} "${png}" --out "${path.join(iconset, `icon_${s}x${s}@2x.png`)}" >/dev/null`, desktopDir);
    }
    run(`iconutil -c icns "${iconset}" -o "${icns}"`, desktopDir);
  }
}

// 1. Сборка фронтенда
console.log('\n1. Building frontend...');
run('npm run build', frontendDir);

// 2. Копирование статики в backend/static
const distDir = path.join(frontendDir, 'dist');
if (!fs.existsSync(staticDir)) fs.mkdirSync(staticDir, { recursive: true });
const copyDir = (src, dest) => {
  if (!fs.existsSync(dest)) fs.mkdirSync(dest, { recursive: true });
  for (const f of fs.readdirSync(src)) {
    const s = path.join(src, f);
    const d = path.join(dest, f);
    if (fs.statSync(s).isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
};
console.log('2. Copying static files...');
if (fs.existsSync(path.join(distDir, 'assets'))) {
  copyDir(path.join(distDir, 'assets'), path.join(staticDir, 'assets'));
}
fs.copyFileSync(path.join(distDir, 'index.html'), path.join(staticDir, 'index.html'));
if (fs.existsSync(path.join(distDir, 'favicon.ico'))) {
  fs.copyFileSync(path.join(distDir, 'favicon.ico'), path.join(staticDir, 'favicon.ico'));
}

const targetBackend = path.join(desktopDir, 'backend');
if (!fs.existsSync(targetBackend)) fs.mkdirSync(targetBackend, { recursive: true });
if (!frontendOnly) {
  // 3. PyInstaller backend
  console.log('3. Building backend with PyInstaller...');
  const venvPython = path.join(root, '..', '.venv', 'bin', 'python');
  const python = fs.existsSync(venvPython) ? venvPython : 'python3';
  execSync(`${python} -m pip install pyinstaller -q`, { stdio: 'inherit' });
  execSync(`${python} -m PyInstaller customs-clear.spec --noconfirm --clean`, {
    cwd: backendDir,
    stdio: 'inherit',
  });

  // 4. Копирование backend в desktop/backend
  const exeName = platform === 'win' ? 'customs-clear-server.exe' : 'customs-clear-server';
  const srcExe = path.join(backendDir, 'dist', exeName);
  if (fs.existsSync(srcExe)) {
    fs.copyFileSync(srcExe, path.join(targetBackend, exeName));
    console.log('   Backend copied to desktop/backend');
  } else {
    // Важно: Windows-бинарник backend нельзя собрать на macOS/Linux без кросс-компиляции.
    if (platform === 'win') {
      throw new Error(
        `PyInstaller output not found at ${srcExe}. ` +
          'Соберите backend на Windows: запустите build.js win на Windows-машине или используйте --frontend-only.'
      );
    }
    console.warn('   PyInstaller output not found at', srcExe);
  }
} else {
  // Для frontend-only чистим backend-папку, чтобы не упаковать бинарник не той платформы.
  console.log('3. Skipping backend build (frontend-only mode)...');
  for (const name of fs.readdirSync(targetBackend)) {
    fs.rmSync(path.join(targetBackend, name), { recursive: true, force: true });
  }
}

// 5. Electron build
console.log('4. Building Electron app...');
run('npm install', desktopDir);
run(`npx electron-builder --${platform === 'mac' ? 'mac' : 'win'}`, desktopDir);

console.log('\n=== Build complete ===');
console.log('Output: desktop/dist/');
