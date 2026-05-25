import express from "express";
import path from "path";
import dotenv from "dotenv";
import { createServer as createViteServer } from "vite";
import { execFile, spawn } from "child_process";
import { promisify } from "util";
import fs from "fs";
import os from "os";
import https from "https";
import http from "http";

dotenv.config();

const app = express();
const PORT = 3000;

// Increase JSON limit — audio payloads can be large
app.use(express.json({ limit: "200mb" }));
app.use(express.urlencoded({ limit: "200mb", extended: true }));

app.use((req, res, next) => {
  res.setHeader("Permissions-Policy", "display-capture=*");
  next();
});

// ── Python backend base URL ───────────────────────────────────────────
// Defaults to localhost (local mode). Frontend passes server_url for remote mode.
const DEFAULT_BACKEND = process.env.PYTHON_BACKEND_URL || "http://localhost:8000";

// ── Helpers ───────────────────────────────────────────────────────────

/**
 * Forward a GET request to the Python backend.
 */
async function backendGet(path: string, baseUrl: string = DEFAULT_BACKEND): Promise<any> {
  const url = `${baseUrl}${path}`;
  const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`Backend GET ${path} returned ${res.status}`);
  return res.json();
}

/**
 * Forward a POST request to the Python backend.
 */
async function backendPost(path: string, body: any, baseUrl: string = DEFAULT_BACKEND): Promise<any> {
  const url = `${baseUrl}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60000), // 60s for job submission
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Backend POST ${path} returned ${res.status}: ${text}`);
  }
  return res.json();
}

// ── ffmpeg availability check ─────────────────────────────────────────
// Run once at startup so we know immediately if ffmpeg is missing,
// rather than discovering it silently mid-recording.
let ffmpegAvailable = false;

function checkFfmpeg(): Promise<void> {
  return new Promise((resolve) => {
    const probe = spawn("ffmpeg", ["-version"]);
    probe.on("close", (code) => {
      ffmpegAvailable = code === 0;
      if (ffmpegAvailable) {
        console.log("  ✓ ffmpeg found — audio conversion ready");
      } else {
        console.error("  ✗ ffmpeg not found — install it and add to PATH");
        console.error("    Windows: winget install ffmpeg   OR   https://ffmpeg.org/download.html");
      }
      resolve();
    });
    probe.on("error", () => {
      ffmpegAvailable = false;
      console.error("  ✗ ffmpeg not found — install it and add to PATH");
      console.error("    Windows: winget install ffmpeg   OR   https://ffmpeg.org/download.html");
      resolve();
    });
  });
}

/**
 * Convert base64 WebM audio (from browser MediaRecorder) to base64 WAV
 * at 16kHz mono using ffmpeg, which is what Parakeet expects.
 * Validates the output is a real WAV before returning.
 */
