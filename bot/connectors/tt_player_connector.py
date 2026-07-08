from __future__ import annotations
import logging
from threading import Thread
import time
from typing import TYPE_CHECKING

from bot.player import State
from bot import app_vars

if TYPE_CHECKING:
    from bot import Bot


class TTPlayerConnector(Thread):
    def __init__(self, bot: Bot):
        super().__init__(daemon=True)
        self.name = "TTPlayerConnector"
        self.player = bot.player
        self.ttclient = bot.ttclient
        self.translator = bot.translator

    def run(self):
        last_player_state = State.Stopped
        self._close = False
        while not self._close:
            try:
                # A generic, stable status; the title of the current media is
                # available on demand via the "t" command instead of being pushed
                # into the status (which is noisy for e.g. radio streams).
                if self.player.state != last_player_state:
                    last_player_state = self.player.state
                    if self.player.state == State.Playing:
                        self.ttclient.enable_voice_transmission()
                        self.ttclient.change_status_text(
                            self.translator.translate("Streaming media")
                        )
                    elif self.player.state == State.Stopped:
                        self.ttclient.disable_voice_transmission()
                        self.ttclient.change_status_text("")
                    elif self.player.state == State.Paused:
                        self.ttclient.disable_voice_transmission()
                        self.ttclient.change_status_text(
                            self.translator.translate("Paused")
                        )
            except Exception:
                logging.error("", exc_info=True)
            time.sleep(app_vars.loop_timeout)

    def close(self):
        self._close = True
