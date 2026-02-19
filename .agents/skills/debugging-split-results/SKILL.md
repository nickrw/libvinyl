---
name: debugging-split-results
description: "Diagnoses incorrect track splits: duration mismatches, track bleed, boundary errors. Use when splits look wrong, tracks are too long/short, or boundaries are in the wrong place."
---

# Debugging Split Results

A diagnostic workflow for when album splitting produces incorrect results.

## Common Symptoms

| Symptom | Likely Cause | Section |
|---------|-------------|---------|
| Track too long | Boundary placed too late, or bleed from next track | Track Bleed |
| Track too short | Boundary placed too early, quiet passage mistaken for gap | False Boundary |
| Tracks shifted by N seconds | Drift accumulated from early error | Drift Analysis |
| Wrong number of tracks | Silence fallback used, or 1:1 mapping triggered | Entry Point Check |
| All tracks in one segment | No silences detected / no durations provided | Missing Metadata |

## Step 1: Check Entry Point Decision

Read `analyze_album_files()` in `src/tp7_org/audio.py` and verify which code path was taken:

1. **1:1 mapping** — `len(wav_files) == expected_tracks`. If the user has one WAV per track already, no splitting occurs. Check if this condition was triggered incorrectly.
2. **Duration-first** — All `expected_durations_ms` are non-None. This is the preferred path.
3. **Silence fallback** — No durations available. Results will be unreliable for vinyl.

**Action**: Check what MusicBrainz data was provided. Look at the album's state in `library-state.yaml` for the `release_id` and track listing.

## Step 2: Compare Expected vs. Actual Durations

For each `TrackSegment` returned:
```
expected_duration = expected_durations_ms[i] / 1000.0
actual_duration   = segment.end_sec - segment.start_sec
drift             = actual_duration - expected_duration
```

- **Small drift (< 5s)**: Normal for vinyl. Pressing variations, speed differences.
- **Large drift (> 15s)**: The boundary search likely locked onto the wrong quiet region.
- **Consistent drift direction**: May indicate a speed mismatch (33⅓ vs 45 RPM, or slight turntable speed error).

## Step 3: Inspect RMS Around Boundaries

To understand why a boundary was placed where it was:

1. Load file RMS data: `_load_file_rms_data(wav_files, window_sec=0.05)`
2. For the problematic boundary, look at RMS values in the ±15s search window
3. The algorithm picks the 0.3s region with the lowest mean RMS
4. Ask: Is there a *quieter* region nearby that should have been chosen? Or is the chosen region actually correct but the prediction was too far off?

### Diagnosis Questions
- **Was the predicted end within ±15s of the actual gap?** If not, increase `search_radius`.
- **Is there a quiet musical passage near the prediction?** The algorithm may have locked onto it instead of the actual inter-track gap.
- **Is the inter-track gap shorter than 0.3s?** Reduce `region_sec` to find it.

## Step 4: Track Bleed Detection

Track bleed occurs when the tail of one track includes the beginning of the next. Signs:

- The track's actual duration is noticeably longer than expected
- Audio at the end of the extracted track sounds like a different song
- The *next* track starts abruptly (missing its intro)

**Root cause**: The quietest region search found a quiet moment *after* the actual gap, perhaps a quiet intro to the next track.

**Fix approaches**:
- Reduce `search_radius` to constrain the search closer to the prediction
- Check if the MusicBrainz duration is accurate (it may include hidden tracks or silence)
- Consider whether the vinyl pressing has a different arrangement than the digital release

## Step 5: Cross-File Boundary Issues

When a track spans two WAV files (e.g., recording was split at a side change):

1. Check `_global_to_file()` mapping — the track is assigned to the file containing its start
2. The `end_sec` will be clamped to the source file's duration if the track crosses a file boundary
3. This means audio from the second file is lost for that track

**Current limitation**: Cross-file tracks are not fully supported. The segment's audio will be truncated at the first file's end.

## Step 6: Silence Fallback Debugging

If duration-first wasn't used and silence detection produced bad results:

1. Adjust `threshold_factor` — try values from 0.02 (very sensitive) to 0.20 (only deep silence)
2. Adjust `min_silence_sec` — try 0.5s for albums with short gaps, 2.0s for fewer false positives
3. Check the 3.0s margin filter — silences within 3s of file start/end are excluded
4. Consider providing MusicBrainz data to switch to duration-first mode

## Verification

After adjusting parameters or fixing issues:

```bash
uv run tp7-org process ./library --album "Artist - Album"
```

The interactive preview shows all detected segments with durations. Compare these against the MusicBrainz track listing before confirming the split.
