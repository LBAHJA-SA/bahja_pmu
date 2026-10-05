const { app, BrowserWindow } = require('electron')
const path = require('path')

function createWindow() {
  const win = new BrowserWindow({
    width: 1200, height: 800,
    title: 'Bahja PMU',
    autoHideMenuBar: true,
  })
  const devUrl = process.env.ELECTRON_DEV_URL
  if (devUrl) win.loadURL(devUrl)
  else win.loadFile(path.join(__dirname, 'dist', 'index.html'))
}

app.whenReady().then(createWindow)
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() })
