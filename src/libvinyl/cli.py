"""CLI entry point for libvinyl."""

from __future__ import annotations

import shutil
from pathlib import Path

import click
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import ui
from .audio import TrackSegment, analyze_album_files, get_wav_duration, split_wav
from .convert import tag_flac, wav_to_flac
from .musicbrainz import get_release_tracks, search_releases
from .state import AlbumState, AlbumStatus, StateManager, TrackInfo


def parse_folder_name(folder_name: str) -> tuple[str, str]:
    """Parse 'Artist - Album' folder name into (artist, album).

    If no ' - ' separator, treat entire name as album (compilation).
    """
    if " - " in folder_name:
        parts = folder_name.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", folder_name.strip()


def get_wav_files(album_dir: Path) -> list[Path]:
    """Get WAV files sorted by name (which sorts by timestamp for TP-7 files)."""
    return sorted(album_dir.glob("*.wav"), key=lambda p: p.name)


def process_album(
    library_path: Path,
    folder_name: str,
    state_mgr: StateManager,
) -> None:
    """Process a single album through all stages."""
    album_dir = library_path / folder_name
    album_state = state_mgr.get_album(folder_name) or AlbumState()

    artist, album = parse_folder_name(folder_name)
    if not album_state.artist:
        album_state.artist = artist
    if not album_state.album:
        album_state.album = album

    ui.print_header(f"Processing: {folder_name}")

    # Stage: RAW → ANALYZED (MusicBrainz lookup)
    if album_state.status == AlbumStatus.RAW:
        album_state = _stage_analyze(album_state, folder_name)
        state_mgr.set_album(folder_name, album_state)

    # Stage: ANALYZED → SPLIT
    if album_state.status == AlbumStatus.ANALYZED:
        album_state = _stage_split(album_state, album_dir, folder_name)
        state_mgr.set_album(folder_name, album_state)

    # Stage: SPLIT → CONVERTED
    if album_state.status == AlbumStatus.SPLIT:
        album_state = _stage_convert(album_state, album_dir, folder_name)
        state_mgr.set_album(folder_name, album_state)

    # Stage: CONVERTED → DONE (archive originals)
    if album_state.status == AlbumStatus.CONVERTED:
        album_state = _stage_archive(album_state, album_dir, library_path, folder_name)
        state_mgr.set_album(folder_name, album_state)

    if album_state.status == AlbumStatus.DONE:
        ui.print_success(f"Album complete: {folder_name}")


def _stage_analyze(album_state: AlbumState, folder_name: str) -> AlbumState:
    """Look up album on MusicBrainz and get track listing."""
    ui.print_info("Looking up album on MusicBrainz...")

    artist = album_state.artist
    album = album_state.album

    try:
        releases, total = search_releases(artist, album)
    except Exception as e:
        ui.print_warning(f"MusicBrainz search failed: {e}")
        releases, total = [], 0

    release = ui.pick_release(releases, total, artist, album)

    if release:
        ui.print_info(f"Fetching track listing for: {release.summary}")
        try:
            full_release = get_release_tracks(release.id)
        except Exception as e:
            ui.print_error(f"Failed to fetch track listing: {e}")
            full_release = None

        if full_release:
            ui.show_track_listing(full_release.tracks)
            album_state.musicbrainz_id = full_release.id
            album_state.year = full_release.year
            album_state.tracks = [
                TrackInfo(number=t.number, name=t.title, duration_ms=t.duration_ms)
                for t in full_release.tracks
            ]
            album_state.artist = full_release.artist
            album_state.album = full_release.title
    else:
        # Manual fallback
        ui.print_info("Entering manual mode.")
        track_count = ui.prompt_int("Number of tracks")
        names = ui.prompt_track_names(track_count)
        album_state.tracks = [
            TrackInfo(number=i + 1, name=name) for i, name in enumerate(names)
        ]
        if not album_state.year:
            year = ui.prompt_string("Year (or press Enter to skip)", default="")
            if year:
                album_state.year = year

    album_state.status = AlbumStatus.ANALYZED
    return album_state


