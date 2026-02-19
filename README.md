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

## Input file expectations

- WAV files recorded from vinyl via the TP-7
- Files are sorted by name (TP-7 names files by timestamp, so alphabetical
  order = recording order)
- A folder might contain any combination of:
  - One file per track (already split)
  - One file per vinyl side
  - One file for the entire album
  - A mix (e.g., missed a split between tracks)
