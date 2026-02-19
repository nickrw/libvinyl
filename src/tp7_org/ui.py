"""Rich console UI: tables, prompts, progress bars."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

if TYPE_CHECKING:
    from .audio import TrackSegment
    from .musicbrainz import MBRelease, MBTrack
    from .state import AlbumState, AlbumStatus

console = Console()


def print_status_table(albums: dict[str, AlbumState]) -> None:
    """Print a status overview of all albums."""
    table = Table(title="Library Status")
    table.add_column("#", style="dim")
    table.add_column("Album Folder", style="cyan")
    table.add_column("Artist", style="green")
    table.add_column("Album", style="green")
    table.add_column("Status", style="bold")
    table.add_column("Tracks", justify="right")

    for i, (folder, state) in enumerate(sorted(albums.items()), 1):
        status_style = {
            "raw": "red",
            "analyzed": "yellow",
            "split": "blue",
            "converted": "magenta",
            "done": "green",
        }.get(state.status.value, "white")

        table.add_row(
            str(i),
            folder,
            state.artist or "—",
            state.album or "—",
            f"[{status_style}]{state.status.value}[/{status_style}]",
            str(len(state.tracks)) if state.tracks else "—",
        )

    console.print(table)


def pick_release(
    releases: list[MBRelease],
    total: int = 0,
    artist: str = "",
    album: str = "",
) -> MBRelease | None:
    """Prompt the user to pick a MusicBrainz release.

    Shows the current page of results. If more are available on MusicBrainz,
    offers a "show more" option that fetches the next page.
    """
    if not releases:
        console.print("[yellow]No releases found on MusicBrainz.[/yellow]")
        return None

    _print_release_table(releases)

    has_more = total > len(releases)
    if has_more:
        console.print(
            f"[dim]Showing {len(releases)} of {total} results. "
            f"Enter -1 to load more.[/dim]"
        )
    console.print("[dim]Enter 0 to skip MusicBrainz and enter track info manually.[/dim]")

    default = _suggest_default(releases)

    choice = IntPrompt.ask("Select release", default=default)

    if choice == 0:
        return None
    if choice == -1 and has_more:
        from .musicbrainz import search_releases

        try:
            more, total = search_releases(
                artist, album, limit=20, offset=len(releases)
            )
        except Exception as e:
            console.print(f"[red]Failed to fetch more results: {e}[/red]")
            return pick_release(releases, len(releases), artist, album)
        releases.extend(more)
        return pick_release(releases, total, artist, album)
    if 1 <= choice <= len(releases):
        return releases[choice - 1]

    console.print("[red]Invalid choice.[/red]")
    return pick_release(releases, total, artist, album)


def _print_release_table(releases: list[MBRelease]) -> None:
    """Print the numbered table of MusicBrainz releases."""
    table = Table(title="MusicBrainz Releases")
    table.add_column("#", style="dim")
    table.add_column("Artist", style="green")
    table.add_column("Title", style="cyan")
    table.add_column("Year")
    table.add_column("Tracks", justify="right")
    table.add_column("Country")
    table.add_column("Format")

    for i, rel in enumerate(releases, 1):
        table.add_row(
            str(i),
            rel.artist,
            rel.title,
            rel.year or "—",
            str(rel.track_count),
            rel.country or "—",
            rel.format or "—",
        )

    console.print(table)


def _suggest_default(releases: list[MBRelease]) -> int:
    """Suggest a default release: prefer GB vinyl, then any vinyl, then first."""
    vinyl_indices = [
        i for i, rel in enumerate(releases, 1)
        if rel.format and "vinyl" in rel.format.lower()
    ]
    gb_vinyl_indices = [
        i for i in vinyl_indices
        if releases[i - 1].country and releases[i - 1].country.upper() == "GB"
    ]
    if len(gb_vinyl_indices) == 1:
        default = gb_vinyl_indices[0]
        console.print(f"[dim]One GB Vinyl release found (#{default}).[/dim]")
    elif len(vinyl_indices) == 1:
        default = vinyl_indices[0]
        console.print(f"[dim]One Vinyl release found (#{default}).[/dim]")
    else:
        default = 1
    return default


def show_track_listing(tracks: list[MBTrack]) -> None:
    """Display the track listing from MusicBrainz."""
    table = Table(title="Track Listing")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Title", style="cyan")
    table.add_column("Duration", justify="right")

    for track in tracks:
        dur = ""
        if track.duration_ms:
            mins, secs = divmod(track.duration_ms // 1000, 60)
            dur = f"{mins}:{secs:02d}"
        table.add_row(str(track.number), track.title, dur)

    console.print(table)


def format_duration(seconds: float) -> str:
    """Format seconds as M:SS."""
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02d}"


def show_split_preview(
    folder_name: str,
    segments: list[TrackSegment],
    track_names: list[str],
    year: str | None = None,
    quality: str = "hi-res",
) -> None:
    """Show a preview of the splitting plan."""
    table = Table(title=f"Split Plan: {folder_name}")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Track Name", style="cyan")
    table.add_column("Source File", style="dim")
    table.add_column("Segment", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Status", style="dim")

    for seg in segments:
        name = track_names[seg.track_number - 1] if seg.track_number <= len(track_names) else "?"
        status = ""
        if seg.duration_sec < 10:
            status = "[red]⚠ SHORT[/red]"

        table.add_row(
            str(seg.track_number),
            name,
            seg.source_file.name,
            f"{format_duration(seg.start_sec)} → {format_duration(seg.end_sec)}",
            format_duration(seg.duration_sec),
            status,
        )

    console.print(table)

    if year:
        console.print(f"  Year: {year}")
    quality_label = "96kHz/24-bit (hi-res)" if quality == "hi-res" else "44.1kHz/16-bit (CD)"
    console.print(f"  Quality: {quality_label}")


def prompt_quality() -> str:
    """Ask the user for output quality."""
    choice = Prompt.ask(
        "Output quality",
        choices=["hi-res", "cd"],
        default="hi-res",
    )
    return choice


def prompt_confirm(message: str = "Proceed?", default: bool = True) -> bool:
    return Confirm.ask(message, default=default)


def prompt_track_names(count: int, defaults: list[str] | None = None) -> list[str]:
    """Prompt for track names, with optional defaults."""
    names = []
    for i in range(1, count + 1):
        default = defaults[i - 1] if defaults and i <= len(defaults) else f"Track {i}"
        name = Prompt.ask(f"  Track {i:2d}", default=default)
        names.append(name)
    return names


def prompt_int(message: str, default: int | None = None) -> int:
    return IntPrompt.ask(message, default=default)


def prompt_string(message: str, default: str | None = None) -> str:
    return Prompt.ask(message, default=default)


def print_success(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def print_warning(message: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {message}")


def print_error(message: str) -> None:
    console.print(f"[red]✗[/red] {message}")


def print_info(message: str) -> None:
    console.print(f"[blue]ℹ[/blue] {message}")


def print_header(message: str) -> None:
    console.print(Panel(message, style="bold cyan"))


def show_short_segments(
    segments: list[TrackSegment],
    track_names: list[str],
    median_duration: float,
) -> list[int]:
    """Show short segments and ask which to delete. Returns indices to delete."""
    threshold = median_duration * 0.3  # Less than 30% of median duration

    short_indices = []
    for i, seg in enumerate(segments):
        if seg.duration_sec < threshold and seg.duration_sec < 15:
            short_indices.append(i)

    if not short_indices:
        return []

    console.print("\n[yellow]Short segments detected:[/yellow]")
    for idx in short_indices:
        seg = segments[idx]
        name = track_names[idx] if idx < len(track_names) else "?"
        console.print(
            f"  Track {seg.track_number}: {name} "
            f"({format_duration(seg.duration_sec)}) from {seg.source_file.name}"
        )

    delete = Confirm.ask("Delete these short segments?", default=True)
    if delete:
        return short_indices
    return []
