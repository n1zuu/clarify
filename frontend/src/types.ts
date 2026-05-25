export enum AppState {
  IDLE = "IDLE",
  RECORDING = "RECORDING",
  PROCESSING = "PROCESSING",
  DONE = "DONE",
  ERROR = "ERROR",
}

export interface ProcessingResult {
  audio_path: string;
  transcript_path: string;
  summary_path: string;
  export_path: string;
  transcript_text: string;
  summary_text: string;
  speakers: string[];
  duration_seconds: number;
  error: string | null;
}

export type ExportFormat = "pdf" | "docx" | "txt" | "all";

export interface EngineSettings {
  output_dir: string;
  export_format: ExportFormat;
  diarization: boolean;
  hf_token: string;
  ollama_model: string;
  ollama_num_ctx: number;
  server_url: string;
  remote_mode: boolean;
}

export interface ProgressPayload {
  stage: string;
  pct: number;
  msg: string;
}

export interface StartupAlerts {
  ollamaRunning: boolean | null; // null = checking, boolean = result
  cudaAvailable: boolean | null;
  outputWritable: boolean | null;
  checked: boolean;
}
