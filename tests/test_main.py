from __future__ import annotations

from thermo_acoustic import main as main_module
from thermo_acoustic.instruments import SimulatedAD2Sdk
from thermo_acoustic.messages import MessageName


def test_queue_smoke_entry_point_uses_simulated_ad2_and_always_cleans_up(monkeypatch, capsys):
    calls: list[object] = []

    class FakeApplication:
        status = "System Initialized"

        def __init__(self, *, ad2):
            calls.append(("construct", ad2))

        def enqueue_main(self, message):
            calls.append(("enqueue", message.name))

        def run_until_idle(self):
            calls.append("run")

        def cleanup(self):
            calls.append("cleanup")

    monkeypatch.setattr(main_module, "Application", FakeApplication)

    main_module.main()

    assert isinstance(calls[0][1], SimulatedAD2Sdk)
    assert calls[1:] == [("enqueue", MessageName.INITIALIZE), "run", "cleanup"]
    assert capsys.readouterr().out.strip() == "System Initialized"


def test_queue_smoke_entry_point_cleans_up_when_dispatch_raises(monkeypatch):
    calls: list[str] = []

    class FailingApplication:
        def __init__(self, *, ad2):
            assert isinstance(ad2, SimulatedAD2Sdk)

        def enqueue_main(self, message):
            assert message.name is MessageName.INITIALIZE

        def run_until_idle(self):
            raise RuntimeError("simulated dispatch failure")

        def cleanup(self):
            calls.append("cleanup")

    monkeypatch.setattr(main_module, "Application", FailingApplication)

    try:
        main_module.main()
    except RuntimeError as exc:
        assert str(exc) == "simulated dispatch failure"
    else:
        raise AssertionError("expected the simulated dispatch failure to propagate")

    assert calls == ["cleanup"]
