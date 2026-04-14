"""Multi-format export for NoteAgent sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from noteagent.models import Session, Transcript


def export_markdown(session: Session, output_path: Optional[Path] = None) -> Path:
    """Export session as a Markdown file."""
    path = output_path or (session.path / "export.md")

    lines = [
        f"# Session: {session.metadata.session_id}",
        "",
        f"**Date:** {session.metadata.created_at:%Y-%m-%d %H:%M}",
        f"**Device:** {session.metadata.device_name}",
    ]

    if session.metadata.duration:
        lines.append(f"**Duration:** {session.metadata.duration:.1f}s")
    lines.append("")

    if session.summary:
        lines.extend(["## Summary", "", session.summary, ""])

    if session.transcript:
        lines.extend(["## Transcript", ""])
        for seg in session.transcript.segments:
            ts = _format_timestamp(seg.start)
            speaker = f" **{seg.speaker}:**" if seg.speaker else ""
            lines.append(f"**[{ts}]**{speaker} {seg.text.strip()}")
            lines.append("")

    path.write_text("\n".join(lines))
    return path


def export_text(session: Session, output_path: Optional[Path] = None) -> Path:
    """Export session as a plain text file."""
    path = output_path or (session.path / "export.txt")

    lines = [
        f"Session: {session.metadata.session_id}",
        f"Date: {session.metadata.created_at:%Y-%m-%d %H:%M}",
        "",
    ]

    if session.summary:
        lines.extend(["--- Summary ---", "", session.summary, ""])

    if session.transcript:
        lines.extend(["--- Transcript ---", ""])
        lines.append(session.transcript.full_text)

    path.write_text("\n".join(lines))
    return path


def export_json(session: Session, output_path: Optional[Path] = None) -> Path:
    """Export session as structured JSON."""
    import json

    path = output_path or (session.path / "export.json")

    data = {
        "session_id": session.metadata.session_id,
        "created_at": session.metadata.created_at.isoformat(),
        "device": session.metadata.device_name,
        "duration": session.metadata.duration,
    }

    if session.transcript:
        data["transcript"] = session.transcript.model_dump()
    if session.summary:
        data["summary"] = session.summary

    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def export_srt(session: Session, output_path: Optional[Path] = None) -> Path:
    """Export transcript as SRT subtitles."""
    if not session.transcript:
        raise ValueError("No transcript available for SRT export")

    path = output_path or (session.path / "export.srt")
    lines = []

    for i, seg in enumerate(session.transcript.segments, 1):
        start_ts = _format_srt_timestamp(seg.start)
        end_ts = _format_srt_timestamp(seg.end)
        speaker = f"[{seg.speaker}] " if seg.speaker else ""
        lines.append(str(i))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"{speaker}{seg.text.strip()}")
        lines.append("")

    path.write_text("\n".join(lines))
    return path


def export_vtt(session: Session, output_path: Optional[Path] = None) -> Path:
    """Export transcript as WebVTT subtitles."""
    if not session.transcript:
        raise ValueError("No transcript available for VTT export")

    path = output_path or (session.path / "export.vtt")
    lines = ["WEBVTT", ""]

    for seg in session.transcript.segments:
        start_ts = _format_vtt_timestamp(seg.start)
        end_ts = _format_vtt_timestamp(seg.end)
        speaker = f"[{seg.speaker}] " if seg.speaker else ""
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"{speaker}{seg.text.strip()}")
        lines.append("")

    path.write_text("\n".join(lines))
    return path


def export_pdf(session: Session, output_path: Optional[Path] = None) -> Path:
    """Export session as a PDF file."""
    from fpdf import FPDF

    path = output_path or (session.path / "export.pdf")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Session: {session.metadata.session_id}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Date: {session.metadata.created_at:%Y-%m-%d %H:%M}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Device: {session.metadata.device_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    if session.summary:
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, session.summary)
        pdf.ln(5)

    if session.transcript:
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Transcript", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)

        for seg in session.transcript.segments:
            ts = _format_timestamp(seg.start)
            speaker = f" {seg.speaker}:" if seg.speaker else ""
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(20, 5, f"[{ts}]{speaker}")
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, seg.text.strip())

    pdf.output(str(path))
    return path


EXPORTERS = {
    "markdown": export_markdown,
    "md": export_markdown,
    "text": export_text,
    "txt": export_text,
    "json": export_json,
    "srt": export_srt,
    "vtt": export_vtt,
    "pdf": export_pdf,
}


def export_session(
    session: Session,
    fmt: str = "markdown",
    output_path: Optional[Path] = None,
) -> Path:
    """Export a session in the given format."""
    exporter = EXPORTERS.get(fmt.lower())
    if not exporter:
        raise ValueError(f"Unknown export format: {fmt}. Available: {', '.join(EXPORTERS)}")
    return exporter(session, output_path)


def _format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm for SRT."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm for VTT."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