async function webmToWavBase64(webmBase64: string): Promise<string> {
  if (!ffmpegAvailable) {
    throw new Error(
      "ffmpeg is not installed or not on PATH. " +
      "Install it with: winget install ffmpeg — then restart the frontend server."
    );
  }

  const tmpDir = os.tmpdir();
  const ts = Date.now();
  const inputPath  = path.join(tmpDir, `clarify_in_${ts}.webm`);
  const outputPath = path.join(tmpDir, `clarify_out_${ts}.wav`);

  try {
    // Write the raw WebM bytes to a temp file
    const webmBuffer = Buffer.from(webmBase64, "base64");
    console.log(`  Audio input: ${(webmBuffer.length / 1024).toFixed(1)} KB WebM`);
    fs.writeFileSync(inputPath, webmBuffer);

    // Run ffmpeg: any-format audio → 16kHz mono PCM WAV
    await new Promise<void>((resolve, reject) => {
      const ff = spawn("ffmpeg", [
        "-y",                  // overwrite output without asking
        "-i", inputPath,       // input file
        "-vn",                 // drop any video stream
        "-ar", "16000",        // resample to 16kHz (Parakeet requirement)
        "-ac", "1",            // mix down to mono
        "-c:a", "pcm_s16le",   // 16-bit PCM (standard WAV)
        "-f", "wav",
        outputPath,
      ]);

      // Capture stderr for diagnostics — ffmpeg writes progress there
      const ffmpegLog: string[] = [];
      ff.stderr.on("data", (d: Buffer) => ffmpegLog.push(d.toString()));

      ff.on("close", (code) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(
            `ffmpeg conversion failed (exit ${code}).\n` +
            `Details: ${ffmpegLog.slice(-5).join("")}`
          ));
        }
      });
      ff.on("error", (err) => {
        reject(new Error(`ffmpeg spawn error: ${err.message}`));
      });
    });

    // Read and validate the output file is a real WAV (starts with "RIFF")
    const wavBuffer = fs.readFileSync(outputPath);
    const header = wavBuffer.slice(0, 4).toString("ascii");
    if (header !== "RIFF") {
      throw new Error(
        `ffmpeg produced an invalid WAV file (header: '${header}'). ` +
        `The recording may be empty or corrupt — try recording again.`
      );
    }

    const wavBase64 = wavBuffer.toString("base64");
    console.log(`  Audio output: ${(wavBuffer.length / 1024).toFixed(1)} KB WAV @ 16kHz mono`);
    return wavBase64;

  } finally {
    try { fs.unlinkSync(inputPath);  } catch {}
    try { fs.unlinkSync(outputPath); } catch {}
  }
}

// ═══════════════════════════════════════════════════════════════════════
// API ROUTES
// ═══════════════════════════════════════════════════════════════════════

/**
 * GET /api/startup-check
 * Pings the Python backend's /health endpoint and returns status.
 * Replaces the old simulated mock.
 */
app.get("/api/startup-check", async (req, res) => {
  try {
    const health = await backendGet("/health");
    res.json({
      ollamaRunning: health.ollama?.includes("available") ?? false,
      cudaAvailable: health.gpu && !health.gpu.includes("No CUDA"),
      outputWritable: true,
      backendOnline: true,
      gpu: health.gpu || "unknown",
    });
  } catch (err: any) {
    // Backend not running yet — return safe defaults so UI still loads
    console.warn("Python backend not reachable on startup:", err.message);
    res.json({
      ollamaRunning: false,
      cudaAvailable: false,
      outputWritable: true,
      backendOnline: false,
      gpu: "Backend offline",
    });
  }
});


/**
 * POST /api/check-ollama
 * Asks the Python backend's health endpoint if Ollama + model are available.
 */
app.post("/api/check-ollama", async (req, res) => {
  const { model = "gemma3:4b" } = req.body;

  // Try both hostnames — Ollama sometimes binds to 127.0.0.1 instead of localhost
  const candidates = ["http://localhost:11434", "http://127.0.0.1:11434"];

  for (const ollamaUrl of candidates) {
    try {
      const response = await fetch(`${ollamaUrl}/api/tags`, {
        signal: AbortSignal.timeout(8000),   // longer timeout than before
      });
      const data = await response.json();
      const models: string[] = (data.models || []).map((m: any) => m.name);
      const modelBase = model.split(":")[0];
      const found = models.some((m) => m.includes(modelBase));
      if (found) {
        return res.json({ available: true, message: `Model '${model}' is available in Ollama (${ollamaUrl}).` });
      } else {
        return res.json({
          available: false,
          message: `Ollama reachable at ${ollamaUrl} but model '${model}' not pulled. Run: ollama pull ${model}`,
        });
      }
    } catch {
      // Try next candidate
      continue;
    }
  }

  res.json({
    available: false,
    message: `Ollama not reachable on localhost:11434 or 127.0.0.1:11434. Open Ollama from the system tray or run: ollama serve`,
  });
});

