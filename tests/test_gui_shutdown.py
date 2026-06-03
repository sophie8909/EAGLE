from types import SimpleNamespace

from eagle_ui import services


def test_shutdown_runtime_does_not_stop_running_experiment(monkeypatch):
    process = SimpleNamespace(pid=1234)
    state = SimpleNamespace(active_processes=[process], active_tasks=[], active_timers=[], is_stopping=False)
    calls = {"cancel": 0, "timers": 0}

    def fail(*args, **kwargs):
        raise AssertionError("shutdown_runtime must not terminate experiment processes")

    monkeypatch.setattr(services, "_cancel_tasks", lambda current_state: calls.__setitem__("cancel", 1))
    monkeypatch.setattr(services, "_deactivate_timers", lambda current_state: calls.__setitem__("timers", 1))
    monkeypatch.setattr(services, "terminate_pid_tree", fail)
    monkeypatch.setattr(services, "_terminate_active_processes", fail)
    monkeypatch.setattr(services, "_reset_runtime_state", fail)
    monkeypatch.setattr(services, "stop_microrts_gui", fail)

    message = services.shutdown_runtime(state)

    assert message == "GUI runtime shutdown complete"
    assert state.active_processes == [process]
    assert state.is_stopping is False
    assert calls == {"cancel": 1, "timers": 1}
