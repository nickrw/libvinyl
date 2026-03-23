"""Audio analysis: silence detection, splitting, and file management."""

from __future__ import annotations

import struct
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import medfilt


@dataclass
class SilenceGap:
    start_sec: float
    end_sec: float

    @property
    def midpoint(self) -> float:
        return (self.start_sec + self.end_sec) / 2

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class SplitPoint:
    """A point within a source file where a track boundary is detected."""
    source_file: Path
    time_sec: float
    gap: SilenceGap


@dataclass
class TrackSegment:
    """A segment of audio that represents one track."""
    source_file: Path
    start_sec: float
    end_sec: float
    track_number: int
    track_name: str = ""

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


def read_wav_mono_rms(path: Path, window_sec: float = 0.1) -> tuple[np.ndarray, int]:
    """Read a WAV file and compute RMS energy in sliding windows.

    Returns (rms_array, sample_rate).
    """
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()

        # Read in chunks to avoid loading entire file into memory at once
        window_frames = int(sample_rate * window_sec)
        rms_values = []

        frames_read = 0
        while frames_read < n_frames:
            chunk_size = min(window_frames, n_frames - frames_read)
            raw = wf.readframes(chunk_size)
            frames_read += chunk_size

            # Convert raw bytes to numpy array
            if sample_width == 2:
                fmt = f"<{chunk_size * n_channels}h"
                max_val = 32768.0
            elif sample_width == 3:
                # 24-bit: unpack manually
                samples = []
                for i in range(0, len(raw), 3):
                    b = raw[i : i + 3]
                    val = struct.unpack("<i", b + (b"\xff" if b[2] & 0x80 else b"\x00"))[0]
                    samples.append(val)
                arr = np.array(samples, dtype=np.float64)
                max_val = 8388608.0
                if n_channels > 1:
                    arr = arr.reshape(-1, n_channels)[:, :2].mean(axis=1)
                rms = np.sqrt(np.mean((arr / max_val) ** 2))
                rms_values.append(rms)
                continue
            elif sample_width == 4:
                fmt = f"<{chunk_size * n_channels}i"
                max_val = 2147483648.0
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")

            if sample_width != 3:
                samples_data = struct.unpack(fmt, raw)
                arr = np.array(samples_data, dtype=np.float64)
                if n_channels > 1:
                    arr = arr.reshape(-1, n_channels)[:, :2].mean(axis=1)
                rms = np.sqrt(np.mean((arr / max_val) ** 2))
                rms_values.append(rms)

    return np.array(rms_values), sample_rate


def detect_silences(
    rms: np.ndarray,
    window_sec: float = 0.1,
    threshold_factor: float = 0.05,
    min_silence_sec: float = 1.0,
    median_filter_size: int = 5,
) -> list[SilenceGap]:
    """Detect silence gaps in an RMS energy array.

    Uses a relative threshold: silence is where RMS drops below
    threshold_factor * median_rms.
    """
    # Smooth the RMS curve
    if len(rms) > median_filter_size:
        smoothed = medfilt(rms, kernel_size=median_filter_size)
    else:
        smoothed = rms

    median_rms = np.median(rms[rms > 0]) if np.any(rms > 0) else 0.001
    threshold = threshold_factor * median_rms

    min_silence_windows = int(min_silence_sec / window_sec)

    # Find runs of silence
    is_silent = smoothed < threshold
    gaps: list[SilenceGap] = []
    in_silence = False
    start_idx = 0

    for i, silent in enumerate(is_silent):
        if silent and not in_silence:
            in_silence = True
            start_idx = i
        elif not silent and in_silence:
            in_silence = False
            length = i - start_idx
            if length >= min_silence_windows:
                gaps.append(SilenceGap(
                    start_sec=start_idx * window_sec,
                    end_sec=i * window_sec,
                ))

    # Handle trailing silence
    if in_silence:
        length = len(is_silent) - start_idx
        if length >= min_silence_windows:
            gaps.append(SilenceGap(
                start_sec=start_idx * window_sec,
                end_sec=len(is_silent) * window_sec,
            ))

    return gaps


