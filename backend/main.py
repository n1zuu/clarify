"""
MeetScribe - Main Entry Point
Launches the backend engine. Connect your GUI by importing MeetScribeEngine
or by running this file directly for a CLI headless mode.
"""

import sys
import argparse
from core.engine import MeetScribeEngine


def main():
    parser = argparse.ArgumentParser(
        description="Clarify - AI-powered meeting recorder, transcriber, and summarizer"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless/CLI mode (no GUI)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Directory to save outputs (default: ./output)",
    )
    parser.add_argument(
        "--export-format",
        type=str,
        choices=["pdf", "docx", "txt", "all"],
        default="docx",
        help="Export format for the meeting summary",
    )
    parser.add_argument(
        "--no-diarization",
        action="store_true",
        help="Disable speaker diarization (faster, but no speaker labels)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Audio device name to capture from (uses default loopback if omitted)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio loopback devices and exit",
    )

    args = parser.parse_args()

    engine = MeetScribeEngine()

    if args.list_devices:
        devices = engine.list_audio_devices()
        print("\nAvailable audio loopback devices:")
        for i, d in enumerate(devices):
            print(f"  [{i}] {d}")
        sys.exit(0)

    if args.headless:
        _run_headless(engine, args)
    else:
        # GUI mode: engine is imported and controlled by the GUI layer
        print("MeetScribe engine ready. Connect your GUI to core.engine.MeetScribeEngine.")
        print("Run with --headless for CLI mode.")


def _run_headless(engine: "MeetScribeEngine", args):
    """Simple CLI mode for testing without a GUI."""
    import time

    print("=== MeetScribe Headless Mode ===")
    print(f"Output dir   : {args.output_dir}")
    print(f"Export format: {args.export_format}")
    print(f"Diarization  : {not args.no_diarization}")
    print()

    engine.configure(
        output_dir=args.output_dir,
        export_format=args.export_format,
        diarization=not args.no_diarization,
        device_name=args.device,
    )

    print("Starting recording... Press Ctrl+C to stop and process.\n")
    engine.start_recording()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping recording...")

    result = engine.stop_and_process()

    print(f"\n✓ Transcript saved : {result.transcript_path}")
    print(f"✓ Summary saved    : {result.summary_path}")
    print(f"✓ Export saved     : {result.export_path}")
    print(f"✓ Audio saved      : {result.audio_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
