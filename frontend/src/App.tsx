import { useState, useEffect, useRef } from "react";
import { AppState, EngineSettings, ProgressPayload, ProcessingResult, StartupAlerts } from "./types";
import { Header } from "./components/Header";
import { MainPanel } from "./components/MainPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { ResultsPanel } from "./components/ResultsPanel";
import { AlertCircle, RefreshCw, Layers, ShieldCheck, HelpCircle } from "lucide-react";

const DEFAULT_SETTINGS: EngineSettings = {
  output_dir: "./output",
  export_format: "docx",
  diarization: false,
  hf_token: "",
  ollama_model: "gemma3:4b",
  ollama_num_ctx: 8192,
  server_url: "http://localhost:8000",
  remote_mode: false,
};

export default function App() {
  const [appState, setAppState] = useState<AppState>(AppState.IDLE);
  const [settings, setSettings] = useState<EngineSettings>(DEFAULT_SETTINGS);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [showWarning, setShowWarning] = useState(true);

  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressPayload>({ stage: "recording", pct: 0, msg: "Capture starting..." });
  const [result, setResult] = useState<ProcessingResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [recordingDuration, setRecordingDuration] = useState<number>(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<any>(null);

  const [startupAlerts, setStartupAlerts] = useState<StartupAlerts>({
    ollamaRunning: null,
    cudaAvailable: null,
    outputWritable: null,
    checked: false,
  });

  // ── 1. Startup checks ──────────────────────────────────────────────
  useEffect(() => {
    // Load saved settings first so startup check uses correct server_url
    const saved = localStorage.getItem("clarify_settings_v1");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setSettings(parsed);
      } catch {
        // Corrupt saved settings — wipe them so they can't cause silent failures
        localStorage.removeItem("clarify_settings_v1");
      }
    }

    // Retry startup check up to 3 times with a 3s gap — handles the case
    // where Tailscale is still establishing the connection when the page loads
    let attempts = 0;
    const MAX_ATTEMPTS = 3;

    const runCheck = () => {
      attempts++;
      fetch("/api/startup-check", { signal: AbortSignal.timeout(8000) })
        .then((res) => res.json())
        .then((data) => {
          setStartupAlerts({
            ollamaRunning: data.ollamaRunning,
            cudaAvailable: data.cudaAvailable,
            outputWritable: data.outputWritable,
            checked: true,
          });
        })
        .catch(() => {
          if (attempts < MAX_ATTEMPTS) {
            setTimeout(runCheck, 3000);
          } else {
            // All retries exhausted — mark as checked so UI doesn't hang
            setStartupAlerts((prev) => ({ ...prev, checked: true }));
          }
        });
    };

    runCheck();
  }, []);

  // ── 2. Job status polling ──────────────────────────────────────────
  useEffect(() => {
    if (!currentJobId) return;

    // The bridge server (Node) always talks to Python on localhost:8000 —
    // it's co-located on the same PC. remote_mode only applies when the
    // frontend would talk directly to a backend, which it never does here.
    // Passing anything other than localhost confuses Node's proxy logic.
    const backendUrl = settings.remote_mode && settings.server_url
      ? settings.server_url
      : "http://localhost:8000";

    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/status/${currentJobId}?backend_url=${encodeURIComponent(backendUrl)}`
        );
        if (!res.ok) throw new Error("Job not found in backend registry.");
        const job = await res.json();

        setProgress({ stage: job.stage, pct: job.pct, msg: job.msg });

        if (job.error) {
          clearInterval(pollInterval);
          setErrorMessage(job.error);
          setAppState(AppState.ERROR);
          setCurrentJobId(null);
        } else if (job.stage === "done" && job.result) {
          clearInterval(pollInterval);
          setResult(job.result);
          setAppState(AppState.DONE);
          setCurrentJobId(null);
        }
      } catch (err: any) {
        clearInterval(pollInterval);
        setErrorMessage(err.message || "Lost connection to processing backend.");
        setAppState(AppState.ERROR);
        setCurrentJobId(null);
      }
    }, 1500);

    return () => clearInterval(pollInterval);
  }, [currentJobId, settings]);

  // ── 3. Recording ───────────────────────────────────────────────────
  const handleStartRecording = async () => {
    setResult(null);
    setErrorMessage(null);
    audioChunksRef.current = [];

    try {
      // video: true is required to trigger the tab picker in Brave and Edge.
      // Chrome supports video: false, but the others don't — so we always
      // request video and immediately stop the video track after getting the stream.
      const stream = await (navigator.mediaDevices as any).getDisplayMedia({
        video: true,
        audio: {
          suppressLocalAudioPlayback: false,
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });

      // Stop the video track immediately — we only needed it to open the picker
      stream.getVideoTracks().forEach((t: MediaStreamTrack) => t.stop());

      // User picked a tab but didn't check "Share tab audio"
      if (stream.getAudioTracks().length === 0) {
        stream.getTracks().forEach((t: MediaStreamTrack) => t.stop());
        setErrorMessage("No audio track was captured. Click Record again, select your Google Meet tab, and make sure to check 'Share tab audio' before clicking Share.");
        return;
      }

      // Confirmed we have audio — now transition to RECORDING
      setAppState(AppState.RECORDING);
      setRecordingDuration(0);

      timerRef.current = setInterval(() => {
        setRecordingDuration((prev) => prev + 1);
      }, 1000);

      const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      // If the user stops sharing via the browser's built-in stop button,
      // treat it the same as clicking Stop in the UI
      stream.getAudioTracks()[0].onended = () => {
        if (mediaRecorderRef.current?.state !== "inactive") {
          handleStopRecording();
        }
      };

      mediaRecorder.start();

    } catch (err: any) {
      // User dismissed the picker — not an error worth showing
      if (err.name === "NotAllowedError" || err.name === "AbortError") {
        return;
      }
      setErrorMessage(`Could not start tab audio capture: ${err.message}`);
    }
  };

  const handleStopRecording = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    setAppState(AppState.PROCESSING);
    setProgress({ stage: "saving_audio", pct: 0.05, msg: "Sending audio to backend..." });

    const duration = recordingDuration || 0;

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        const reader = new FileReader();
        reader.readAsDataURL(blob);
        reader.onloadend = () => {
          const base64 = (reader.result as string).split(",")[1];
          submitJob(base64, duration, false, 0);
        };
      };
      mediaRecorderRef.current.stop();
      try { mediaRecorderRef.current.stream.getTracks().forEach((t) => t.stop()); } catch {}
    }
  };

  // ── 4. Simulation mode (uses real backend with sample data) ─────────
  const handleRunSimulation = (sampleIndex: number) => {
    setAppState(AppState.PROCESSING);
    setProgress({ stage: "recording", pct: 0.0, msg: "Running simulated meeting through backend..." });
    setResult(null);
    setErrorMessage(null);
    submitJob(null, 24.5, true, sampleIndex);
  };

  // ── 5. Submit to bridge server ─────────────────────────────────────
  const submitJob = async (
    audioBase64: string | null,
    duration: number,
    isSimulated: boolean,
    sampleIndex: number
  ) => {
    try {
      const resp = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audioBase64, duration, settings, isSimulated, sampleIndex }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: "Backend rejected request." }));
        throw new Error(err.error || "Backend error.");
      }
      const { jobId } = await resp.json();
      setCurrentJobId(jobId);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to reach the Clarify processing backend.");
      setAppState(AppState.ERROR);
    }
  };

  const handleSaveSettings = (newSettings: EngineSettings) => {
    setSettings(newSettings);
    localStorage.setItem("clarify_settings_v1", JSON.stringify(newSettings));
    setIsSettingsOpen(false);
  };

  return (
    <div className="min-h-screen flex flex-col items-center p-4 md:p-8 bg-gradient-to-b from-slate-950 via-slate-950 to-slate-900 border border-slate-900 shadow-2xl rounded-3xl max-w-7xl mx-auto w-full relative overflow-hidden my-4" id="app_frame">
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-505/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 right-1/4 w-[400px] h-[400px] bg-rose-505/5 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-4xl z-15 flex flex-col gap-6">
        <Header
          alerts={startupAlerts}
          dismissWarning={() => setShowWarning(false)}
          showWarning={showWarning}
        />

        {appState === AppState.DONE && result ? (
          <ResultsPanel result={result} onClose={() => setAppState(AppState.IDLE)} />
        ) : appState === AppState.ERROR ? (
          <div className="bg-rose-500/10 border border-rose-500/20 text-rose-200 p-6 rounded-2xl flex flex-col gap-4 shadow-xl shadow-rose-950/10">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-6 h-6 text-rose-400 shrink-0 mt-0.5" />
              <div className="flex flex-col gap-1.5">
                <h3 className="font-semibold text-white">Processing Error</h3>
                <p className="text-xs text-slate-300 leading-relaxed font-mono">
                  {errorMessage}
                </p>
                <div className="text-xs text-slate-400 mt-2 space-y-1">
                  <p className="font-bold text-slate-300">Troubleshooting:</p>
                  <ul className="list-disc pl-4 space-y-1">
                    <li>Make sure <code className="bg-slate-950 text-indigo-400 text-[10px] px-1 font-mono">python server_api.py</code> is running in the backend folder.</li>
                    <li>Make sure Ollama is running: <code className="bg-slate-950 text-indigo-400 text-[10px] px-1 font-mono">ollama serve</code></li>
                    <li>Verify your selected model is pulled: <code className="bg-slate-950 text-indigo-400 text-[10px] px-1 font-mono">ollama pull {settings.ollama_model}</code></li>
                  </ul>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3 self-end mt-2">
              <button
                onClick={() => setIsSettingsOpen(true)}
                className="px-3.5 py-1.5 border border-slate-800 hover:bg-slate-800 text-slate-300 hover:text-white rounded-lg text-xs font-medium transition"
              >
                Open Settings
              </button>
              <button
                onClick={() => setAppState(AppState.IDLE)}
                className="flex items-center gap-1.5 px-4 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-medium transition"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Try Again
              </button>
            </div>
          </div>
        ) : (
          <MainPanel
            appState={appState}
            settings={settings}
            progress={progress}
            recordingDuration={recordingDuration}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onStartRecording={handleStartRecording}
            onStopRecording={handleStopRecording}
            onRunSimulation={handleRunSimulation}
          />
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 border-t border-slate-800/60 pt-6">
          <div className="bg-slate-900/10 border border-slate-800/30 p-3.5 rounded-xl">
            <Layers className="w-4 h-4 text-indigo-400 mb-2" />
            <span className="font-semibold text-xs text-white block">On-Device Transcription</span>
            <p className="text-[10px] text-slate-400 leading-relaxed mt-0.5">
              NVIDIA Parakeet runs locally via NeMo — no audio ever leaves your machine.
            </p>
          </div>
          <div className="bg-slate-900/10 border border-slate-800/30 p-3.5 rounded-xl">
            <ShieldCheck className="w-4 h-4 text-emerald-400 mb-2" />
            <span className="font-semibold text-xs text-white block">Tab Audio Capture</span>
            <p className="text-[10px] text-slate-400 leading-relaxed mt-0.5">
              Captures only your Google Meet tab — no system sounds, no virtual cable needed.
            </p>
          </div>
          <div className="bg-slate-900/10 border border-slate-800/30 p-3.5 rounded-xl">
            <HelpCircle className="w-4 h-4 text-rose-400 mb-2" />
            <span className="font-semibold text-xs text-white block">Structured Export</span>
            <p className="text-[10px] text-slate-400 leading-relaxed mt-0.5">
              Outputs DOCX, PDF, and TXT meeting briefs with summaries and action items.
            </p>
          </div>
        </div>
      </div>

      {isSettingsOpen && (
        <SettingsPanel
          settings={settings}
          onSave={handleSaveSettings}
          onClose={() => setIsSettingsOpen(false)}
        />
      )}
    </div>
  );
}