def _stage_split(
    album_state: AlbumState,
    album_dir: Path,
    folder_name: str,
) -> AlbumState:
    """Analyze audio files and split into individual tracks."""
    wav_files = get_wav_files(album_dir)

    if not wav_files:
        ui.print_warning("No WAV files found in album directory.")
        return album_state

    expected_tracks = len(album_state.tracks) if album_state.tracks else None
    expected_durations: list[int | None] | None = None
    if album_state.tracks:
        durations = [t.duration_ms for t in album_state.tracks]
        if any(d is not None for d in durations):
            expected_durations = durations

    track_names = [t.name for t in album_state.tracks] if album_state.tracks else []

    ui.print_info(f"Analyzing {len(wav_files)} WAV file(s)...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=ui.console,
    ) as progress:
        task = progress.add_task("Analyzing audio...", total=None)
        segments = analyze_album_files(
            wav_files,
            expected_tracks=expected_tracks,
            expected_durations_ms=expected_durations,
        )
        progress.update(task, completed=True)

    # Check if files already match 1:1 with tracks (no splitting needed)
    files_match_tracks = (
        expected_tracks
        and len(wav_files) == expected_tracks
        and len(segments) == expected_tracks
        and all(s.start_sec == 0 for s in segments)
    )

    if files_match_tracks:
        ui.print_info("Files already match expected track count — no splitting needed.")
    else:
        # Detect short segments
        if segments:
            durations = [s.duration_sec for s in segments]
            median_dur = sorted(durations)[len(durations) // 2]
            delete_indices = ui.show_short_segments(segments, track_names, median_dur)
            if delete_indices:
                segments = [s for i, s in enumerate(segments) if i not in delete_indices]
                # Renumber
                for i, seg in enumerate(segments, 1):
                    seg.track_number = i

    # If we don't have enough track names, prompt for manual entry
    if len(track_names) < len(segments):
        ui.print_warning(
            f"Detected {len(segments)} segments but only have "
            f"{len(track_names)} track names."
        )
        if not track_names:
            # Fully manual
            track_names = ui.prompt_track_names(len(segments))
        else:
            # Need more names
            extra = ui.prompt_track_names(
                len(segments) - len(track_names),
                defaults=[f"Track {i}" for i in range(len(track_names) + 1, len(segments) + 1)],
            )
            track_names.extend(extra)
    elif len(track_names) > len(segments):
        ui.print_warning(
            f"Expected {len(track_names)} tracks but only detected "
            f"{len(segments)} segments. Track names will be truncated."
        )
        track_names = track_names[: len(segments)]

    # Apply names to segments
    for i, seg in enumerate(segments):
        if i < len(track_names):
            seg.track_name = track_names[i]

    # Ask for quality
    quality = ui.prompt_quality()
    album_state.quality = quality

    # Show preview
    ui.show_split_preview(
        folder_name, segments, track_names,
        year=album_state.year, quality=quality,
    )

    if not ui.prompt_confirm("Proceed with splitting?"):
        ui.print_warning("Skipping album.")
        return album_state

    # Record original file names before any splitting/renaming
    original_files = [f.name for f in wav_files]

    # Do the splitting
    pad = len(str(len(segments)))
    if files_match_tracks:
        # Just rename in place — files already correspond 1:1
        for seg in segments:
            track_name = seg.track_name or f"Track {seg.track_number}"
            new_name = f"{seg.track_number:0{pad}d} - {track_name}.wav"
            new_path = album_dir / new_name
            if seg.source_file != new_path:
                seg.source_file.rename(new_path)
                ui.print_success(f"Renamed: {seg.source_file.name} → {new_name}")
            seg.source_file = new_path
    else:
        # Need to split files
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=ui.console,
        ) as progress:
            task = progress.add_task("Splitting audio...", total=len(segments))
            for seg in segments:
                track_name = seg.track_name or f"Track {seg.track_number}"
                new_name = f"{seg.track_number:0{pad}d} - {track_name}.wav"
                output_path = album_dir / new_name
                split_wav(seg.source_file, output_path, seg.start_sec, seg.end_sec)
                seg.source_file = output_path
                progress.advance(task)

    # Update state
    album_state.tracks = [
        TrackInfo(number=seg.track_number, name=seg.track_name, file=seg.source_file.name)
        for seg in segments
    ]
    album_state.original_files = original_files
    album_state.status = AlbumStatus.SPLIT
    return album_state


