import { useState } from "react";
import { Mic, Cpu, CheckCircle, AlertTriangle, X, Terminal } from "lucide-react";
import { StartupAlerts } from "../types";

interface HeaderProps {
  alerts: StartupAlerts;
  dismissWarning: () => void;
  showWarning: boolean;
}

export function Header({ alerts, dismissWarning, showWarning }: HeaderProps) {
  return (
    <div className="w-full flex flex-col gap-4">
      {/* Prime Header Bar */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-rose-500 shadow-indigo-500/10 shadow-lg">
            <Mic className="text-white w-5.5 h-5.5" id="header_logo" />
            <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-500 border-2 border-slate-950 rounded-full animate-ping" />
            <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-500 border-2 border-slate-950 rounded-full" />
          </div>
          <div>
            <h1 className="font-display font-semibold text-xl tracking-tight text-white flex items-center gap-2">
              Clarify <span className="text-xs font-mono font-normal tracking-wide bg-indigo-505/10 text-indigo-400 border border-indigo-500/20 px-1.5 py-0.5 rounded uppercase">MeetScribe v1.4</span>
            </h1>
            <p className="text-xs text-slate-400">On-device Audio Capturing & Meeting Intelligence Briefing</p>
          </div>
        </div>

        {/* Core System Indicators */}
        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-2 bg-slate-900/60 border border-slate-800/80 px-2.5 py-1.5 rounded-lg">
            <Cpu className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-slate-400">Engine:</span>
            <span className="text-white font-medium">Local Ollama</span>
          </div>

          <div className="flex items-center gap-2 bg-slate-900/60 border border-slate-800/80 px-2.5 py-1.5 rounded-lg">
            <Terminal className="w-3.5 h-3.5 text-rose-400" />
            <span className="text-slate-400">Processing:</span>
            <span className={alerts.cudaAvailable ? "text-emerald-400" : "text-amber-400"}>
              {alerts.cudaAvailable ? "CUDA GPU" : "CPU Bound"}
            </span>
          </div>
        </div>
      </div>

      {/* Dismissible Warning Banner (Required by startup checklist) */}
      {showWarning && (!alerts.ollamaRunning || !alerts.cudaAvailable || !alerts.outputWritable) && (
        <div className="flex items-start justify-between bg-amber-500/10 border border-amber-500/20 text-amber-200 px-4 py-3.5 rounded-xl text-xs gap-3 animate-fade-in shadow-lg shadow-amber-950/10">
          <div className="flex gap-2.5">
            <AlertTriangle className="w-4.5 h-4.5 text-amber-400 shrink-0 mt-0.5" />
            <div className="flex flex-col gap-1">
              <span className="font-semibold text-amber-300">Environment Diagnostic Warnings:</span>
              <ul className="list-disc pl-4 space-y-1 text-slate-300">
                {!alerts.ollamaRunning && (
                  <li>Ollama service is not reachable on localhost:11434. Local LLM summary triggers will execute in simulation model.</li>
                )}
                {!alerts.cudaAvailable && (
                  <li>No NVIDIA CUDA accelerator detected. Audio speech-to-text transcription uses CPU fallback (NVIDIA Parakeet may run details slowly).</li>
                )}
                {!alerts.outputWritable && (
                  <li>The local Output folder directory is not currently writable. Please verify settings write privileges.</li>
                )}
              </ul>
            </div>
          </div>
          <button
            onClick={dismissWarning}
            className="text-slate-400 hover:text-white transition p-1 rounded hover:bg-slate-800/50"
            title="Dismiss Warnings"
          >
            <X className="w-4.5 h-4.5" />
          </button>
        </div>
      )}
    </div>
  );
}
