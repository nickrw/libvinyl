---
name: analyzing-wav-audio
description: "Guides WAV file audio analysis: RMS energy computation, silence detection, and signal interpretation. Use when reading, inspecting, or reasoning about WAV audio loudness, noise floor, or silence in this project."
---

# Analyzing WAV Audio

Provides instructions for working with WAV audio analysis in tp7-org.

## Core Concepts

### RMS Energy
RMS (Root Mean Square) energy measures average loudness in sliding windows. This project computes it in `src/tp7_org/audio.py` via `read_wav_mono_rms()`.

- **Window size**: Default 0.05s (50ms) for analysis, 0.1s for basic detection
- **Output**: A 1D numpy array where each element is the RMS energy of one window
- **Normalization**: Raw samples are divided by max value for the bit depth before squaring

### Multi-Bitrate WAV Handling
The TP-7 records at various bit depths. The code handles:

| Bit depth | Format string | Max value | Notes |
|-----------|--------------|-----------|-------|
| 16-bit | `<Nh` (signed short) | 32768.0 | Standard WAV |
| 24-bit | Manual 3-byte unpack | 8388608.0 | Sign-extended to 32-bit int |
| 32-bit | `<Ni` (signed int) | 2147483648.0 | High-resolution |

For 24-bit files, bytes are unpacked manually in groups of 3 and sign-extended:
```python
val = struct.unpack("<i", b + (b"\xff" if b[2] & 0x80 else b"\x00"))[0]
```

### Mono Downmixing
Multi-channel audio is averaged across channels before RMS calculation:
```python
arr = arr.reshape(-1, n_channels).mean(axis=1)
```

### Median Filtering
RMS curves are smoothed with `scipy.signal.medfilt` (default kernel size 5) to reduce the impact of transient clicks and pops from vinyl surface noise.

## Silence Detection

Silence is detected using a **relative threshold** — not an absolute one. This is critical for vinyl recordings where the noise floor is never truly zero.

### Algorithm (`detect_silences()`)
1. Smooth the RMS curve with median filter
2. Compute `threshold = threshold_factor × median_rms` (default factor: 0.05 = 5% of median)
3. Find contiguous runs where smoothed RMS < threshold
4. Keep only runs longer than `min_silence_sec` (default: 1.0s)
5. Return as `SilenceGap` objects with `start_sec`, `end_sec`, `midpoint`, `duration`

### Key Insight: Vinyl Surface Noise
Global silence detection is unreliable for vinyl because:
- Surface noise means RMS never reaches zero between tracks
- Quiet musical passages can be mistaken for track gaps
- Short inter-track gaps (< 0.3s) get filtered out by minimum duration

When silence detection alone isn't working, prefer the duration-first approach (see `splitting-vinyl-tracks` skill).

## Workflow: Inspecting Audio

When asked to analyze or debug audio:

1. **Check file properties** — Use `get_wav_duration()` to get duration, open with `wave` module to check channels, sample width, sample rate
2. **Compute RMS** — Use `read_wav_mono_rms(path, window_sec=0.05)` for fine-grained analysis
3. **Visualize mentally** — High RMS = loud audio, low RMS = quiet/silence, median RMS = typical loudness level
4. **Detect silences** — Use `detect_silences()` with default params first, then adjust `threshold_factor` (0.02–0.20) and `min_silence_sec` (0.5–3.0) if needed

## Key Functions (in `src/tp7_org/audio.py`)

- `read_wav_mono_rms(path, window_sec)` → `(rms_array, sample_rate)`
- `detect_silences(rms, window_sec, threshold_factor, min_silence_sec, median_filter_size)` → `list[SilenceGap]`
- `get_wav_duration(path)` → `float` (seconds)
- `_load_file_rms_data(wav_files, window_sec)` → `list[_FileRMS]` (with global offsets)