def _stage_convert(
    album_state: AlbumState,
    album_dir: Path,
    folder_name: str,
) -> AlbumState:
    """Convert split WAV tracks to FLAC with metadata."""
    hi_res = album_state.quality != "cd"
    total_tracks = len(album_state.tracks)

    ui.print_info(
        f"Converting {total_tracks} tracks to FLAC "
        f"({'96kHz/24-bit' if hi_res else '44.1kHz/16-bit'})..."
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=ui.console,
    ) as progress:
        task = progress.add_task("Converting...", total=total_tracks)

        pad = len(str(total_tracks))
        for track in album_state.tracks:
            wav_name = track.file or f"{track.number:0{pad}d} - {track.name}.wav"
            wav_path = album_dir / wav_name
            flac_name = f"{track.number:0{pad}d} - {track.name}.flac"
            flac_path = album_dir / flac_name

            if flac_path.exists():
                ui.print_info(f"Already converted: {flac_name}")
                progress.advance(task)
                continue

            if not wav_path.exists():
                ui.print_error(f"WAV file not found: {wav_name}")
                progress.advance(task)
                continue

            wav_to_flac(wav_path, flac_path, hi_res=hi_res)
            tag_flac(
                flac_path,
                track_number=track.number,
                track_title=track.name,
                artist=album_state.artist,
                album=album_state.album,
                year=album_state.year,
                genre=album_state.genre,
                total_tracks=total_tracks,
            )
            track.file = flac_name
            progress.advance(task)

    album_state.status = AlbumStatus.CONVERTED
    return album_state


def _stage_archive(
    album_state: AlbumState,
    album_dir: Path,
    library_path: Path,
    folder_name: str,
) -> AlbumState:
    """Archive original WAV files and clean up split WAV intermediates."""
    archive_dir = library_path.parent / "archive" / folder_name

    # Identify original source files to archive
    if album_state.original_files:
        originals = [album_dir / f for f in album_state.original_files if (album_dir / f).exists()]
    else:
        originals = []

    # Any remaining WAV files (split intermediates) should be deleted
    all_wavs = set(album_dir.glob("*.wav"))
    original_set = set(originals)
    intermediates = all_wavs - original_set

    if not originals and not intermediates:
        ui.print_info("No WAV files to archive or clean up.")
        album_state.status = AlbumStatus.DONE
        return album_state

    if originals:
        archive_dir.mkdir(parents=True, exist_ok=True)
        ui.print_info(f"Archiving {len(originals)} original WAV file(s) to {archive_dir}...")
        for wav_file in originals:
            dest = archive_dir / wav_file.name
            shutil.move(str(wav_file), str(dest))

    if intermediates:
        ui.print_info(f"Cleaning up {len(intermediates)} intermediate WAV file(s)...")
        for wav_file in intermediates:
            wav_file.unlink()

    total = len(originals) + len(intermediates)
    ui.print_success(f"Processed {total} WAV file(s).")
    album_state.status = AlbumStatus.DONE
    return album_state


@click.group()
def main() -> None:
    """TP-7 Library Organiser — manage vinyl recordings."""
    pass


@main.command()
@click.argument("library_path", type=click.Path(exists=True, path_type=Path))
@click.option("--album", "-a", help="Process a specific album folder only.")
def process(library_path: Path, album: str | None) -> None:
    """Process albums: analyse, split, convert to FLAC, and archive."""
    library_path = library_path.resolve()
    state_mgr = StateManager(library_path)

    if album:
        folder = album
        if not (library_path / folder).is_dir():
            ui.print_error(f"Album folder not found: {folder}")
            raise SystemExit(1)
        process_album(library_path, folder, state_mgr)
    else:
        folders = state_mgr.discover_albums()
        if not folders:
            ui.print_warning("No album folders found.")
            return

        ui.print_info(f"Found {len(folders)} album(s) in library.")

        # Show current state
        all_states = {}
        for f in folders:
            existing = state_mgr.get_album(f)
            if existing:
                all_states[f] = existing
            else:
                artist, album_name = parse_folder_name(f)
                all_states[f] = AlbumState(artist=artist, album=album_name)

        ui.print_status_table(all_states)

        # Process albums that aren't done
        for folder in folders:
            existing = state_mgr.get_album(folder)
            if existing and existing.status == AlbumStatus.DONE:
                continue
            ui.console.print()
            process_album(library_path, folder, state_mgr)


@main.command()
@click.argument("library_path", type=click.Path(exists=True, path_type=Path))
def status(library_path: Path) -> None:
    """Show the processing status of all albums."""
    library_path = library_path.resolve()
    state_mgr = StateManager(library_path)

    folders = state_mgr.discover_albums()
    all_states = {}
    for f in folders:
        existing = state_mgr.get_album(f)
        if existing:
            all_states[f] = existing
        else:
            artist, album_name = parse_folder_name(f)
            all_states[f] = AlbumState(artist=artist, album=album_name)

    ui.print_status_table(all_states)
