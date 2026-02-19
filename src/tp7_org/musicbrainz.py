"""MusicBrainz API integration for album/track metadata lookup."""

from __future__ import annotations

from dataclasses import dataclass

import musicbrainzngs

musicbrainzngs.set_useragent("tp7-org", "0.1.0", "https://github.com/nickrw/tp7-org")


@dataclass
class MBTrack:
    number: int
    title: str
    duration_ms: int | None


@dataclass
class MBRelease:
    id: str
    title: str
    artist: str
    year: str | None
    track_count: int
    tracks: list[MBTrack]
    country: str | None = None
    format: str | None = None

    @property
    def summary(self) -> str:
        parts = [f"{self.artist} - {self.title}"]
        if self.year:
            parts.append(f"({self.year})")
        parts.append(f"[{self.track_count} tracks]")
        if self.country:
            parts.append(f"[{self.country}]")
        if self.format:
            parts.append(f"[{self.format}]")
        return " ".join(parts)


def _parse_release_list(release_list: list[dict]) -> list[MBRelease]:
    """Parse a list of raw release dicts into MBRelease objects."""
    releases = []
    for rel in release_list:
        release_id = rel["id"]
        title = rel.get("title", "")
        year = None
        if "date" in rel:
            year = rel["date"][:4] if len(rel["date"]) >= 4 else rel["date"]
        artist_name = ""
        if "artist-credit" in rel:
            artist_name = "".join(
                c.get("name", c.get("artist", {}).get("name", ""))
                if isinstance(c, dict) else c
                for c in rel["artist-credit"]
            )
        track_count = 0
        medium_format = None
        for medium in rel.get("medium-list", []):
            track_count += int(medium.get("track-count", 0))
            if not medium_format and "format" in medium:
                medium_format = medium["format"]

        country = rel.get("country")
        releases.append(MBRelease(
            id=release_id,
            title=title,
            artist=artist_name,
            year=year,
            track_count=track_count,
            tracks=[],
            country=country,
            format=medium_format,
        ))
    return releases


def search_releases(artist: str, album: str, limit: int = 20, offset: int = 0) -> tuple[list[MBRelease], int]:
    """Search MusicBrainz for releases matching artist and album.

    Returns (releases, total_count) so callers can paginate.
    """
    result = musicbrainzngs.search_releases(
        artist=artist, release=album, limit=limit, offset=offset
    )
    release_list = result.get("release-list", [])
    total = int(result.get("release-count", 0))
    return _parse_release_list(release_list), total


def get_release_tracks(release_id: str) -> MBRelease:
    """Fetch full track listing for a specific release."""
    result = musicbrainzngs.get_release_by_id(
        release_id, includes=["recordings", "artists", "tags"]
    )
    rel = result["release"]

    title = rel.get("title", "")
    year = None
    if "date" in rel:
        year = rel["date"][:4] if len(rel["date"]) >= 4 else rel["date"]

    artist_name = ""
    if "artist-credit" in rel:
        artist_name = "".join(
            c.get("name", c.get("artist", {}).get("name", ""))
            if isinstance(c, dict) else c
            for c in rel["artist-credit"]
        )

    # Collect tags as genre
    tags = rel.get("tag-list", [])

    tracks: list[MBTrack] = []
    track_num = 1
    for medium in rel.get("medium-list", []):
        for track in medium.get("track-list", []):
            recording = track.get("recording", {})
            duration = None
            if "length" in track:
                duration = int(track["length"])
            elif "length" in recording:
                duration = int(recording["length"])
            tracks.append(MBTrack(
                number=track_num,
                title=recording.get("title", track.get("title", f"Track {track_num}")),
                duration_ms=duration,
            ))
            track_num += 1

    medium_format = None
    for medium in rel.get("medium-list", []):
        if "format" in medium:
            medium_format = medium["format"]
            break

    return MBRelease(
        id=release_id,
        title=title,
        artist=artist_name,
        year=year,
        track_count=len(tracks),
        tracks=tracks,
        format=medium_format,
    )
