# libvinyl

Library organiser for vinyl recordings made with a Teenage Engineering TP-7.

Records vinyl to WAV files, then splits, tags, and converts them into a neatly
organised FLAC library.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/), plus ffmpeg:

```bash
brew install ffmpeg  # macOS
uv sync
```

## Usage

### Process albums

Point at your library folder. Each subfolder should be named `Artist - Album`
(or just `Album` for compilations) and contain WAV recordings from the TP-7.

```bash
uv run libvinyl process ./library
```

Process a single album:

```bash
uv run libvinyl process ./library --album "Blink-182 - Take Off Your Pants and Jacket"
```

### Check status

```bash
uv run libvinyl status ./library
```

## How it works

### Pipeline

Each album goes through these stages (tracked in `library-state.yaml`):

1. **raw → analyzed** — Looks up the album on MusicBrainz to get track names,
   durations, and metadata. Prompts you to pick a release if ambiguous, or
   enter track info manually if not found.

2. **analyzed → split** — Uses a duration-first approach: for each track,
   predicts where it should end based on the known duration, then searches
   ±15 seconds around that point for the quietest region in the audio.
   Derives the true start from `(found_end - known_duration)`. Shows a
   preview of the split plan for confirmation.

3. **split → converted** — Converts each WAV track to FLAC (default:
   96kHz/24-bit hi-res, with option to downsample to 44.1kHz/16-bit CD
   quality per album). Tags each FLAC with artist, album, track name/number,
   year, and genre.

4. **converted → done** — Archives original WAV files to `archive/Artist - Album/`
   and cleans up intermediate files.

### Folder structure

```
library/
├── Artist - Album/          # Input: WAV files from TP-7
│   ├── recording-001.wav    # Before processing
│   ├── 01 - Track Name.flac # After processing
│   └── ...
├── library-state.yaml       # Processing state
archive/
└── Artist - Album/          # Archived original WAVs
    └── recording-001.wav
```

### Resumability

State is tracked per-album in `library-state.yaml`. If processing is
interrupted, re-running the command picks up where it left off. Albums
marked as `done` are skipped.

## Recording styles

The TP-7 doesn't know anything about your vinyl — it just records WAV files.
How you choose to start and stop recording determines what libvinyl has to
work with. All of these approaches are supported and can be mixed within a
single album folder:

### One file per track

If you manually stop and start the TP-7 between each track, you'll end up
with one WAV file per track. When the number of files matches the expected
track count from MusicBrainz, libvinyl skips splitting entirely and maps
files 1:1 to tracks (sorted by filename, which the TP-7 timestamps
chronologically).

### One file per vinyl side

The most natural approach — drop the needle at the start of a side and let
it record until the side ends. You'll get two files for a standard LP. The
splitting algorithm handles finding individual track boundaries within each
file.

### One continuous file

Record the entire album into a single WAV, flipping sides without stopping.
This also works fine — the algorithm treats it the same as any other layout,
just with one file in the timeline.

### Mixed / partial recordings

Sometimes you'll miss a track change, or stop and restart mid-side. You
might end up with a file containing tracks 1–3 and another with tracks 4–5.
libvinyl handles this by treating all files as a single continuous timeline
(concatenated in filename order) and finding boundaries within that combined
audio stream. A track boundary can even fall across a file boundary.

## How track splitting works

Vinyl surface noise makes traditional silence detection unreliable — there's
never true silence between tracks, just quieter crackle. libvinyl uses a
**duration-first** approach that relies on knowing how long each track
*should* be, using MusicBrainz as the source of truth.

### Duration-first algorithm

1. **Build a timeline.** All WAV files are loaded and treated as one
   continuous audio stream, sorted by filename. RMS energy is computed in
   0.05-second windows across the entire stream.

2. **Predict each boundary.** Starting at `cursor = 0.0`, the expected
   duration of track 1 (from MusicBrainz) is added to predict where it
   should end.

3. **Search for the quietest region.** Within a ±15-second window around
   the predicted end, a 0.3-second sliding window scans the RMS energy to
   find the lowest-energy region. The midpoint of that region becomes the
   track boundary.

4. **Derive the true start.** The track start is calculated as
   `found_end − expected_duration`, clamped to the previous track's end
   to prevent gaps or overlaps.

5. **Advance and repeat.** The found end becomes the cursor for predicting
   the next track. This anchoring prevents timing drift from accumulating
   across the album. The last track always extends to the end of the audio.

6. **Preview and confirm.** A table is shown comparing expected vs detected
   durations for each track. Nothing is written until you confirm.

### Fallback: silence detection

When MusicBrainz data is unavailable (or you enter tracks manually without
durations), libvinyl falls back to conventional silence detection. It
computes a threshold at 5% of the median RMS energy and looks for sustained
drops below that level (at least 1 second), using those gaps as track
boundaries. This works less reliably on vinyl recordings due to surface
noise but is serviceable as a last resort.

### Short segments and mistakes

If a recording contains very short segments (e.g., accidentally starting and
stopping the recorder), these are flagged during analysis and you're prompted
to discard them before splitting.
