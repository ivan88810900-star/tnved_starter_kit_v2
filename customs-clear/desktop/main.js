const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');

const API_PORT = 8001;
const API_URL = `http://127.0.0.1:${API_PORT}`;

let backendProcess = null;

function getBackendPath() {
  const isDev = !app.isPackaged;
  if (isDev) {
    return path.join(__dirname, '..', 'backend', 'customs-clear-server');
  }
  const resources = process.resourcesPath;
  const backendDir = path.join(resources, 'backend');
  const isWin = process.platform === 'win32';
  const exe = isWin ? 'customs-clear-server.exe' : 'customs-clear-server';
  return path.join(backendDir, exe);
}

function waitForServer(maxAttempts = 120) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      http.get(`${API_URL}/api/health`, (res) => {
        if (res.statusCode === 200) resolve();
        else if (++attempts < maxAttempts) setTimeout(check, 500);
        else reject(new Error('Backend не запустился'));
      }).on('error', () => {
        if (++attempts < maxAttempts) setTimeout(check, 500);
        else reject(new Error('Backend не запустился'));
      });
    };
    check();
  });
}

function startBackend() {
  const backendPath = getBackendPath();
  if (!fs.existsSync(backendPath)) {
    console.error('Backend не найден:', backendPath);
    return null;
  }
  const backendDir = path.dirname(backendPath);
  // Всегда включаем проверку TLS-сертификатов для внешних HTTPS-запросов backend.
  const env = { ...process.env, PERMITS_VERIFY_SSL: 'true' };
  backendProcess = spawn(backendPath, [], { cwd: backendDir, env });
  backendProcess.stdout?.on('data', (d) => process.stdout.write(d.toString()));
  backendProcess.stderr?.on('data', (d) => process.stderr.write(d.toString()));
  backendProcess.on('error', (err) => console.error('Backend error:', err));
  backendProcess.on('exit', (code) => console.log('Backend exit:', code));
  return backendProcess;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
    title: 'CustomsClear',
  });
  win.loadURL(API_URL);
  win.on('closed', () => {
    if (backendProcess) {
      backendProcess.kill();
      backendProcess = null;
    }
  });
}

app.whenReady().then(async () => {
  const backendPath = getBackendPath();
  if (fs.existsSync(backendPath)) {
    startBackend();
    try {
      await waitForServer();
    } catch (e) {
      console.error(e);
    }
  } else {
    // Режим разработки: backend не собран — пробуем подключиться к уже запущенному
    try {
      await waitForServer(10);
    } catch {
      console.log('Backend не найден. Запустите: cd backend && uvicorn app.main:app --port 8001');
    }
  }
  createWindow();
});

app.on('window-all-closed', () => {
  if (backendProcess) backendProcess.kill();
  app.quit();
});
