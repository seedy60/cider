from __future__ import annotations
import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot import Bot

from bot.config.models import YtModel

from bot.player.enums import TrackType
from bot.player.track import Track
from bot.services import Service as _Service
from bot import errors


# Audio-only format selection; avoids native HLS so a single stream is picked.
_FORMAT = "m4a/bestaudio/best[protocol!=m3u8_native]/best"

# Suppress the console window yt-dlp would otherwise flash on Windows when the bot
# runs without an attached console; 0 (no-op) everywhere else.
_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class YtService(_Service):
    def __init__(self, bot: Bot, config: YtModel):
        self.bot = bot
        self.config = config
        self.name = "yt"
        self.hostnames = []
        self.is_enabled = self.config.enabled
        self.error_message = ""
        self.warning_message = ""
        self.help = ""
        self.hidden = False

    def initialize(self):
        # We shell out to the standalone yt-dlp binary (configurable path) instead
        # of the Python library so it can be updated independently of the bot.
        self._base_args = [
            self.config.yt_dlp_path,
            "--ignore-config",
            "--no-warnings",
            "--socket-timeout",
            "5",
        ]
        if self.config.cookiefile_path and os.path.isfile(self.config.cookiefile_path):
            self._base_args += ["--cookies", self.config.cookiefile_path]

    def _run_json(self, args: List[str]) -> Dict[str, Any]:
        process = subprocess.run(
            self._base_args + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATIONFLAGS,
        )
        if process.returncode != 0:
            logging.error(
                "yt-dlp failed (%s): %s",
                process.returncode,
                process.stderr.decode(errors="replace").strip(),
            )
            raise errors.ServiceError()
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError:
            raise errors.ServiceError()

    def download(self, track: Track, file_path: str) -> None:
        webpage_url = (track.extra_info or {}).get("webpage_url")
        if not webpage_url:
            super().download(track, file_path)
            return
        # "-o -" streams the media to stdout, guaranteeing the file lands exactly
        # at file_path regardless of the container extension yt-dlp would choose.
        with open(file_path, "wb") as file:
            process = subprocess.run(
                self._base_args
                + ["--no-playlist", "-f", _FORMAT, "-o", "-", webpage_url],
                stdout=file,
                stderr=subprocess.PIPE,
                creationflags=_CREATIONFLAGS,
            )
        if process.returncode != 0:
            logging.error(
                "yt-dlp download failed (%s): %s",
                process.returncode,
                process.stderr.decode(errors="replace").strip(),
            )
            raise errors.ServiceError()

    def get(
        self,
        url: str,
        extra_info: Optional[Dict[str, Any]] = None,
        process: bool = False,
    ) -> List[Track]:
        target = url or (extra_info or {}).get("webpage_url") or (extra_info or {}).get("url")
        if not target:
            raise errors.InvalidArgumentError()
        if process:
            return self._resolve(target)
        # Flat extraction is enough to tell a single video from a playlist.
        info = self._run_json(["--flat-playlist", "-J", target])
        if info.get("_type") == "playlist":
            tracks: List[Track] = []
            for entry in info.get("entries") or []:
                entry_url = entry.get("url") if entry else None
                if entry_url:
                    tracks.append(
                        Track(service=self.name, url=entry_url, type=TrackType.Dynamic)
                    )
            return tracks
        return [Track(service=self.name, url=target, type=TrackType.Dynamic)]

    def _resolve(self, target: str) -> List[Track]:
        info = self._run_json(["--no-playlist", "-J", "-f", _FORMAT, target])
        stream_url = info.get("url")
        if not stream_url:
            downloads = info.get("requested_downloads") or []
            if downloads:
                stream_url = downloads[0].get("url")
        if not stream_url:
            raise errors.ServiceError()
        title = info.get("title") or ""
        if info.get("uploader"):
            title += " - {}".format(info["uploader"])
        return [
            Track(
                service=self.name,
                url=stream_url,
                name=title,
                format=info.get("ext") or "",
                type=TrackType.Live if info.get("is_live") else TrackType.Default,
                extra_info={"webpage_url": info.get("webpage_url") or target},
            )
        ]

    def search(self, query: str) -> List[Track]:
        info = self._run_json(["--flat-playlist", "-J", f"ytsearch300:{query}"])
        tracks: List[Track] = []
        for entry in info.get("entries") or []:
            if entry and entry.get("ie_key") == "Youtube" and entry.get("url"):
                tracks.append(
                    Track(service=self.name, url=entry["url"], type=TrackType.Dynamic)
                )
        if not tracks:
            raise errors.NothingFoundError("")
        return tracks
