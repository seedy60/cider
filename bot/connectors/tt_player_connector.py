from __future__ import annotations
import logging
from threading import Thread
import time
from typing import Dict, TYPE_CHECKING

from bot.player import State
from bot import app_vars

if TYPE_CHECKING:
    from bot import Bot


class TTPlayerConnector(Thread):
    def __init__(self, bot: Bot):
        super().__init__(daemon=True)
        self.name = "TTPlayerConnector"
        self.player = bot.player
        self.ttclients = bot.ttclients
        self.translator = bot.translator

    def run(self):
        last_player_state = State.Stopped
        # The server the playback belongs to; a fresh, idle bot has none.
        last_target = None
        # Matches each client's current status text, so a fresh, idle bot does
        # not issue a redundant status update before anything plays.
        last_status_texts: Dict[int, str] = {}
        self._close = False
        while not self._close:
            try:
                state = self.player.state
                target = self._playback_target()
                # Voice transmission only flips on a real state or target change.
                if state != last_player_state or target is not last_target:
                    last_player_state = state
                    last_target = target
                    for ttclient in self.ttclients:
                        if state == State.Playing and ttclient is target:
                            ttclient.enable_voice_transmission()
                        else:
                            ttclient.disable_voice_transmission()

                # The status text is recomputed every tick, not just on a state
                # change, so it follows track changes while playback stays in
                # the Playing state (e.g. advancing through a playlist). Only the
                # server being played on announces the track; the others keep
                # their own status, since they are not transmitting it.
                status_text = self._status_text(state) if target is not None else ""
                for ttclient in self.ttclients:
                    text = status_text if ttclient is target else ""
                    if last_status_texts.get(id(ttclient), "") != text:
                        last_status_texts[id(ttclient)] = text
                        ttclient.change_status_text(text)
            except Exception:
                logging.error("", exc_info=True)
            time.sleep(app_vars.loop_timeout)

    def _playback_target(self):
        """The client the current playback belongs to.

        Playback started without an originating server (e.g. from an event
        handler) falls back to the primary server, so a track is never sent to
        every configured server at once.
        """
        return self.player.ttclient or (self.ttclients[0] if self.ttclients else None)

    def _status_text(self, state: State) -> str:
        """The TeamTalk status to show for the current player state.

        While playing, show the current media's title (its URL if untitled, as
        the "t" command does), falling back to a generic label if neither is
        known yet. An empty string resets the client to its default status.
        """
        if state == State.Playing:
            track = self.player.track
            return (
                track.name
                or track.url
                or self.translator.translate("Streaming media")
            )
        if state == State.Paused:
            return self.translator.translate("Paused")
        return ""

    def close(self):
        self._close = True
