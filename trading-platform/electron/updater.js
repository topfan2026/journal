// In-app updates from this project's GitHub Releases (public repo, no token needed).
// Windows and Linux AppImage update in place; macOS needs a signed build to self-update,
// so there we just point to the download page.
import { app, dialog, shell } from 'electron';
import electronUpdater from 'electron-updater';

const { autoUpdater } = electronUpdater;
const RELEASES_URL = 'https://github.com/topfan2026/journal/releases/latest';
const CHECK_EVERY_MS = 4 * 60 * 60 * 1000;
const canSelfUpdate = app.isPackaged && process.platform !== 'darwin';

let getWindow = () => null;
let manualCheck = false;
let downloading = false;

const box = (opts) => dialog.showMessageBox(getWindow() ?? undefined, { title: 'ChartDesk', ...opts });

export function initUpdater(windowGetter) {
  getWindow = windowGetter;
  if (!canSelfUpdate) return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    downloading = true;
    if (manualCheck) box({ type: 'info', message: `Downloading ChartDesk ${info.version}…`, detail: "You'll be asked to restart when it's ready." });
  });
  autoUpdater.on('update-not-available', () => {
    if (manualCheck) box({ type: 'info', message: `You're up to date`, detail: `ChartDesk ${app.getVersion()} is the latest version.` });
    manualCheck = false;
  });
  autoUpdater.on('error', (err) => {
    downloading = false;
    if (manualCheck) box({ type: 'warning', message: 'Could not check for updates', detail: String(err?.message ?? err) });
    manualCheck = false;
  });
  autoUpdater.on('update-downloaded', async (info) => {
    downloading = false;
    manualCheck = false;
    const { response } = await box({
      type: 'info',
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
      message: `ChartDesk ${info.version} is ready to install`,
      detail: 'Restart now to update, or it will install the next time you close ChartDesk.',
    });
    if (response === 0) autoUpdater.quitAndInstall();
  });

  check(false);
  setInterval(() => check(false), CHECK_EVERY_MS).unref?.();
}

function check(manual) {
  manualCheck = manual;
  autoUpdater.checkForUpdates().catch(() => { /* reported via the 'error' event */ });
}

/** Help → Check for Updates… */
export function checkForUpdatesManually() {
  if (!app.isPackaged) {
    box({ type: 'info', message: 'Updates are only available in the installed app.' });
  } else if (!canSelfUpdate) {
    shell.openExternal(RELEASES_URL);
  } else if (downloading) {
    box({ type: 'info', message: 'An update is already downloading.' });
  } else {
    check(true);
  }
}
