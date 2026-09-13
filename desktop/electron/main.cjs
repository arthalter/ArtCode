const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');

let window, backend, sequence = 0, exiting = false, quitPending = false;
const pending = new Map();
const methods = new Set(['initialize', 'open', 'input', 'snapshot', 'cancel', 'answer', 'background']);
const emit = (event) => { if (window && !window.isDestroyed()) window.webContents.send('artcode:event', event); };

function startBackend() {
  const root = path.resolve(__dirname, '../..');
  const binary = app.isPackaged ? path.join(process.resourcesPath, 'backend/artcode-server')
    : process.env.ARTCODE_PYTHON || path.join(root, '.venv/bin/python');
  const args = app.isPackaged ? [] : ['-m', 'artcode.desktop_server'];
  const child = spawn(binary, args, {
    cwd: app.isPackaged ? app.getPath('home') : root,
    env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8',
      PATH: [...new Set([...(process.env.PATH || '').split(path.delimiter), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'].filter(Boolean))].join(path.delimiter) },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  backend = child;
  child.stdin.on('error', () => {}); // Pending requests are rejected by write callbacks / process exit.
  // Never forward raw backend stderr to the renderer; errors arrive through the protocol.
  child.stderr.resume();
  const lines = readline.createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    let message;
    try { message = JSON.parse(line); } catch { return; }
    if (message.method === 'event') return emit(message.params);
    const waiting = pending.get(message.id);
    if (!waiting) return;
    pending.delete(message.id);
    clearTimeout(waiting.timer);
    if (message.error) waiting.reject(new Error(message.error.message));
    else waiting.resolve(message.result);
  });
  function failed(reason) {
    if (backend !== child) return;
    backend = null;
    for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error(reason)); }
    pending.clear();
    emit({ kind: 'disconnected', message: reason });
  }
  child.on('error', () => failed('Python 后端无法启动。请检查运行环境或重新打包应用。'));
  child.on('exit', (code) => failed(code === 0 ? '后端已关闭。' : `后端已退出（${code}）。请重新连接。`));
  return child;
}

function request(method, params = {}) {
  if (!backend && method !== 'initialize') return Promise.reject(new Error('后端未连接，请重新连接。'));
  const child = backend || startBackend();
  const id = String(++sequence);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('请求响应超时；请检查状态，不要重复发送任务。'));
    }, 15000);
    pending.set(id, { resolve, reject, timer });
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n', (error) => {
      if (error && pending.delete(id)) { clearTimeout(timer); reject(new Error('后端连接已断开。')); }
    });
  });
}

async function stopBackend() {
  const child = backend;
  if (!child) return;
  const ended = new Promise((resolve) => child.once('exit', resolve));
  await request('close').catch(() => {});
  // Keep the app alive until Python has reaped its tools and saved the Session.
  await ended;
}

app.whenReady().then(() => {
  window = new BrowserWindow({
    width: 1280, height: 860, minWidth: 900, minHeight: 650,
    title: 'ArtCode', backgroundColor: '#f5f4f0',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  const trusted = (event) => event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame;
  ipcMain.handle('artcode:request', (event, method, params) => {
    if (!trusted(event) || !methods.has(method)) throw new Error('无效的桌面操作。');
    return request(method, params);
  });
  ipcMain.handle('artcode:choose', async (event, kind) => {
    if (!trusted(event) || !['workspace', 'config'].includes(kind)) throw new Error('无效的选择器。');
    const result = await dialog.showOpenDialog(window, {
      properties: [kind === 'workspace' ? 'openDirectory' : 'openFile'],
      ...(kind === 'config' ? { filters: [{ name: '配置文件', extensions: ['yml', 'yaml'] }] } : {}),
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle('artcode:restart', async (event) => {
    if (!trusted(event)) throw new Error('无效的桌面操作。');
    await stopBackend();
    return request('initialize', { protocol: 'artcode-desktop/0.1' });
  });
  window.loadFile(path.join(__dirname, '../dist/index.html'));
});

app.on('before-quit', (event) => {
  if (exiting || !backend) return;
  event.preventDefault();
  if (quitPending) return;
  quitPending = true;
  dialog.showMessageBox(window, { type: 'question', buttons: ['返回应用', '退出'], defaultId: 0,
    title: '退出 ArtCode', message: '退出会取消当前执行和后台任务，保留已提交会话与文件成果。' })
    .then(async ({ response }) => {
      if (response === 0) { quitPending = false; return; }
      emit({ kind: 'closing' });
      await stopBackend();
      exiting = true;
      app.quit();
    }).catch(() => { quitPending = false; });
});
app.on('browser-window-created', (_, win) => win.on('close', (event) => {
  if (!exiting && backend) { event.preventDefault(); app.quit(); }
}));
app.on('window-all-closed', () => app.quit());
