---
name: splitting-vinyl-tracks
description: "Documents the duration-first track splitting algorithm for vinyl recordings. Use when processing, modifying, or debugging album splitting, track boundary detection, or MusicBrainz-guided segmentation."
---

# Splitting Vinyl Tracks

Describes the duration-first splitting algorithm used to segment multi-track vinyl recordings into individual tracks.

## Why Duration-First?

Global silence detection fails on vinyl because surface noise prevents true silence between tracks. Instead, we use known track durations from MusicBrainz to *predict* where boundaries should be, then refine using the audio signal.

## Algorithm Overview

The implementation lives in `_analyze_duration_first()` in `src/tp7_org/audio.py`.

### Step-by-Step

```
cursor = 0.0 (start of album)

For each track:
  1. PREDICT:  predicted_end = cursor + expected_duration
  2. SEARCH:   Find quietest 0.3s region within ±15s of predicted_end
  3. ANCHOR:   track_end = midpoint of quietest region
  4. DERIVE:   track_start = max(track_end - expected_duration, cursor)
  5. ADVANCE:  cursor = track_end  (drift correction)
```

The last track always extends to the end of all audio.

### Drift Correction
Using the *found* end (not the predicted end) as the next cursor prevents timing errors from accumulating. If track 3 is 5 seconds longer than MusicBrainz says, the prediction for track 4 automatically adjusts.

### Quietest Region Search (`_find_quietest_region()`)
- Searches ±15s (configurable `search_radius`) around the predicted time
- Slides a 0.3s window across the search area
- Returns the midpoint of the window with the lowest mean RMS energy
- Works across file boundaries using global offsets

## Multi-File Handling

Vinyl sides are typically separate WAV files. The system treats them as one continuous timeline:

1. `_load_file_rms_data()` loads all files and assigns `global_offset` to each
2. `_find_quietest_region()` searches across file boundaries seamlessly
3. `_global_to_file()` converts global timestamps back to `(file, local_time)` pairs

### Cross-File Tracks
A track can span two source files (e.g., last track of side A bleeds into side B file). Currently, the segment is assigned to the file containing its start. This is a known limitation.

## Entry Point: `analyze_album_files()`

```python
analyze_album_files(
    wav_files: list[Path],           # Ordered WAV files
    expected_tracks: int | None,      # From MusicBrainz
    expected_durations_ms: list[int | None] | None,  # Per-track durations
    window_sec: float = 0.05,         # RMS window size
) -> list[TrackSegment]
```

### Decision Logic
1. If `len(wav_files) == expected_tracks` → assume 1:1 mapping (no splitting needed)
2. If all durations available → use `_analyze_duration_first()`
3. Otherwise → fall back to `_analyze_silence_fallback()` (global silence detection)

## Data Types

- **`TrackSegment`**: `source_file`, `start_sec`, `end_sec`, `track_number`, `track_name`
- **`SplitPoint`**: `source_file`, `time_sec`, `gap` (a `SilenceGap`)
- **`SilenceGap`**: `start_sec`, `end_sec` (with `midpoint` and `duration` properties)
- **`_FileRMS`**: Internal cache with `path`, `duration`, `rms`, `window_sec`, `global_offset`

## Physical Splitting: `split_wav()`

Once segments are determined, `split_wav(source, output, start_sec, end_sec)` extracts audio:
- Seeks to `start_frame = int(start_sec * sample_rate)`
- Reads `n_frames = end_frame - start_frame` frames
- Writes a new WAV file preserving original params (channels, sample width, sample rate)

## Workflow: Modifying the Splitting Algorithm

1. Read `src/tp7_org/audio.py` — all splitting logic is here
2. Key tuning parameters:
   - `search_radius` (default 15.0s) — how far from prediction to search
   - `region_sec` (default 0.3s) — width of the "quietest region" window
   - `window_sec` (default 0.05s) — RMS computation granularity
3. Test changes with: `uv run tp7-org process ./library --album "Artist - Album"`
4. The interactive preview will show detected segments before any files are written
