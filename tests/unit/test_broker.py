from apps.common import broker


class Task:
    def __init__(self, fails=False):
        self.fails, self.calls = fails, []

    def apply_async(self, args, kwargs):
        self.calls.append(args)
        if self.fails:
            raise ConnectionError("redis down")


def test_hands_work_to_the_broker():
    task = Task()
    assert broker.enqueue(task, 1, "x") is True
    assert task.calls == [(1, "x")]


def test_after_a_failure_it_stops_trying_for_a_while(monkeypatch):
    """A dead broker costs one timeout per process, not one per request."""
    now = [1000.0]
    monkeypatch.setattr(broker.time, "monotonic", lambda: now[0])
    down = Task(fails=True)
    assert broker.enqueue(down, 1) is False
    healthy = Task()
    assert broker.enqueue(healthy, 2) is False  # skipped, left to the sweeper
    assert healthy.calls == []
    now[0] += broker.COOLDOWN + 1
    assert broker.enqueue(healthy, 3) is True  # probes again after the cooldown
    assert healthy.calls == [(3,)]