/**
 * POST /api/check-server
 * Tests connectivity to a remote Python backend (remote mode).
 */
app.post("/api/check-server", async (req, res) => {
  const { server_url = "http://localhost:8000" } = req.body;
  const start = Date.now();
  try {
    const health = await backendGet("/health", server_url);
    const latency = Date.now() - start;
    res.json({
      connected: true,
      latency_ms: latency,
      message: `Connected to Clarify backend at ${server_url}. GPU: ${health.gpu || "unknown"}.`,
    });
  } catch (err: any) {
    res.json({
      connected: false,
      latency_ms: null,
      message: `Cannot reach backend at ${server_url}: ${err.message}`,
    });
  }
});

/**
 * POST /api/process
 * Main processing endpoint. Receives audio from the browser, converts it
 * to WAV, submits it to the Python backend, and returns a job ID.
 *
 * Body:
 *   audioBase64:  string | null  — base64 WebM from MediaRecorder
 *   duration:     number         — recorded seconds
 *   settings:     EngineSettings — user config from the UI
 *   isSimulated:  boolean        — true = use backend sample data (dev/demo mode)
 *   sampleIndex:  number         — which sample to use in simulated mode
 */
app.post("/api/process", async (req, res) => {
  const { audioBase64, duration, settings, isSimulated, sampleIndex } = req.body;

  // Determine which backend URL to use (local vs remote mode)
  const backendUrl = settings?.remote_mode && settings?.server_url
    ? settings.server_url
    : DEFAULT_BACKEND;

  try {
    let wavBase64: string | null = null;

    if (audioBase64 && !isSimulated) {
      // Convert browser WebM → 16kHz mono WAV for Parakeet.
      // This throws clearly if ffmpeg is missing or the conversion fails —
      // we never send raw WebM to Python because it will always cause "not a RIFF" errors.
      console.log("Converting WebM audio to WAV for Parakeet...");
      wavBase64 = await webmToWavBase64(audioBase64);
    }

    // Submit job to Python backend
    const payload = {
      audio_b64: wavBase64,
      export_format: settings?.export_format || "docx",
      diarization: settings?.diarization ?? false,
      ollama_model: settings?.ollama_model || "gemma3:4b",
      is_simulated: isSimulated ?? false,       // ← pass simulation flag
      sample_index: sampleIndex ?? 0,           // ← pass which sample
    };

    const backendResponse = await backendPost("/jobs/submit", payload, backendUrl);

    // Return the Python backend's job ID directly to the frontend
    res.json({ jobId: backendResponse.job_id });

  } catch (err: any) {
    console.error("Failed to submit job to Python backend:", err.message);
    res.status(502).json({
      error: err.message || "Could not reach the Python backend. Make sure server_api.py is running.",
    });
  }
});

/**
 * GET /api/download?path=<server-side-path>
 * Streams a backend-generated file (DOCX, PDF, TXT) to the browser.
 * Only serves files inside the configured output directory to prevent
 * path traversal attacks.
 */
app.get("/api/download", (req, res) => {
  const requestedPath = req.query.path as string;

  if (!requestedPath) {
    return res.status(400).json({ error: "Missing 'path' query parameter." });
  }

  const outputRoot = path.resolve(process.env.OUTPUT_DIR || "./output");
  const resolvedPath = path.resolve(requestedPath);

  // Reject any path that escapes the output directory
  if (!resolvedPath.startsWith(outputRoot)) {
    return res.status(403).json({ error: "Access denied: path is outside output directory." });
  }

  if (!fs.existsSync(resolvedPath)) {
    return res.status(404).json({ error: "File not found." });
  }

  const ext = path.extname(resolvedPath).toLowerCase();
  const mimeTypes: Record<string, string> = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf":  "application/pdf",
    ".txt":  "text/plain",
    ".wav":  "audio/wav",
  };
  const mimeType = mimeTypes[ext] || "application/octet-stream";

  res.setHeader("Content-Type", mimeType);
  res.setHeader("Content-Disposition", `attachment; filename="${path.basename(resolvedPath)}"`);
  fs.createReadStream(resolvedPath).pipe(res);
});

