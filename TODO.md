# TODO

## High priority

- [ ] Handle tracks that span file boundaries (e.g., a track split across
      Side A and Side B WAVs — needs concatenation before slicing)
- [ ] Detect and trim track bleed: if recording wasn't stopped in time, the
      start of the next track may appear at the end of the current file.
      Could detect this by comparing the tail of the extracted segment against
      the expected duration and looking for an energy spike after the expected
      end point.

## Medium priority

- [ ] Multi-disc album support: group folders like `Artist - Album (Disc 1)`
      and `Artist - Album (Disc 2)` into a single logical album
- [ ] Compilation album support: per-track artist metadata from MusicBrainz
      when the folder is named with just the album title (no artist)
- [ ] Genre tags from MusicBrainz (currently fetched but not always populated
      in the API response — may need to query recordings or release groups)
- [ ] Add `--dry-run` flag to preview what would happen without making changes
- [ ] Better handling when detected segment count doesn't match expected tracks
      (interactive adjustment of split points)

## Low priority / future ideas

- [ ] TP-7 MTP integration: connect to the TP-7 via USB, put it in MTP mode,
      discover new recordings, and import them to the library automatically
- [ ] Cover art embedding from Cover Art Archive (adds ~500KB-2MB per track)
- [ ] Web UI / TUI for browsing the library and managing processing
- [ ] Waveform visualisation of split points in the terminal
- [ ] Support for other input formats (not just WAV)
- [ ] Configurable search radius for silence detection (currently ±15s)
- [ ] Noise profile analysis: characterise the surface noise of each vinyl
      and use it to set more accurate silence thresholds
