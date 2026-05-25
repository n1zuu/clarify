import { useState } from "react";
import { FileText, Download, Users, Clock, Copy, Check, CheckCircle, ExternalLink, HelpCircle } from "lucide-react";
import { ProcessingResult } from "../types";

interface ResultsPanelProps {
  result: ProcessingResult;
  onClose: () => void;
}

export function ResultsPanel({ result, onClose }: ResultsPanelProps) {
  const [activeTab, setActiveTab] = useState<"summary" | "transcript" | "speakers">("summary");
  const [copiedText, setCopiedText] = useState(false);

  const handleCopySummary = async () => {
    try {
      await navigator.clipboard.writeText(result.summary_text);
      setCopiedText(true);
      setTimeout(() => setCopiedText(false), 2000);
    } catch (err) {
      console.error("Failed to copy transcript", err);
    }
  };

  const handleTriggerDownload = (format: "txt" | "md" | "docx") => {
    const textToDownload = format === "docx" || format === "txt" ? result.transcript_text : result.summary_text;
    const blob = new Blob([textToDownload], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `Clarify_Session.${format}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Convert seconds to human format e.g. "1m 45s"
  const translateDurationType = (seconds: number) => {
    if (!seconds) return "0s";
    const mm = Math.floor(seconds / 60);
    const ss = Math.floor(seconds % 60);
    return mm > 0 ? `${mm}m ${ss}s` : `${ss}s`;
  };

  return (
    <div className="w-full bg-slate-900/40 border border-slate-805 rounded-2xl p-6 relative overflow-hidden backdrop-blur-md shadow-2xl flex flex-col gap-5 animate-fade-in" id="panel_results">
      {/* Session Title Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-5">
        <div>
          <span className="text-[10px] font-mono font-semibold tracking-wider text-indigo-400 bg-indigo-505/10 border border-indigo-500/20 px-2 py-0.5 rounded uppercase">
            Processing Completed Successfully
          </span>
          <h3 className="font-display font-semibold text-lg text-white mt-1.5 flex items-center gap-2">
            <CheckCircle className="text-emerald-400 w-5 h-5 shrink-0" />
            Workspace Meeting Intelligence Output
          </h3>
        </div>

        {/* Floating Quick Action Tabs */}
        <div className="flex items-center gap-3 text-xs">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-lg border border-slate-800 hover:bg-slate-850 text-slate-400 hover:text-white font-medium transition"
          >
            Clear / Record New
          </button>
        </div>
      </div>

      {/* Meta Stats Panel */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-xl flex items-center gap-3">
          <Clock className="w-4 h-4 text-indigo-400" />
          <div>
            <span className="text-[10px] text-slate-500 font-mono block">DURATION</span>
            <span className="text-xs font-semibold text-white font-mono">{translateDurationType(result.duration_seconds)}</span>
          </div>
        </div>

        <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-xl flex items-center gap-3">
          <Users className="w-4 h-4 text-rose-400" />
          <div>
            <span className="text-[10px] text-slate-500 font-mono block">PARTICIPANTS</span>
            <span className="text-xs font-semibold text-white font-mono">
              {result.speakers.length > 0 ? `${result.speakers.length} Identified` : "Single Stream"}
            </span>
          </div>
        </div>

        <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-xl flex flex-col justify-center select-all">
          <span className="text-[10px] text-slate-500 font-mono">EXPORT PATH</span>
          <span className="text-[10px] font-mono text-indigo-300 truncate mt-0.5" title={result.export_path}>
            {result.export_path}
          </span>
        </div>

        <div className="bg-slate-950/60 border border-slate-800/80 p-3 rounded-xl flex flex-col justify-center select-all">
          <span className="text-[10px] text-slate-500 font-mono">AUDIO SOURCE</span>
          <span className="text-[10px] font-mono text-emerald-400 truncate mt-0.5" title={result.audio_path}>
            WAV 48kHz Stereo Loopback
          </span>
        </div>
      </div>

      {/* Primary Display Card with Tab Filters */}
      <div className="border border-slate-800 rounded-xl bg-slate-950/30 overflow-hidden flex flex-col">
        {/* Tab Filters header */}
        <div className="flex items-center justify-between border-b border-slate-800/80 bg-slate-950/60 px-4 py-3">
          <div className="flex items-center gap-1.5 font-medium text-xs">
            <button
              onClick={() => setActiveTab("summary")}
              className={`px-3 py-1.5 rounded-lg transition ${
                activeTab === "summary" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Executive Summary
            </button>
            <button
              onClick={() => setActiveTab("transcript")}
              className={`px-3 py-1.5 rounded-lg transition ${
                activeTab === "transcript" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Dialogue Transcript
            </button>
            <button
              onClick={() => setActiveTab("speakers")}
              className={`px-3 py-1.5 rounded-lg transition ${
                activeTab === "speakers" ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Speaker Registry
            </button>
          </div>

          <div className="flex items-center gap-2">
            {activeTab === "summary" ? (
              <button
                onClick={handleCopySummary}
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-indigo-505/10 border border-indigo-500/20 text-indigo-400 hover:bg-indigo-650 hover:text-white transition duration-150 text-[11px] font-medium"
              >
                {copiedText ? (
                  <>
                    <Check className="w-3.5 h-3.5" /> Copied briefing!
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" /> Copy markdown
                  </>
                )}
              </button>
            ) : null}
          </div>
        </div>

        {/* Tab content screens */}
        <div className="p-5 max-h-[420px] min-h-[180px] overflow-y-auto leading-relaxed text-sm text-slate-300">
          {activeTab === "summary" && (
            <div className="prose prose-invert max-w-none text-slate-300 space-y-4">
              {result.summary_text.split("\n\n").map((para, idx) => {
                // Formatting helper for simple inline headers or list points
                if (para.startsWith("# ")) {
                  return <h1 key={idx} className="text-xl font-display font-bold text-white tracking-tight mt-2">{para.replace("# ", "")}</h1>;
                }
                if (para.startsWith("## ")) {
                  return <h2 key={idx} className="text-md font-display font-semibold text-indigo-300 tracking-tight mt-3 border-b border-indigo-950/20 pb-1">{para.replace("## ", "")}</h2>;
                }
                if (para.startsWith("- ") || para.startsWith("* ")) {
                  return (
                    <ul key={idx} className="list-disc pl-5 text-xs text-slate-300 space-y-1.5">
                      {para.split("\n").map((li, liIdx) => (
                        <li key={liIdx}>
                          {li.replace(/^[\s*-]+/, "").split("**").map((textBlock, blockIdx) => 
                            blockIdx % 2 === 1 ? <strong key={blockIdx} className="text-slate-200">{textBlock}</strong> : textBlock
                          )}
                        </li>
                      ))}
                    </ul>
                  );
                }
                return (
                  <p key={idx} className="text-xs text-slate-400 whitespace-pre-line leading-relaxed">
                    {para.split("**").map((textBlock, blockIdx) => 
                      blockIdx % 2 === 1 ? <strong key={blockIdx} className="text-slate-200">{textBlock}</strong> : textBlock
                    )}
                  </p>
                );
              })}
            </div>
          )}

          {activeTab === "transcript" && (
            <div className="space-y-3 font-sans text-xs">
              {result.transcript_text.split("\n").map((line, idx) => {
                const match = line.match(/^([^:]+):(.*)$/);
                if (match) {
                  return (
                    <div key={idx} className="flex flex-col gap-0.5 border-b border-slate-805/30 pb-2">
                      <span className="font-mono text-indigo-400 font-semibold text-[10px] tracking-wide uppercase">
                        {match[1].trim()}
                      </span>
                      <p className="text-slate-300 text-xs leading-relaxed">{match[2].trim()}</p>
                    </div>
                  );
                }
                return <p key={idx} className="text-slate-400 text-xs italic">{line}</p>;
              })}
            </div>
          )}

          {activeTab === "speakers" && (
            <div className="flex flex-col gap-3">
              <span className="text-xs text-slate-400">Total speakers identified inside meeting stream bounds:</span>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-1">
                {result.speakers.map((speaker, idx) => (
                  <div key={idx} className="bg-slate-950/60 border border-slate-800 p-3.5 rounded-xl flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-rose-500 flex items-center justify-center text-white text-[10px] font-mono font-bold">
                        S{idx + 1}
                      </div>
                      <div>
                        <span className="text-xs font-semibold text-white block">{speaker}</span>
                        <span className="text-[10px] text-slate-500 font-mono">Diarized Segment Node #{idx + 1}</span>
                      </div>
                    </div>
                    <span className="text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                      Matching
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Export Compilation & Action Downloader Tray */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-indigo-950/10 border border-indigo-550/10 rounded-xl p-4 mt-2">
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold text-indigo-200">Clarify Compilation Exports Ready</p>
          <span className="text-[10px] text-slate-400 font-mono">Download local copies of dialogue maps, summaries, or structured doc files.</span>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => handleTriggerDownload("docx")}
            className="flex items-center gap-1.5 text-xs font-medium px-3.5 py-2 bg-slate-950 hover:bg-slate-900 border border-slate-800 hover:border-slate-705 text-slate-300 hover:text-white rounded-lg transition"
          >
            <Download className="w-3.5 h-3.5 text-blue-400" />
            Download Word (DOCX)
          </button>
          <button
            onClick={() => handleTriggerDownload("md")}
            className="flex items-center gap-1.5 text-xs font-medium px-3.5 py-2 bg-slate-950 hover:bg-slate-900 border border-slate-800 hover:border-slate-705 text-slate-300 hover:text-white rounded-lg transition"
          >
            <Download className="w-3.5 h-3.5 text-rose-400" />
            Download Briefing (MarkDown)
          </button>
          <button
            onClick={() => handleTriggerDownload("txt")}
            className="flex items-center gap-1.5 text-xs font-medium px-3.5 py-2 bg-slate-950 hover:bg-slate-900 border border-slate-800 hover:border-slate-705 text-slate-300 hover:text-white rounded-lg transition"
          >
            <Download className="w-3.5 h-3.5 text-indigo-400" />
            Download Transcript (TXT)
          </button>
        </div>
      </div>
    </div>
  );
}
