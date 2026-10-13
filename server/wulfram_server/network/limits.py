"""Small, bounded rate windows for the public protocol's expensive paths."""
from collections import OrderedDict
import threading
import time


class RateLimit:
    def __init__(self, count: int, seconds: float, *, keys: int = 4096):
        self.count, self.seconds, self.keys = count, seconds, keys
        self.windows = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key=0, *, now=None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            entry = self.windows.get(key)
            if entry is None:
                while self.windows and next(iter(self.windows.values()))[0] <= now:
                    self.windows.popitem(last=False)
                if len(self.windows) >= self.keys:
                    return False
                entry = [now + self.seconds, 0]
                self.windows[key] = entry
            elif entry[0] <= now:
                entry = [now + self.seconds, 0]
                self.windows[key] = entry
                self.windows.move_to_end(key)
            if entry[1] >= self.count:
                return False
            entry[1] += 1
            return True
