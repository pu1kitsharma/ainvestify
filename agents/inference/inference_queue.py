"""FIFO scheduling of individual local inference calls, never whole workflows."""
from collections import deque
from threading import Condition
import time


class InferenceQueue:
    def __init__(self):
        self._condition = Condition()
        self._waiting = deque()
        self._active = False

    def acquire(self, blocking=True, timeout=None):
        token = object()
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            if not blocking and (self._active or self._waiting):
                return False
            self._waiting.append(token)
            while self._active or self._waiting[0] is not token:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    self._waiting.remove(token)
                    self._condition.notify_all()
                    return False
                self._condition.wait(remaining)
            self._waiting.popleft()
            self._active = True
            return True

    def release(self):
        with self._condition:
            if not self._active:
                raise ValueError('No inference slot is held')
            self._active = False
            self._condition.notify_all()

    @property
    def waiting(self):
        with self._condition:
            return len(self._waiting)
