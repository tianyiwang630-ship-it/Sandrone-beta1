import threading

import pytest

from agent.core.execution_threads import ExecutionThreads


def test_many_waiting_parents_leave_room_for_their_children():
    executor = ExecutionThreads()
    ready = threading.Barrier(41, timeout=5)

    def parent(index):
        ready.wait()
        return executor.submit(lambda: index).result(timeout=5)

    try:
        parents = [executor.submit(parent, index) for index in range(40)]
        ready.wait()
        assert [future.result(timeout=5) for future in parents] == list(range(40))
    finally:
        ready.abort()
        executor.shutdown()
    with pytest.raises(RuntimeError, match="shutting down"):
        executor.submit(lambda: None)
