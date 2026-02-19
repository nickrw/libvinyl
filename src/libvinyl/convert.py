"""WAV to FLAC conversion and metadata tagging."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mutagen.flac import FLAC


def wav_to_flac(
    wav_path: Path,
    flac_path: Path,
    hi_res: bool = True,
) -> None:
    """Convert a WAV file to FLAC using ffmpeg.

    If hi_res is False, downsample to 44.1kHz/16-bit (CD quality).
    """
    cmd = ["ffmpeg", "-y", "-i", str(wav_path)]
    if not hi_res:
        cmd.extend(["-ar", "44100", "-sample_fmt", "s16"])
    cmd.extend(["-c:a", "flac", str(flac_path)])
    subprocess.run(cmd, check=True, capture_output=True)


def tag_flac(
    flac_path: Path,
    track_number: int,
    track_title: str,
    artist: str,
    album: str,
    year: str | None = None,
    genre: str | None = None,
    total_tracks: int | None = None,
) -> None:
    """Write metadata tags to a FLAC file."""
    audio = FLAC(str(flac_path))
    audio["title"] = track_title
    audio["artist"] = artist
    audio["album"] = album
    audio["tracknumber"] = str(track_number)
    if total_tracks:
        audio["tracktotal"] = str(total_tracks)
    if year:
        audio["date"] = year
    if genre:
        audio["genre"] = genre
    audio.save()