def get_wav_duration(path: Path) -> float:
    """Get the duration of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


@dataclass
class _FileRMS:
    """Cached RMS data for a file."""
    path: Path
    duration: float
    rms: np.ndarray
    window_sec: float
    global_offset: float  # start time relative to album start


def _load_file_rms_data(
    wav_files: list[Path],
    window_sec: float = 0.05,
) -> list[_FileRMS]:
    """Load RMS data for all files with global offset tracking."""
    result = []
    offset = 0.0
    for f in wav_files:
        dur = get_wav_duration(f)
        rms, _sr = read_wav_mono_rms(f, window_sec=window_sec)
        result.append(_FileRMS(
            path=f, duration=dur, rms=rms,
            window_sec=window_sec, global_offset=offset,
        ))
        offset += dur
    return result


def _find_quietest_region(
    fd: _FileRMS,
    local_time: float,
    search_radius: float = 15.0,
    region_sec: float = 0.3,
) -> float:
    """Find the midpoint of the quietest region near a local time within a file.

    Searches ±search_radius seconds around local_time, clamped to the
    file boundaries. Returns the local time of the quietest region's midpoint.
    """
    search_start = max(0.0, local_time - search_radius)
    search_end = min(fd.duration, local_time + search_radius)

    start_idx = int(search_start / fd.window_sec)
    end_idx = int(search_end / fd.window_sec)

    if start_idx >= end_idx or start_idx >= len(fd.rms):
        return local_time

    rms_slice = fd.rms[start_idx:end_idx]
    region_windows = max(1, int(region_sec / fd.window_sec))

    best_energy = float("inf")
    best_time = local_time

    for i in range(len(rms_slice) - region_windows + 1):
        region_energy = np.mean(rms_slice[i : i + region_windows])
        if region_energy < best_energy:
            best_energy = region_energy
            mid_idx = i + region_windows // 2
            best_time = (start_idx + mid_idx) * fd.window_sec

    return best_time


def _detect_music_region(
    fd: _FileRMS,
    threshold_factor: float = 0.1,
    sustain_sec: float = 3.0,
) -> tuple[float, float]:
    """Detect where music starts and ends in a file.

    Skips leading silence (needle drop, run-in groove) and trailing
    silence (run-out groove, needle lift). Uses a sustain requirement
    to filter out needle pops and other brief transients.
    """
    rms = fd.rms
    if len(rms) == 0:
        return 0.0, fd.duration

    nonzero = rms[rms > 0]
    if len(nonzero) == 0:
        return 0.0, fd.duration

    median_rms = float(np.median(nonzero))
    threshold = threshold_factor * median_rms
    sustain_windows = max(1, int(sustain_sec / fd.window_sec))

    music_start = 0.0
    for i in range(len(rms) - sustain_windows + 1):
        if float(np.mean(rms[i : i + sustain_windows])) >= threshold:
            music_start = max(0.0, i * fd.window_sec - 1.0)
            break

    music_end = fd.duration
    for i in range(len(rms) - sustain_windows, -1, -1):
        if float(np.mean(rms[i : i + sustain_windows])) >= threshold:
            music_end = min((i + sustain_windows) * fd.window_sec + 1.0, fd.duration)
            break

    return music_start, music_end


def _assign_tracks_to_files(
    file_music_durations: list[float],
    track_durations: list[float],
) -> list[list[int]]:
    """Assign track indices to files based on cumulative duration fit.

    Greedily assigns consecutive tracks to each file, finding the split
    point where the cumulative track duration best matches the file's
    music duration. Returns a list of lists of 0-based track indices.
    """
    n_files = len(file_music_durations)
    n_tracks = len(track_durations)

    groups: list[list[int]] = [[] for _ in range(n_files)]
    track_idx = 0

    for file_idx in range(n_files):
        if file_idx == n_files - 1:
            groups[file_idx] = list(range(track_idx, n_tracks))
            break

        target = file_music_durations[file_idx]
        cumulative = 0.0
        best_split = track_idx
        best_diff = target

        for i in range(track_idx, n_tracks):
            cumulative += track_durations[i]
            diff = abs(cumulative - target)
            if diff < best_diff:
                best_diff = diff
                best_split = i + 1
            if cumulative > target * 1.5:
                break

        groups[file_idx] = list(range(track_idx, best_split))
        track_idx = best_split

    return groups


def analyze_album_files(
    wav_files: list[Path],
    expected_tracks: int | None = None,
    expected_durations_ms: list[int | None] | None = None,
    window_sec: float = 0.05,
) -> list[TrackSegment]:
    """Analyze WAV files for an album and determine track segments.

    When expected durations are available (from MusicBrainz), uses a
    duration-first approach:
      1. For each track, advance by its expected duration to predict the end
      2. Search ±15s around that prediction for the quietest region
      3. Derive the true start as (found_end - known_duration)
      4. Use the found end as the anchor for the next track

    Falls back to simple silence detection when no durations are available.
    """
    if not wav_files:
        return []

    file_durations = [(f, get_wav_duration(f)) for f in wav_files]

    # If files already match expected track count, assume 1:1 mapping
    if expected_tracks and len(wav_files) == expected_tracks:
        segments = []
        for i, (f, dur) in enumerate(file_durations, 1):
            segments.append(TrackSegment(
                source_file=f, start_sec=0, end_sec=dur, track_number=i,
            ))
        return segments

    # Duration-first approach when we have MusicBrainz data
    has_durations = (
        expected_durations_ms
        and all(d is not None for d in expected_durations_ms)
    )
    if has_durations and expected_tracks:
        return _analyze_duration_first(
            wav_files, expected_tracks, expected_durations_ms, window_sec  # type: ignore[arg-type]
        )

    # Fallback: simple silence detection (for manual mode)
    return _analyze_silence_fallback(wav_files, file_durations, window_sec)


def _analyze_duration_first(
    wav_files: list[Path],
    expected_tracks: int,
    expected_durations_ms: list[int],
    window_sec: float,
) -> list[TrackSegment]:
    """Duration-first analysis using expected track lengths.

    Tracks never cross file boundaries — each file is a self-contained
    recording (e.g., one vinyl side). The algorithm:
      1. Detects the music region in each file (skipping lead-in/lead-out)
      2. Assigns tracks to files based on cumulative duration fit
      3. Finds track boundaries within each file independently
    """
    file_data = _load_file_rms_data(wav_files, window_sec=window_sec)
    durations_sec = [d / 1000.0 for d in expected_durations_ms]

    music_regions = [_detect_music_region(fd) for fd in file_data]
    music_durations = [end - start for start, end in music_regions]
    track_groups = _assign_tracks_to_files(music_durations, durations_sec)

    segments: list[TrackSegment] = []
    track_num = 1

    for fd, (music_start, music_end), group in zip(
        file_data, music_regions, track_groups,
    ):
        if not group:
            continue

        group_durations = [durations_sec[i] for i in group]
        cursor = music_start

        for i, expected_dur in enumerate(group_durations):
            predicted_end = cursor + expected_dur

            if i == len(group_durations) - 1:
                track_end = music_end
            else:
                track_end = _find_quietest_region(
                    fd, predicted_end, search_radius=15.0,
                )
                track_end = max(cursor, min(track_end, music_end))

            track_start = max(track_end - expected_dur, cursor)

            segments.append(TrackSegment(
                source_file=fd.path,
                start_sec=track_start,
                end_sec=track_end,
                track_number=track_num,
            ))

            cursor = track_end
            track_num += 1

    return segments


def _analyze_silence_fallback(
    wav_files: list[Path],
    file_durations: list[tuple[Path, float]],
    window_sec: float,
) -> list[TrackSegment]:
    """Fallback silence-based analysis for manual mode (no expected durations)."""
    segments: list[TrackSegment] = []
    track_num = 1

    for wav_file, file_duration in file_durations:
        rms, _sr = read_wav_mono_rms(wav_file, window_sec=window_sec)
        silences = detect_silences(rms, window_sec=window_sec)

        margin = 3.0
        inner_silences = [
            s for s in silences
            if s.midpoint > margin and s.midpoint < (file_duration - margin)
        ]

        if not inner_silences:
            segments.append(TrackSegment(
                source_file=wav_file, start_sec=0,
                end_sec=file_duration, track_number=track_num,
            ))
            track_num += 1
        else:
            boundaries = [0.0]
            for gap in inner_silences:
                boundaries.append(gap.midpoint)
            boundaries.append(file_duration)

            for i in range(len(boundaries) - 1):
                segments.append(TrackSegment(
                    source_file=wav_file,
                    start_sec=boundaries[i],
                    end_sec=boundaries[i + 1],
                    track_number=track_num,
                ))
                track_num += 1

    return segments


def split_wav(
    source: Path,
    output: Path,
    start_sec: float,
    end_sec: float,
) -> None:
    """Extract a segment from a WAV file and write it to a new file."""
    with wave.open(str(source), "rb") as wf:
        params = wf.getparams()
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()

        start_frame = int(start_sec * sample_rate)
        end_frame = int(end_sec * sample_rate)
        n_frames = end_frame - start_frame

        wf.setpos(start_frame)
        raw_data = wf.readframes(n_frames)

    with wave.open(str(output), "wb") as out_wf:
        out_wf.setnchannels(n_channels)
        out_wf.setsampwidth(sample_width)
        out_wf.setframerate(sample_rate)
        out_wf.writeframes(raw_data)
