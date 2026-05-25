import { useState } from "react";
import { X, Folder, FileText, Key, Cpu, Save, CheckCircle, AlertCircle, Loader2, Database, Wifi } from "lucide-react";
import { EngineSettings, ExportFormat } from "../types";

interface SettingsPanelProps {
  settings: EngineSettings;
  onSave: (newSettings: EngineSettings) => void;
  onClose: () => void;
}

export function SettingsPanel({
  settings,
  onSave,
  onClose,
}: SettingsPanelProps) {
  const [localSettings, setLocalSettings] = useState<EngineSettings>({ ...settings });
  
  // Test connection states
  const [testingOllama, setTestingOllama] = useState(false);
  const [ollamaStatus, setOllamaStatus] = useState<{ success: boolean; msg: string } | null>(null);

  const [testingServer, setTestingServer] = useState(false);
  const [serverStatus, setServerStatus] = useState<{ success: boolean; msg: string } | null>(null);

  const handleTestOllama = async () => {
    setTestingOllama(true);
    setOllamaStatus(null);
    try {
      const res = await fetch("/api/check-ollama", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: localSettings.ollama_model })
      });
      const data = await res.json();
      if (data.available) {
        setOllamaStatus({ success: true, msg: data.message });
      } else {
        setOllamaStatus({ success: false, msg: "Failed to discover selected model context." });
      }
    } catch (err: any) {
      setOllamaStatus({ success: false, msg: `Connection refused: ${err.message || err}` });
    } finally {
      setTestingOllama(false);
    }
  };

  const handleTestServer = async () => {
    setTestingServer(true);
    setServerStatus(null);
    try {
      const res = await fetch("/api/check-server", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ server_url: localSettings.server_url })
      });
      const data = await res.json();
      if (data.connected) {
        setServerStatus({ success: true, msg: `${data.message} Latency: ${data.latency_ms}ms.` });
      } else {
        setServerStatus({ success: false, msg: "Remote server exists but refused authentication." });
      }
    } catch (err: any) {
      setServerStatus({ success: false, msg: `Could not reach remote server: ${err.message || err}` });
    } finally {
      setTestingServer(false);
    }
  };

  const handleSave = () => {
    onSave(localSettings);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 animate-fade-in">
      <div className="w-full max-w-2xl bg-slate-900 border border-slate-805 rounded-2xl h-full max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800/80 p-5 shrink-0">
          <div className="flex items-center gap-2">
            <Cpu className="text-indigo-400 w-5 h-5" />
            <h3 className="font-display font-semibold text-lg text-white">MeetScribe Engine Configurations</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Configurations Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Section 1: Local System Paths */}
          <div className="space-y-4">
            <h4 className="text-xs font-mono text-indigo-400 uppercase tracking-widest font-semibold">1. Storage & Export</h4>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-300 font-medium flex items-center gap-1.5">
                  <Folder className="w-3.5 h-3.5 text-slate-400" /> Save Output Directory:
                </label>
                <input
                  type="text"
                  value={localSettings.output_dir}
                  onChange={(e) => setLocalSettings({ ...localSettings, output_dir: e.target.value })}
                  placeholder="./output"
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-300 font-medium flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5 text-slate-400" /> Export Compilation Format:
                </label>
                <select
                  value={localSettings.export_format}
                  onChange={(e) => setLocalSettings({ ...localSettings, export_format: e.target.value as ExportFormat })}
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="docx">Microsoft Word (.docx)</option>
                  <option value="pdf">Adobe PDF document (.pdf)</option>
                  <option value="txt">Raw Markdown PlainText (.txt)</option>
                  <option value="all">Export All Formats (WAV + PDFs + Docx)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Section 2: AI Summarizer & Language Models */}
          <div className="space-y-4 border-t border-slate-800/60 pt-6">
            <h4 className="text-xs font-mono text-indigo-400 uppercase tracking-widest font-semibold">2. Local Summary Models (Ollama)</h4>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-300 font-medium flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-slate-400" /> Ollama Target Model:
                </label>
                <select
                  value={localSettings.ollama_model}
                  onChange={(e) => setLocalSettings({ ...localSettings, ollama_model: e.target.value })}
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                >
                  <option value="gemma3:4b">gemma3:4b (Recommended Default — 3GB)</option>
                  <option value="mistral-nemo">mistral-nemo (Best Precision — 7GB)</option>
                  <option value="mistral">mistral (Lightweight — 4GB)</option>
                  <option value="llama3.3">llama3.3 (Highest Quality — 20GB)</option>
                  <option value="llama3.2">llama3.2 (Fast and Light — 2GB)</option>
                </select>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-300 font-medium">
                  Model Context Length (num_ctx):
                </label>
                <input
                  type="number"
                  value={localSettings.ollama_num_ctx}
                  onChange={(e) => setLocalSettings({ ...localSettings, ollama_num_ctx: parseInt(e.target.value) || 8192 })}
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-400">Validate selected model availability in Ollama endpoint.</span>
                <button
                  type="button"
                  onClick={handleTestOllama}
                  disabled={testingOllama}
                  className="text-xs font-medium text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
                >
                  {testingOllama && <Loader2 className="w-3 h-3 animate-spin" />}
                  Test selected model
                </button>
              </div>

              {ollamaStatus && (
                <div className={`p-2.5 rounded-lg border text-xs flex items-center gap-2 ${
                  ollamaStatus.success ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" : "bg-rose-500/10 border-rose-500/20 text-rose-300"
                }`}>
                  {ollamaStatus.success ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                  <span>{ollamaStatus.msg}</span>
                </div>
              )}
            </div>
          </div>

          {/* Section 3: Speaker Identification & Diarization */}
          <div className="space-y-4 border-t border-slate-800/60 pt-6">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-xs font-mono text-indigo-400 uppercase tracking-widest font-semibold flex items-center gap-2">
                  3. Diarization Parameters
                </h4>
                <p className="text-[11px] text-slate-400 mt-0.5">Separate different speakers during transcription blocks.</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.diarization}
                  onChange={(e) => setLocalSettings({ ...localSettings, diarization: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-slate-950 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-650 peer-checked:after:bg-indigo-400 border border-slate-800"></div>
              </label>
            </div>

            {localSettings.diarization && (
              <div className="flex flex-col gap-1.5 animate-fade-in">
                <label className="text-xs text-slate-300 font-medium flex items-center gap-1.5">
                  <Key className="w-3.5 h-3.5 text-slate-400" /> HuggingFace Auth Token (Required for pyannote speaker matching):
                </label>
                <input
                  type="password"
                  value={localSettings.hf_token}
                  onChange={(e) => setLocalSettings({ ...localSettings, hf_token: e.target.value })}
                  placeholder="hf_..."
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                />
                <span className="text-[10px] text-slate-500 leading-relaxed">
                  Your HF auth token coordinates on-device validation for HuggingFace's pyannote dataset repository. Set local-only.
                </span>
              </div>
            )}
          </div>

          {/* Section 4: Remote Mode Settings */}
          <div className="space-y-4 border-t border-slate-800/60 pt-6">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-xs font-mono text-indigo-400 uppercase tracking-widest font-semibold">4. Hybrid Remote Engine</h4>
                <p className="text-[11px] text-slate-400 mt-0.5">Stream capture sessions to an external high-GPU server box.</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.remote_mode}
                  onChange={(e) => setLocalSettings({ ...localSettings, remote_mode: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-slate-950 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-650 peer-checked:after:bg-indigo-400 border border-slate-800"></div>
              </label>
            </div>

            {localSettings.remote_mode && (
              <div className="space-y-3 animate-fade-in">
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-slate-300 font-medium flex items-center gap-1.5">
                    <Wifi className="w-3.5 h-3.5 text-slate-400" /> Remote Server URL Address:
                  </label>
                  <input
                    type="text"
                    value={localSettings.server_url}
                    onChange={(e) => setLocalSettings({ ...localSettings, server_url: e.target.value })}
                    className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-400">Verify response status of the specified cluster endpoint.</span>
                    <button
                      type="button"
                      onClick={handleTestServer}
                      disabled={testingServer}
                      className="text-xs font-medium text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
                    >
                      {testingServer && <Loader2 className="w-3 h-3 animate-spin" />}
                      Test connection now
                    </button>
                  </div>

                  {serverStatus && (
                    <div className={`p-2.5 rounded-lg border text-xs flex items-center gap-2 ${
                      serverStatus.success ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" : "bg-rose-500/10 border-rose-500/20 text-rose-300"
                    }`}>
                      {serverStatus.success ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                      <span>{serverStatus.msg}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Footer Actions */}
        <div className="p-5 border-t border-slate-800/80 bg-slate-950/40 flex items-center justify-end gap-3 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 border border-slate-800 hover:bg-slate-800 text-slate-300 hover:text-white rounded-xl text-xs font-medium transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-indigo-650 hover:bg-indigo-600 text-white rounded-xl text-xs font-medium flex items-center gap-1.5 transition shadow-lg shadow-indigo-950/45"
            id="btn_settings_save"
          >
            <Save className="w-4 h-4" />
            Apply Settings
          </button>
        </div>
      </div>
    </div>
  );
}