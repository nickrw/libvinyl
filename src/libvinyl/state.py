"""State management for the TP-7 library organiser.

Tracks per-album processing state in a YAML file at the library root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml


class AlbumStatus(str, Enum):
    RAW = "raw"
    ANALYZED = "analyzed"
    SPLIT = "split"
    CONVERTED = "converted"
    DONE = "done"

    @property
    def next(self) -> AlbumStatus | None:
        order = list(AlbumStatus)
        idx = order.index(self)
        if idx + 1 < len(order):
            return order[idx + 1]
        return None


@dataclass
class TrackInfo:
    number: int
    name: str
    file: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict:
        d: dict = {"number": self.number, "name": self.name}
        if self.file:
            d["file"] = self.file
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TrackInfo:
        return cls(
            number=d["number"], name=d["name"],
            file=d.get("file"), duration_ms=d.get("duration_ms"),
        )


@dataclass
class AlbumState:
    status: AlbumStatus = AlbumStatus.RAW
    artist: str = ""
    album: str = ""
    musicbrainz_id: str | None = None
    year: str | None = None
    genre: str | None = None
    quality: str = "hi-res"  # "hi-res" or "cd"
    tracks: list[TrackInfo] = field(default_factory=list)
    original_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {
            "status": self.status.value,
            "artist": self.artist,
            "album": self.album,
            "quality": self.quality,
        }
        if self.musicbrainz_id:
            d["musicbrainz_id"] = self.musicbrainz_id
        if self.year:
            d["year"] = self.year
        if self.genre:
            d["genre"] = self.genre
        if self.tracks:
            d["tracks"] = [t.to_dict() for t in self.tracks]
        if self.original_files:
            d["original_files"] = self.original_files
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AlbumState:
        return cls(
            status=AlbumStatus(d.get("status", "raw")),
            artist=d.get("artist", ""),
            album=d.get("album", ""),
            musicbrainz_id=d.get("musicbrainz_id"),
            year=d.get("year"),
            genre=d.get("genre"),
            quality=d.get("quality", "hi-res"),
            tracks=[TrackInfo.from_dict(t) for t in d.get("tracks", [])],
            original_files=d.get("original_files", []),
        )


class StateManager:
    def __init__(self, library_path: Path):
        self.library_path = library_path
        self.state_file = library_path / "library-state.yaml"
        self._state: dict[str, AlbumState] = {}
        self._load()

    def _load(self) -> None:
        if self.state_file.exists():
            with open(self.state_file) as f:
                data = yaml.safe_load(f) or {}
            albums = data.get("albums", {})
            for folder_name, album_data in albums.items():
                self._state[folder_name] = AlbumState.from_dict(album_data)

    def save(self) -> None:
        data = {
            "albums": {
                name: state.to_dict() for name, state in sorted(self._state.items())
            }
        }
        with open(self.state_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def get_album(self, folder_name: str) -> AlbumState | None:
        return self._state.get(folder_name)

    def set_album(self, folder_name: str, state: AlbumState) -> None:
        self._state[folder_name] = state
        self.save()

    def all_albums(self) -> dict[str, AlbumState]:
        return dict(self._state)

    def discover_albums(self) -> list[str]:
        """Find all album folders in the library that aren't hidden."""
        folders = []
        for entry in sorted(self.library_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                if entry.name == "archive":
                    continue
                folders.append(entry.name)
        return folders
