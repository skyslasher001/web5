"""UUIDv7 ids (RFC 9562): time-ordered, generated anywhere, stored as TEXT."""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> str:
    """Return a new UUIDv7 string. Ids from one process are strictly increasing."""
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x3FF  # random start, room to count up
        else:
            # Same millisecond (or clock went backwards): keep order with the 12-bit counter.
            _counter += 1
            if _counter > 0xFFF:
                _last_ms += 1
                _counter = 0
        ms = _last_ms
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | _counter << 64 | 0b10 << 62 | rand_b
    return str(uuid.UUID(int=value))
