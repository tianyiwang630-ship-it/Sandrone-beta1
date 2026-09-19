"""One lightweight supervisor per execution, without a starvation-prone pool."""
from concurrent.futures import Future
import threading
import time


class ExecutionThreads:
    def __init__(self):
        self._lock = threading.Lock()
        self._threads = set()
        self._closing = False

    def submit(self, function, *args):
        future = Future()

        def run():
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(function(*args))
                    except BaseException as exc:
                        future.set_exception(exc)
            finally:
                with self._lock:
                    self._threads.discard(threading.current_thread())

        with self._lock:
            if self._closing:
                raise RuntimeError("Execution supervision is shutting down")
            thread = threading.Thread(target=run, daemon=True)
            self._threads.add(thread)
            thread.start()
        return future

    def shutdown(self, wait=True):
        with self._lock:
            self._closing = True
            threads = list(self._threads)
        if wait:
            deadline = time.monotonic() + 3
            for thread in threads:
                thread.join(timeout=max(0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads):
                raise TimeoutError("Execution supervision has not finished shutting down")
