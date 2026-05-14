"""NoteAgent CLI — typer application."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.status import Status

from noteagent import get_version
from noteagent.models import AppConfig

app = typer.Typer(
    name="noteagent",
    help="Speech-to-text note-taking agent with live transcription and LLM summarization.",
    no_args_is_help=True,
)
console = Console()

_BATCH_MEDIA_SUFFIXES = {".mp3", ".mp4"}
_QUALITY_LEVELS = {"fast", "balanced", "accurate"}


def _resolve_session_path(config: AppConfig, session_path: Path) -> Path:
    """Resolve a session ID or path to a full session directory path."""
    if session_path.exists() and session_path.is_dir():
        return session_path
    # Treat as a session ID — look in the storage directory
    resolved = config.storage_path.expanduser() / "sessions" / str(session_path)
    if resolved.exists():
        return resolved
    # Fall through — return as-is so load_session gives a clear error
    return session_path


def _is_session_directory(path: Path) -> bool:
    """Return True when a directory looks like a NoteAgent session."""
    return path.is_dir() and (path / "metadata.json").exists()


def _collect_batch_media_files(folder: Path) -> list[Path]:
    """Collect supported media files from a folder (non-recursive)."""
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _BATCH_MEDIA_SUFFIXES
    )


@app.command()
def record(
    device: Optional[str] = typer.Option(None, "--device", "-d", help="Audio device name or index from 'noteagent devices' (mic in meeting mode)"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="Override storage path for this session"),
    live_transcript: bool = typer.Option(True, "--live-transcript/--no-live-transcript", help="Show live transcript"),
    model: str = typer.Option("base.en", "--model", "-m", help="Whisper model size"),
    meeting: bool = typer.Option(False, "--meeting", help="Dual-channel meeting mode (mic + system audio)"),
    system_device: Optional[str] = typer.Option(None, "--system-device", help="System audio device name or index for meeting mode (e.g. BlackHole 2ch)"),
    max_duration: int = typer.Option(3600, "--max-duration", help="Maximum recording duration in seconds (default: 3600 = 60 min)"),
) -> None:
    """Start recording with live transcript."""
    from noteagent.storage import create_session, load_config, save_transcript

    from noteagent.audio import resolve_device

    config = load_config()
    try:
        mic_device = resolve_device(device) or config.default_device
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    if meeting:
        try:
            sys_device = resolve_device(system_device) or "BlackHole 2ch"
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        _record_meeting(config, mic_device, sys_device, output_dir, live_transcript, model, max_duration)
    else:
        _record_single(config, mic_device, output_dir, live_transcript, model, max_duration)


def _record_single(
    config: AppConfig, device: str, output_dir: Optional[Path],
    live_transcript: bool, model: str, max_duration: int,
) -> None:
    """Single-channel recording."""
    from noteagent.audio import Recorder, StreamReader
    from noteagent.storage import create_session, save_meeting_preview, save_transcript
    from noteagent.transcript import LiveTranscriber, transcribe_file

    session = create_session(config, output_dir=output_dir, device_name=device)
    console.print(f"[bold green]Recording session:[/] {session.metadata.session_id}")
    console.print(f"[dim]Output: {session.path}[/]")
    console.print(f"[dim]Max duration: {max_duration // 60} minutes[/]")
    console.print("[yellow]Press Ctrl+C to stop recording.[/]\n")

    recorder = Recorder(device_name=device, sample_rate=config.sample_rate)
    recorder.start(session.audio_path, device_name=device)

    start_time = time.monotonic()
    stopped_reason = "user"

    if live_transcript:
        stream = StreamReader(device_name=device, sample_rate=config.sample_rate)
        transcriber = LiveTranscriber(model_size=model, language=config.language, sample_rate=config.sample_rate)
        silence_prompted = False

        live_display = Live(Panel("[dim]Listening...[/]", title="Live Transcript"), console=console, refresh_per_second=2)
        live_display.start()
        try:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= max_duration:
                    stopped_reason = "max_duration"
                    break

                samples = stream.read_chunk()
                if samples:
                    new_segs = transcriber.feed(samples)
                    if new_segs:
                        silence_prompted = False
                        transcript = transcriber.get_transcript()
                        recent = transcript.segments[-20:]
                        text = Text()
                        if len(transcript.segments) > 20:
                            text.append(f"... {len(transcript.segments) - 20} earlier segments ...\n", style="dim")
                        for seg in recent:
                            text.append(f"[{seg.start:.1f}s] ", style="bold cyan")
                            text.append(seg.text.strip() + "\n")
                        live_display.update(Panel(text, title="Live Transcript"))

                if transcriber.silence_seconds >= 300 and not silence_prompted:
                    silence_prompted = True
                    live_display.stop()
                    if typer.confirm("\n5 minutes of silence detected. Stop recording?"):
                        stopped_reason = "silence"
                        break
                    live_display.start()

                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            live_display.stop()

        stream.stop()
        recorder.stop()
    else:
        stream = StreamReader(device_name=device, sample_rate=config.sample_rate)
        silence_start: Optional[float] = None
        silence_prompted = False

        try:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= max_duration:
                    stopped_reason = "max_duration"
                    break

                samples = stream.read_chunk()
                if samples:
                    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                    if rms < 1e-4:
                        if silence_start is None:
                            silence_start = time.monotonic()
                        elif time.monotonic() - silence_start >= 300 and not silence_prompted:
                            silence_prompted = True
                            if typer.confirm("\n5 minutes of silence detected. Stop recording?"):
                                stopped_reason = "silence"
                                break
                    else:
                        silence_start = None
                        silence_prompted = False

                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

        stream.stop()
        recorder.stop()

    if stopped_reason == "max_duration":
        console.print("\n[bold yellow]Recording stopped — maximum duration reached.[/]")
    elif stopped_reason == "silence":
        console.print("\n[bold yellow]Recording stopped — prolonged silence.[/]")
    else:
        console.print("\n[bold red]Recording stopped.[/]")

    with Status("[yellow]Running post-recording transcription...[/]", console=console, spinner="dots"):
        transcript = transcribe_file(session.audio_path, model_size=model, language=config.language)
        save_transcript(session, transcript)
    console.print(f"[green]Transcript saved ({len(transcript.segments)} segments)[/]")


def _record_meeting(
    config: AppConfig, mic_device: str, system_device: str,
    output_dir: Optional[Path], live_transcript: bool, model: str, max_duration: int,
) -> None:
    """Dual-channel meeting recording."""
    from noteagent.audio import DualRecorder, DualStreamReader
    from noteagent.storage import create_session, save_transcript
    from noteagent.transcript import MeetingLiveTranscriber, transcribe_meeting

    session = create_session(
        config,
        output_dir=output_dir,
        device_name=mic_device,
        recording_mode="meeting",
        system_device_name=system_device,
    )
    console.print(f"[bold green]Meeting recording:[/] {session.metadata.session_id}")
    console.print(f"  [cyan]Mic:[/]    {mic_device}")
    console.print(f"  [cyan]System:[/] {system_device}")
    console.print(f"[dim]Output: {session.path}[/]")
    console.print(f"[dim]Max duration: {max_duration // 60} minutes[/]")
    console.print("[yellow]Press Ctrl+C to stop recording.[/]\n")

    recorder = DualRecorder(
        mic_device=mic_device,
        system_device=system_device,
        sample_rate=config.sample_rate,
    )
    recorder.start(session.mic_audio_path, session.system_audio_path)

    start_time = time.monotonic()
    stopped_reason = "user"

    if live_transcript:
        dual_stream = DualStreamReader(
            mic_device=mic_device,
            system_device=system_device,
            sample_rate=config.sample_rate,
        )
        transcriber = MeetingLiveTranscriber(
            model_size=model,
            language=config.language,
            sample_rate=config.sample_rate,
        )
        silence_prompted = False

        live_display = Live(Panel("[dim]Listening...[/]", title="Meeting Transcript"), console=console, refresh_per_second=2)
        live_display.start()
        try:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= max_duration:
                    stopped_reason = "max_duration"
                    break

                mic_samples = dual_stream.read_mic_chunk()
                sys_samples = dual_stream.read_system_chunk()
                new_segs = []
                if mic_samples:
                    new_segs.extend(transcriber.feed_mic(mic_samples))
                if sys_samples:
                    new_segs.extend(transcriber.feed_system(sys_samples))
                if new_segs:
                    silence_prompted = False
                    transcript = transcriber.get_transcript()
                    recent = transcript.segments[-20:]
                    text = Text()
                    if len(transcript.segments) > 20:
                        text.append(f"... {len(transcript.segments) - 20} earlier segments ...\n", style="dim")
                    for seg in recent:
                        label = f"[{seg.speaker}]" if seg.speaker else ""
                        color = "bold green" if seg.speaker == "You" else "bold magenta"
                        text.append(f"[{seg.start:.1f}s] {label} ", style=color)
                        text.append(seg.text.strip() + "\n")
                    live_display.update(Panel(text, title="Meeting Transcript"))

                if transcriber.silence_seconds >= 300 and not silence_prompted:
                    silence_prompted = True
                    live_display.stop()
                    if typer.confirm("\n5 minutes of silence detected. Stop recording?"):
                        stopped_reason = "silence"
                        break
                    live_display.start()

                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            live_display.stop()

        dual_stream.stop()
        recorder.stop()
    else:
        dual_stream = DualStreamReader(
            mic_device=mic_device,
            system_device=system_device,
            sample_rate=config.sample_rate,
        )
        silence_start: Optional[float] = None
        silence_prompted = False

        try:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= max_duration:
                    stopped_reason = "max_duration"
                    break

                mic_samples = dual_stream.read_mic_chunk()
                sys_samples = dual_stream.read_system_chunk()
                any_audio = False
                for samples in [mic_samples, sys_samples]:
                    if samples:
                        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                        if rms >= 1e-4:
                            any_audio = True
                            break

                if any_audio:
                    silence_start = None
                    silence_prompted = False
                else:
                    if silence_start is None:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start >= 300 and not silence_prompted:
                        silence_prompted = True
                        if typer.confirm("\n5 minutes of silence detected. Stop recording?"):
                            stopped_reason = "silence"
                            break

                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

        dual_stream.stop()
        recorder.stop()

    if stopped_reason == "max_duration":
        console.print("\n[bold yellow]Recording stopped — maximum duration reached.[/]")
    elif stopped_reason == "silence":
        console.print("\n[bold yellow]Recording stopped — prolonged silence.[/]")
    else:
        console.print("\n[bold red]Recording stopped.[/]")

    with Status("[yellow]Running dual-channel transcription...[/]", console=console, spinner="dots"):
        transcript = transcribe_meeting(
            session.mic_audio_path,
            session.system_audio_path,
            model_size=model,
            language=config.language,
        )
        save_transcript(session, transcript)
        save_meeting_preview(session)
    console.print(f"[green]Meeting transcript saved ({len(transcript.segments)} segments)[/]")


@app.command()
def transcribe(
    audio_file: Path = typer.Argument(..., help="Session ID, audio file path, or session directory"),
    model: str = typer.Option("small.en", "--model", "-m", help="Whisper model: tiny.en, base.en, small.en, medium.en, large-v3"),
    language: str = typer.Option("auto", "--language", "-l", help="Audio language (use 'auto' for detection)"),
    quality: str = typer.Option("balanced", "--quality", "-q", help="Decoding quality profile: fast, balanced, accurate"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output transcript file"),
    summarize_imports: bool = typer.Option(
        True,
        "--summarize/--no-summarize",
        help="For folder input, generate summaries for each imported file",
    ),
    style: str = typer.Option(
        "general",
        "--style",
        "-s",
        help="Summary style for folder imports: general, meeting, lecture",
    ),
) -> None:
    """Transcribe an existing audio file."""
    from noteagent.storage import (
        create_session,
        load_config,
        load_session,
        save_preview_media,
        save_summary,
        save_transcript,
        save_transcript_version,
    )
    from noteagent.summary import summarize as do_summarize
    from noteagent.transcript import load_model, transcribe_file

    config = load_config()
    resolved = _resolve_session_path(config, audio_file)

    if quality not in _QUALITY_LEVELS:
        console.print(f"[red]Invalid --quality '{quality}'. Choose from: fast, balanced, accurate.[/]")
        raise typer.Exit(1)

    selected_language: Optional[str] = None if language.lower() == "auto" else language

    if resolved.is_dir() and not _is_session_directory(resolved):
        media_files = _collect_batch_media_files(resolved)
        if not media_files:
            console.print(f"[red]No .mp3 or .mp4 files found in: {resolved}[/]")
            raise typer.Exit(1)

        if output and output.suffix:
            console.print("[red]When input is a folder, --output must be a directory path.[/]")
            raise typer.Exit(1)

        output_root = output or config.storage_path
        whisper_model = load_model(model)
        results: list[tuple[str, str, int, str]] = []

        for media_path in media_files:
            with Status(f"[yellow]Transcribing {media_path.name}...[/]", console=console, spinner="dots"):
                transcript = transcribe_file(
                    media_path,
                    model=whisper_model,
                    model_size=model,
                    language=selected_language,
                    quality=quality,
                )

            session = create_session(
                config,
                output_dir=output_root,
                device_name=f"import:{media_path.name}",
                recording_mode="import",
                source_file=str(media_path),
            )
            save_preview_media(session, media_path)
            save_transcript(session, transcript)
            save_transcript_version(session, transcript, model_label=model, set_default_if_missing=False)

            summary_state = "no"
            if summarize_imports:
                with Status(f"[yellow]Summarizing {media_path.name}...[/]", console=console, spinner="dots"):
                    summary = do_summarize(transcript, style=style, provider=config.summary_provider)
                save_summary(session, summary)
                summary_state = "yes"

            results.append((media_path.name, session.metadata.session_id, len(transcript.segments), summary_state))

        table = Table(title=f"Imported {len(results)} files")
        table.add_column("File", style="cyan")
        table.add_column("Session", style="green")
        table.add_column("Segments", style="yellow")
        table.add_column("Summary", style="magenta")
        for name, session_id, segment_count, summary_state in results:
            table.add_row(name, session_id, str(segment_count), summary_state)
        console.print(table)
        return

    session_dir: Optional[Path] = None
    if resolved.is_dir():
        session_dir = resolved
        # Session directory — find the audio file
        for name in ("audio.wav", "mic.wav"):
            candidate = resolved / name
            if candidate.exists():
                audio_file = candidate
                break
        else:
            console.print(f"[red]No audio file found in session: {resolved}[/]")
            raise typer.Exit(1)
    else:
        audio_file = resolved

    if not audio_file.exists():
        console.print(f"[red]File not found: {audio_file}[/]")
        raise typer.Exit(1)

    with Status(f"[yellow]Transcribing {audio_file.name}...[/]", console=console, spinner="dots"):
        transcript = transcribe_file(audio_file, model_size=model, language=selected_language, quality=quality)

    if session_dir and not output:
        session = load_session(session_dir)
        model_json, model_txt = save_transcript_version(session, transcript, model_label=model)
        console.print(
            f"[green]Model transcript saved ({len(transcript.segments)} segments, {transcript.duration:.0f}s):[/] "
            f"{model_json.name}, {model_txt.name}"
        )
    elif output:
        import json
        output.write_text(json.dumps(transcript.model_dump(), indent=2))
        console.print(f"[green]Transcript saved to {output}[/]")
    else:
        for seg in transcript.segments:
            console.print(f"[cyan][{seg.start:.1f}s - {seg.end:.1f}s][/] {seg.text.strip()}")


@app.command()
def summarize(
    session_path: Path = typer.Argument(..., help="Session ID or path to session directory"),
    style: str = typer.Option("general", "--style", "-s", help="Summary style: general, meeting, lecture"),
) -> None:
    """Summarize a session transcript using LLM."""
    from noteagent.storage import load_config, load_session, save_summary
    from noteagent.summary import summarize as do_summarize

    config = load_config()
    session_path = _resolve_session_path(config, session_path)
    session = load_session(session_path)

    if not session.transcript:
        console.print("[red]No transcript found for this session.[/]")
        raise typer.Exit(1)

    with Status("[yellow]Generating summary...[/]", console=console, spinner="dots"):
        summary = do_summarize(session.transcript, style=style, provider=config.summary_provider)
        save_summary(session, summary)

    console.print(Panel(summary, title="Summary", border_style="green"))


@app.command()
def export(
    session_path: Path = typer.Argument(..., help="Session ID or path to session directory"),
    fmt: str = typer.Option("markdown", "--format", "-f", help="Export format: markdown, text, json, srt, vtt, pdf"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> None:
    """Export a session to a specific format."""
    from noteagent.export import export_session
    from noteagent.storage import load_config, load_session

    config = load_config()
    session_path = _resolve_session_path(config, session_path)
    session = load_session(session_path)
    path = export_session(session, fmt=fmt, output_path=output)
    console.print(f"[green]Exported to {path}[/]")


@app.command(name="download-model")
def download_model_command(
    size: str = typer.Argument("base.en", help="Model size, e.g. tiny.en, base.en, small, medium, large-v3"),
) -> None:
    """Download a ggml whisper.cpp model from HuggingFace."""
    from noteagent.model_download import cli_download, known_models

    if size not in known_models():
        console.print(f"[red]Unknown model: {size}[/]")
        console.print(f"Known: {', '.join(known_models())}")
        raise typer.Exit(1)

    try:
        cli_download(size)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


@app.command()
def devices() -> None:
    """List available audio input devices."""
    from noteagent.audio import list_devices

    device_list = list_devices()
    table = Table(title="Audio Input Devices")
    table.add_column("#", style="cyan")
    table.add_column("Device Name", style="green")

    for i, name in enumerate(device_list):
        table.add_row(str(i), name)

    console.print(table)


@app.command()
def config(
    storage_path: Optional[str] = typer.Option(None, "--storage-path", help="Set default storage path"),
    device: Optional[str] = typer.Option(None, "--device", help="Set default audio device"),
    show: bool = typer.Option(False, "--show", help="Show current config"),
) -> None:
    """View or update configuration."""
    from noteagent.storage import load_config, save_config

    cfg = load_config()

    if show or (storage_path is None and device is None):
        table = Table(title="NoteAgent Configuration")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("storage_path", str(cfg.storage_path))
        table.add_row("default_device", cfg.default_device)
        table.add_row("sample_rate", str(cfg.sample_rate))
        table.add_row("whisper_model", cfg.whisper_model)
        table.add_row("language", cfg.language)
        table.add_row("summary_provider", cfg.summary_provider)
        table.add_row("summary_style", cfg.summary_style)
        console.print(table)
        return

    if storage_path:
        cfg.storage_path = Path(storage_path)
    if device:
        cfg.default_device = device

    save_config(cfg)
    console.print("[green]Configuration saved.[/]")


@app.command()
def sessions() -> None:
    """List past recording sessions."""
    from noteagent.storage import list_sessions, load_config

    cfg = load_config()
    session_list = list_sessions(cfg)

    if not session_list:
        console.print("[dim]No sessions found.[/]")
        return

    table = Table(title="Recording Sessions")
    table.add_column("Session", style="cyan")
    table.add_column("Date", style="green")
    table.add_column("Duration", style="yellow")
    table.add_column("Transcript", style="magenta")
    table.add_column("Summary", style="blue")

    for s in session_list:
        dur = f"{s.metadata.duration:.0f}s" if s.metadata.duration else "-"
        has_t = "yes" if s.transcript else "no"
        has_s = "yes" if s.summary else "no"
        table.add_row(
            s.metadata.session_id,
            f"{s.metadata.created_at:%Y-%m-%d %H:%M}",
            dur,
            has_t,
            has_s,
        )

    console.print(table)


_PID_FILE = Path.home() / ".config" / "noteagent" / "serve.pid"


@app.command()
def serve(
    port: int = typer.Option(8765, "--port", "-p", help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser automatically"),
) -> None:
    """Start the web UI."""
    import os
    import sys
    import atexit
    import uvicorn

    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: _PID_FILE.unlink(missing_ok=True))

    from noteagent import get_version

    url = f"http://127.0.0.1:{port}"
    console.print(
        f"[bold green]Starting NoteAgent[/] [dim]v{get_version()}[/]  "
        f"[bold green]at[/] {url}"
    )
    console.print(f"[dim]Python: {sys.executable}[/]")

    if not no_browser:
        import webbrowser
        import threading
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    uvicorn.run("noteagent.server:app", host="127.0.0.1", port=port, log_level="info")


@app.command()
def stop() -> None:
    """Stop a running web UI server."""
    import os
    import signal

    if not _PID_FILE.exists():
        console.print("[yellow]No running server found (PID file missing).[/]")
        raise typer.Exit(1)

    pid = int(_PID_FILE.read_text().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Server (PID {pid}) stopped.[/]")
    except ProcessLookupError:
        console.print(f"[yellow]Server process {pid} not running.[/]")
    finally:
        _PID_FILE.unlink(missing_ok=True)


@app.command()
def version() -> None:
    """Show NoteAgent version."""
    console.print(f"NoteAgent v{get_version()}")


@app.command(name="setup-check")
def setup_check() -> None:
    """Verify that NoteAgent is installed correctly."""
    import shutil

    ok = True

    # 1. Rust audio extension
    try:
        import noteagent_audio  # type: ignore[import-not-found]
        console.print("[green]✔[/] Rust audio extension loaded")
    except ImportError:
        console.print("[red]✘[/] Rust audio extension not found — run: cd noteagent-audio && maturin develop")
        ok = False

    # 2. Whisper model
    model_path = Path(__file__).resolve().parent.parent.parent / "models" / "base.en.pt"
    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        console.print(f"[green]✔[/] Whisper model found ({size_mb:.0f} MB)")
    else:
        console.print(f"[red]✘[/] Whisper model not found at {model_path} — run: make model")
        ok = False

    # 3. Audio devices
    try:
        from noteagent.audio import list_devices
        devs = list_devices()
        console.print(f"[green]✔[/] Audio devices: {len(devs)} found")
        for d in devs:
            marker = "●" if "blackhole" in d.lower() else "○"
            console.print(f"    {marker} {d}")
    except Exception as e:
        console.print(f"[red]✘[/] Cannot list audio devices: {e}")
        ok = False

    # 4. GitHub CLI + Copilot (optional)
    gh = shutil.which("gh")
    if gh:
        console.print("[green]✔[/] GitHub CLI found")
    else:
        console.print("[yellow]○[/] GitHub CLI not found (optional — needed for LLM summarization)")

    # 5. Config
    from noteagent.storage import load_config
    cfg = load_config()
    console.print(f"[green]✔[/] Config loaded (storage: {cfg.storage_path})")

    console.print()
    if ok:
        console.print("[bold green]All checks passed — NoteAgent is ready![/]")
    else:
        console.print("[bold red]Some checks failed — see above for fix instructions.[/]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Authentication & Token Management
# ---------------------------------------------------------------------------

@app.command(name="token-generate")
def token_generate(
    name: str = typer.Argument(..., help="Human-readable name for this token (e.g., 'laptop', 'mobile')"),
    role: str = typer.Option("admin", help="Role: 'admin' or 'read-only'"),
    expires_days: Optional[int] = typer.Option(None, help="Days until expiration (optional)"),
) -> None:
    """Generate a new authentication token."""
    from datetime import datetime, timedelta
    from noteagent.auth import create_auth_token
    from noteagent.storage import load_config_extended, save_config_extended
    
    # Calculate expiration
    expires_at = None
    if expires_days is not None:
        expires_at = datetime.now() + timedelta(days=expires_days)
    
    # Create token
    auth_token = create_auth_token(name, role, expires_at)
    
    # Load config and add token
    config = load_config_extended()
    config.auth.tokens.append(auth_token)
    save_config_extended(config)
    
    # Display
    console.print(f"\n[bold green]✓ Token created successfully[/]")
    console.print(f"\n[bold]Token:[/] {auth_token.token}")
    console.print(f"[dim]Name:[/] {auth_token.name}")
    console.print(f"[dim]Role:[/] {auth_token.role}")
    if expires_at:
        console.print(f"[dim]Expires:[/] {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
    console.print(f"\n[yellow]⚠ Save this token securely - it cannot be recovered![/]\n")


@app.command(name="token-list")
def token_list() -> None:
    """List all authentication tokens."""
    from noteagent.storage import load_config_extended
    from rich.table import Table
    
    config = load_config_extended()
    
    if not config.auth.tokens:
        console.print("[yellow]No tokens configured[/]")
        return
    
    table = Table(title="Authentication Tokens")
    table.add_column("Name", style="cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Created", style="dim")
    table.add_column("Expires", style="dim")
    table.add_column("Token Preview", style="dim")
    
    for token in config.auth.tokens:
        created = token.created_at.strftime("%Y-%m-%d") if token.created_at else "N/A"
        expires = token.expires_at.strftime("%Y-%m-%d") if token.expires_at else "Never"
        preview = token.token[:20] + "..." if len(token.token) > 20 else token.token
        
        table.add_row(
            token.name,
            token.role,
            created,
            expires,
            preview,
        )
    
    console.print(table)
    console.print(f"\n[dim]Auth enabled: {config.auth.enabled}[/]")


@app.command(name="token-revoke")
def token_revoke(
    name: str = typer.Argument(..., help="Name of the token to revoke"),
) -> None:
    """Revoke an authentication token by name."""
    from noteagent.storage import load_config_extended, save_config_extended
    
    config = load_config_extended()
    
    # Find and remove token
    original_count = len(config.auth.tokens)
    config.auth.tokens = [t for t in config.auth.tokens if t.name != name]
    
    if len(config.auth.tokens) == original_count:
        console.print(f"[red]✗ Token '{name}' not found[/]")
        raise typer.Exit(1)
    
    save_config_extended(config)
    console.print(f"[green]✓ Token '{name}' revoked successfully[/]")


@app.command(name="token-test")
def token_test(
    token: str = typer.Argument(..., help="Token to test"),
) -> None:
    """Test if a token is valid."""
    from noteagent.auth import validate_token
    from noteagent.storage import load_config_extended
    
    config = load_config_extended()
    
    auth_token = validate_token(token, config.auth.tokens)
    
    if auth_token:
        console.print(f"[green]✓ Token is valid[/]")
        console.print(f"[dim]Name:[/] {auth_token.name}")
        console.print(f"[dim]Role:[/] {auth_token.role}")
        if auth_token.expires_at:
            console.print(f"[dim]Expires:[/] {auth_token.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        console.print(f"[red]✗ Token is invalid or expired[/]")
        raise typer.Exit(1)


@app.command(name="auth-enable")
def auth_enable() -> None:
    """Enable authentication."""
    from noteagent.storage import load_config_extended, save_config_extended
    
    config = load_config_extended()
    config.auth.enabled = True
    save_config_extended(config)
    
    console.print("[green]✓ Authentication enabled[/]")
    
    if not config.auth.tokens:
        console.print("[yellow]⚠ No tokens configured. Run 'noteagent token-generate' to create one.[/]")


@app.command(name="auth-disable")
def auth_disable() -> None:
    """Disable authentication."""
    from noteagent.storage import load_config_extended, save_config_extended
    
    config = load_config_extended()
    config.auth.enabled = False
    save_config_extended(config)
    
    console.print("[green]✓ Authentication disabled[/]")


if __name__ == "__main__":
    app()