app.get("/api/status/:id", async (req, res) => {
  const jobId = req.params.id;

  // Determine backend URL — we store it in a query param from the frontend
  const backendUrl = (req.query.backend_url as string) || DEFAULT_BACKEND;

  try {
    const job = await backendGet(`/jobs/${jobId}`, backendUrl);

    // Map Python backend shape → frontend shape
    const isDone = job.status === "done";
    const isError = job.status === "error";

    const frontendJob: any = {
      id: job.job_id,
      stage: job.status,
      pct: job.progress_pct,
      msg: job.progress_msg,
      result: null,
      error: job.error || null,
    };

    if (isDone && !job.error) {
      // Build a ProcessingResult matching src/types.ts
      frontendJob.result = {
        audio_path: job.audio_path || "",
        transcript_path: job.transcript_path || "",
        summary_path: job.summary_path || "",
        export_path: job.export_path || "",
        transcript_text: job.transcript || "",
        summary_text: job.summary || "",
        speakers: job.speakers || [],
        duration_seconds: job.duration_seconds || 0,
        error: null,
      };
      // Mark as done so frontend exits the polling loop
      frontendJob.stage = "done";
    }

    res.json(frontendJob);
  } catch (err: any) {
    console.error(`Status poll failed for job ${jobId}:`, err.message);
    res.status(502).json({
      id: jobId,
      stage: "error",
      pct: 0,
      msg: "Lost connection to processing backend.",
      result: null,
      error: err.message,
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════
// Vite dev server / static serving
// ═══════════════════════════════════════════════════════════════════════

async function startServer() {
  await checkFfmpeg();

  const certPath = path.join(process.cwd(), "cert.pem");
  const keyPath  = path.join(process.cwd(), "key.pem");
  const hasCerts = fs.existsSync(certPath) && fs.existsSync(keyPath);

  const httpsOptions = hasCerts ? {
    cert: fs.readFileSync(certPath),
    key:  fs.readFileSync(keyPath),
  } : null;

  // Create the HTTP(S) server first so we can pass it to Vite middleware.
  // Vite needs a reference to the actual server to configure HMR (ws vs wss)
  // correctly — without this, HMR tries ws:// on an HTTPS page and browsers
  // block the mixed-content websocket, causing a blank page with no errors.
  const server = httpsOptions
    ? https.createServer(httpsOptions, app)
    : http.createServer(app);

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: {
        middlewareMode: true,
        // Pass the actual server so Vite configures HMR over wss:// automatically
        hmr: { server },
      },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    console.log("Production Assets Path:", distPath);
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  server.listen(PORT, "0.0.0.0", () => {
    const protocol = httpsOptions ? "https" : "http";
    console.log("");
    console.log("  ╔══════════════════════════════════════╗");
    console.log(`  ║     Clarify Frontend Bridge           ║`);
    console.log(`  ║     ${protocol}://localhost:${PORT}             ║`);
    console.log(`  ║     Python backend: ${DEFAULT_BACKEND.padEnd(17)}║`);
    console.log("  ╚══════════════════════════════════════╝");
    console.log("");
    if (httpsOptions) {
      console.log("  Access from laptop: https://<tailscale-ip>:3000");
      console.log("  NOTE: Accept the certificate warning on first visit.");
    } else {
      console.log("  ⚠ No certs found — running HTTP only.");
      console.log("  Tab audio capture will NOT work from other devices.");
      console.log("  Generate certs with mkcert or openssl to enable HTTPS.");
    }
    console.log("");
    console.log("  Make sure the Python backend is running:");
    console.log("    cd ../backend && python server_api.py");
    console.log("");
  });
}

startServer();