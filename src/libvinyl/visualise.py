"""Visualisation of split points and dropped sections."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from .audio import TrackSegment, get_wav_duration
from .ui import console, format_duration


# Alternating track colours
_TRACK_COLOURS = ["cyan", "bright_blue"]
_DROP_COLOUR = "red"
_GAP_COLOUR = "bright_black"


def visualise_splits(
    wav_files: list[Path],
    segments: list[TrackSegment],
    track_names: list[str],
    dropped_indices: list[int] | None = None,
) -> None:
    """Render a visual map of the splitting plan.

    Shows each source file on its own line with a coloured bar indicating
    track assignments, cut points, dropped sections, and timing details.
    """
    if not wav_files or not segments:
        return

    dropped = set(dropped_indices or [])

    # Group segments by source file, preserving file order
    file_durations = {f: get_wav_duration(f) for f in wav_files}
    segments_by_file: dict[Path, list[tuple[int, TrackSegment]]] = {f: [] for f in wav_files}
    for i, seg in enumerate(segments):
        if seg.source_file in segments_by_file:
            segments_by_file[seg.source_file].append((i, seg))

    width = max(40, console.width - 2)

    for wav_file in wav_files:
        file_dur = file_durations[wav_file]
        file_segs = segments_by_file[wav_file]

        _render_file(wav_file, file_dur, file_segs, track_names, dropped, width)


def _render_file(
    wav_file: Path,
    file_dur: float,
    file_segs: list[tuple[int, TrackSegment]],
    track_names: list[str],
    dropped: set[int],
    width: int,
) -> None:
    """Render all lines for a single source file."""
    sec_per_col = file_dur / width

    # Header
    header = Text()
    header.append(f" {wav_file.name} ", style="bold")
    header.append(f"({format_duration(file_dur)})", style="dim")
    console.print(header)

    # Build the regions: segments interspersed with gaps
    regions = _build_regions(file_segs, file_dur, dropped)

    # Render each line
    bar = Text()
    name_line = Text()
    range_line = Text()
    dur_line = Text()

    for region in regions:
        col_start = int(region["start"] / sec_per_col)
        col_end = int(region["end"] / sec_per_col)
        seg_width = max(1, col_end - col_start)

        kind = region["kind"]
        track_num = region.get("track_num", 0)
        name = region.get("name", "")
        r_start = region["start"]
        r_end = region["end"]
        r_dur = r_end - r_start

        if kind == "track":
            colour = _TRACK_COLOURS[(track_num - 1) % len(_TRACK_COLOURS)]
            bar.append("█" * seg_width, style=colour)
            label = f"{track_num}. {name}"
        elif kind == "dropped":
            colour = _DROP_COLOUR
            bar.append("░" * seg_width, style=colour)
            label = "✂ drop"
        else:
            colour = _GAP_COLOUR
            bar.append("░" * seg_width, style=colour)
            label = ""

        # Name annotation
        if seg_width <= 2:
            fill = "·" if kind != "track" else "─"
            name_line.append(fill * seg_width, style=colour)
        elif kind == "gap":
            name_line.append("·" * seg_width, style=colour)
        elif kind == "dropped":
            name_line.append(_center(label, seg_width).replace(" ", "·"), style=colour)
        else:
            inner = seg_width - 2
            if len(label) > inner:
                label = label[: max(0, inner - 1)] + "…" if inner > 1 else label[:inner]
            left = (inner - len(label)) // 2
            right = inner - len(label) - left
            name_line.append("├" + "─" * left + label + "─" * right + "┤", style=colour)

        # Range and duration lines
        if kind == "track":
            range_line.append(
                _fit_text(f"{format_duration(r_start)}→{format_duration(r_end)}", seg_width),
                style=f"dim {colour}",
            )
            dur_line.append(
                _fit_text(f"({format_duration(r_dur)})", seg_width),
                style=f"dim {colour}",
            )
        else:
            range_line.append(" " * seg_width)
            dur_line.append(" " * seg_width)

    console.print(bar)
    console.print(name_line)
    console.print(range_line)
    console.print(dur_line)

    # Time axis
    console.print(_render_time_axis(file_dur, width))
    console.print()


def _build_regions(
    file_segs: list[tuple[int, TrackSegment]],
    file_dur: float,
    dropped: set[int],
) -> list[dict]:
    """Build an ordered list of regions (tracks, gaps, dropped) for a file."""
    regions: list[dict] = []
    cursor = 0.0

    for seg_idx, seg in file_segs:
        # Gap before this segment?
        if seg.start_sec > cursor + 0.1:
            regions.append({
                "kind": "gap",
                "start": cursor,
                "end": seg.start_sec,
            })

        kind = "dropped" if seg_idx in dropped else "track"
        regions.append({
            "kind": kind,
            "start": seg.start_sec,
            "end": seg.end_sec,
            "track_num": seg.track_number,
            "name": seg.track_name,
        })
        cursor = seg.end_sec

    # Trailing gap?
    if cursor < file_dur - 0.1:
        regions.append({
            "kind": "gap",
            "start": cursor,
            "end": file_dur,
        })

    return regions


def _center(text: str, width: int) -> str:
    """Centre text within a field, truncating if needed."""
    if len(text) >= width:
        return text[:width]
    left = (width - len(text)) // 2
    right = width - len(text) - left
    return " " * left + text + " " * right


def _fit_text(text: str, width: int) -> str:
    """Centre text if it fits, otherwise return blank."""
    if len(text) <= width:
        return _center(text, width)
    return " " * width


def _render_time_axis(file_dur: float, width: int) -> Text:
    """Render a time axis for a single file."""
    axis_chars = [" "] * width
    sec_per_col = file_dur / width

    if file_dur <= 120:
        tick_interval = 15.0
    elif file_dur <= 600:
        tick_interval = 60.0
    elif file_dur <= 1800:
        tick_interval = 120.0
    else:
        tick_interval = 300.0

    tick_time = 0.0
    while tick_time <= file_dur:
        label = format_duration(tick_time)
        col = int(tick_time / sec_per_col)
        pos = max(0, col - len(label) // 2)
        if pos + len(label) > width:
            pos = width - len(label)
        pos = max(0, pos)

        if all(axis_chars[p] == " " for p in range(pos, min(pos + len(label), width))):
            for j, ch in enumerate(label):
                if pos + j < width:
                    axis_chars[pos + j] = ch

        tick_time += tick_interval

    # Right-aligned end time
    end_label = format_duration(file_dur)
    end_start = width - len(end_label)
    if end_start >= 0:
        region = axis_chars[end_start:width]
        if all(c == " " for c in region):
            for j, ch in enumerate(end_label):
                axis_chars[end_start + j] = ch

    return Text("".join(axis_chars), style="dim")
