// Desktop shell: runs the IBKR bridge and serves the built UI from one local port,
// then opens it in a native window. Nothing listens beyond 127.0.0.1.
import { app, BrowserWindow, Menu, shell } from 'electron';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from '../server/index.js';
import { checkForUpdatesManually, initUpdater } from './updater.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.join(here, '..', 'dist');

// The IBKR gateway login page uses a self-signed cert; let the user open it in their browser.
const GATEWAY_LOGIN = process.env.IBKR_GATEWAY_URL ?? 'https://localhost:5000';

let origin = '';
let mainWindow = null;

async function createWindow() {
  const win = (mainWindow = new BrowserWindow({
    width: 1600,
    height: 980,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#0a0d12',
    title: 'ChartDesk',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  }));
  win.on('closed', () => { if (mainWindow === win) mainWindow = null; });
  // links to anything other than the app itself open in the system browser
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(origin)) { e.preventDefault(); shell.openExternal(url); } });
  await win.loadURL(`${origin}/#/app`);
}

function buildMenu() {
  const isMac = process.platform === 'darwin';
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(isMac ? [{ role: 'appMenu' }] : []),
    { role: 'fileMenu' },
    { role: 'editMenu' },
    { role: 'viewMenu' },
    {
      label: 'IBKR',
      submenu: [
        { label: 'Open IBKR Gateway Login', click: () => shell.openExternal(GATEWAY_LOGIN) },
        { label: 'Download Client Portal Gateway', click: () => shell.openExternal('https://www.interactivebrokers.com/en/trading/ib-api.php') },
      ],
    },
    { role: 'windowMenu' },
    {
      role: 'help',
      submenu: [
        { label: 'Check for Updates…', click: checkForUpdatesManually },
        { label: `About ChartDesk ${app.getVersion()}`, click: () => shell.openExternal('https://github.com/topfan2026/journal/releases') },
      ],
    },
  ]));
}

app.whenReady().then(async () => {
  const server = await createServer({ staticDir: distDir }).listen(0);
  origin = `http://127.0.0.1:${server.address().port}`;
  buildMenu();
  await createWindow();
  initUpdater(() => mainWindow);
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
