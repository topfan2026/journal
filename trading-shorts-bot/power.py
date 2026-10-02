"""Keep Windows awake while the scheduler runs, and the screen on while streaming.

Uses SetThreadExecutionState, the call video players use. It only stops *idle* sleep:
choosing Sleep in the Start menu, closing a laptop lid, or a power-button press still sleep.
The setting is per thread and ends when the process exits. No-op on macOS/Linux.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def _set(flags: int) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except Exception as e:
        log.debug("SetThreadExecutionState failed: %s", e)
        return False


def stay_awake(screen_on: bool = False) -> bool:
    """No idle sleep from now on (and no screen-off / screen saver if screen_on)."""
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | (ES_DISPLAY_REQUIRED if screen_on else 0)
    return _set(flags)


def allow_screen_off() -> bool:
    """Back to 'system awake, screen may turn off' (between streams)."""
    return stay_awake(screen_on=False)
