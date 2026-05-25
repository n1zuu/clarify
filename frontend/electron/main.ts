import { app, BrowserWindow, shell } from "electron";
import { spawn, ChildProcess } from "child_process";
import path from "path";

let mainWindow: BrowserWindow | null = null;
let backendProcess: ChildProcess | null = null;

function startBackend() {
  // Path to the bundled Python backend executable
  const backendExe = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "MeetScribe.exe")
    : path.join(__dirname, "../../backend/server_api.py");

  if (app.isPackaged) {
    // Production: run the compiled .exe
    backendProcess = spawn(backendExe, [], { detached: false });
  } else {
    // Development: run Python directly
    backendProcess = spawn("python", [backendExe], { detached: false });
  }

  backendProcess.stdout?.on("data", (d) => console.log("[backend]", d.toString()));
  backendProcess.stderr?.on("data", (d) => console.error("[backend]", d.toString()));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 650,
    title: "Clarify",
    icon: path.join(__dirname, "../assets/icon.ico"),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    titleBarStyle: "hidden",
    backgroundColor: "#0f172a",   // matches slate-950
  });

  // In production, load the built React app
  // In dev, load from Vite dev server
  const url = app.isPackaged
    ? `file://${path.join(__dirname, "../dist/index.html")}`
    : "http://localhost:3000";

  mainWindow.loadURL(url);

  // Open external links in the OS browser, not Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(() => {
  startBackend();

  // Give the backend a moment to start before loading the UI
  setTimeout(createWindow, 1500);
});

app.on("window-all-closed", () => {
  // Kill the Python backend when the app closes
  if (backendProcess) {
    backendProcess.kill();
  }
  if (process.platform !== "darwin") app.quit();
});