from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "refill": ROOT / "tools" / "test_qmix_backend_refill.py",
    "nemesys": ROOT / "tools" / "test_nemesys_reference.py",
    "legacy": ROOT / "tools" / "legacy_qmix_pump_probe.py",
}
CONFIRM = "CONFIRM_REAL_CETONI_QMIX"


def load_tool(name: str) -> ModuleType:
    module_name = f"pump_qmix_tool_{name}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, TOOLS[name])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeQmixBackend:
    def __init__(self, events: list[str], *, fail: str | None = None, close_fails: bool = False, **_kwargs: object) -> None:
        self.events = events
        self.fail = fail
        self.close_fails = close_fails
        self.max_flow_rate_ul_min = 123.0
        self.max_volume_ml = 1.0
        events.append("construct")

    def _event(self, name: str) -> None:
        self.events.append(name)
        if self.fail == name:
            raise RuntimeError(f"{name} failed")

    def initialize(self, _configuration: Path) -> None:
        self._event("initialize")

    def reference_move(self) -> None:
        self._event("reference")

    def refill(self, _flow: float) -> None:
        self._event("refill")

    def read_fill_level(self) -> float:
        self._event("read_fill")
        return 1.0

    def read_status(self) -> bool:
        self._event("read_status")
        return False

    def generate_flow(self, _flow: float) -> None:
        self._event("flow")

    def stop(self) -> None:
        self._event("stop")

    def close(self) -> None:
        self.events.append("close")
        if self.close_fails:
            raise RuntimeError("close failed")


class FakeNemesysPump:
    def __init__(self, events: list[str], *, fail: str | None = None, close_fails: bool = False, **_kwargs: object) -> None:
        self.events = events
        self.fail = fail
        self.close_fails = close_fails
        events.append("construct")

    def _event(self, name: str) -> None:
        self.events.append(name)
        if self.fail == name:
            raise RuntimeError(f"{name} failed")

    def connect(self) -> None:
        self._event("connect")

    @property
    def device_name(self) -> str:
        return "fake-pump"

    @property
    def syringe_parameters(self) -> tuple[float, float]:
        return (1.0, 2.0)

    @property
    def maximum_volume_ul(self) -> float:
        return 1000.0

    @property
    def maximum_flow_ul_min(self) -> float:
        return 123.0

    def reference_move(self, *, timeout_s: float) -> None:
        assert timeout_s == 60.0
        self._event("reference")

    def close(self) -> None:
        self.events.append("close")
        if self.close_fails:
            raise RuntimeError("close failed")


@pytest.mark.parametrize("tool_name, backend_name", [("refill", "QmixPumpBackend"), ("nemesys", "NemesysPump"), ("legacy", "QmixPumpBackend")])
def test_import_is_inert_and_help_precedes_backend_construction(monkeypatch: pytest.MonkeyPatch, tool_name: str, backend_name: str) -> None:
    module = load_tool(tool_name)
    calls: list[str] = []

    def tripwire(*_args: object, **_kwargs: object) -> object:
        calls.append("constructed")
        raise AssertionError("backend construction must not occur")

    monkeypatch.setattr(module, backend_name, tripwire)
    with pytest.raises(SystemExit) as raised:
        module.main(["--help"])
    assert raised.value.code == 0
    assert calls == []


@pytest.mark.parametrize("tool_name, backend_name", [("refill", "QmixPumpBackend"), ("nemesys", "NemesysPump"), ("legacy", "QmixPumpBackend")])
@pytest.mark.parametrize("confirmation", [None, "", "confirm_real_cetoni_qmix", "CONFIRM_REAL_CETONI_QMIX ", " CONFIRM_REAL_CETONI_QMIX", "CONFIRM_REAL_CETONI", "CONFIRM_REAL_CETONI_QMIX_EXTRA"])
def test_missing_or_malformed_confirmation_fails_before_construction(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, backend_name: str, confirmation: str | None
) -> None:
    module = load_tool(tool_name)
    calls: list[str] = []

    def tripwire(*_args: object, **_kwargs: object) -> object:
        calls.append("constructed")
        raise AssertionError("backend construction must not occur")

    monkeypatch.setattr(module, backend_name, tripwire)
    argv = [] if confirmation is None else ["--confirm", confirmation]
    assert module.main(argv) == 2
    assert calls == []


def test_refill_valid_confirmation_reaches_existing_fake_engineering_path(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tool("refill")
    events: list[str] = []
    monkeypatch.setattr(module, "QmixPumpBackend", lambda **kwargs: FakeQmixBackend(events, **kwargs))

    assert module.main(["--confirm", CONFIRM]) == 0
    assert events[:4] == ["construct", "initialize", "reference", "refill"]
    assert events[-1] == "close"


def test_nemesys_valid_confirmation_reaches_existing_fake_engineering_path(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tool("nemesys")
    events: list[str] = []
    monkeypatch.setattr(module, "NemesysPump", lambda **kwargs: FakeNemesysPump(events, **kwargs))

    assert module.main(["--confirm", CONFIRM]) == 0
    assert events == ["construct", "connect", "reference", "close"]


def test_legacy_valid_confirmation_preserves_default_no_flow_and_opt_in_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tool("legacy")
    default_events: list[str] = []
    monkeypatch.setattr(module, "QmixPumpBackend", lambda **kwargs: FakeQmixBackend(default_events, **kwargs))

    assert module.main(["--confirm", CONFIRM]) == 0
    assert default_events == ["construct", "initialize", "close"]

    flow_events: list[str] = []
    monkeypatch.setattr(module, "QmixPumpBackend", lambda **kwargs: FakeQmixBackend(flow_events, **kwargs))
    assert module.main(["--confirm", CONFIRM, "--flow-ul-min", "1.5"]) == 0
    assert flow_events == ["construct", "initialize", "flow", "read_status", "stop", "close"]


@pytest.mark.parametrize("tool_name, backend_name, factory", [
    ("refill", "QmixPumpBackend", FakeQmixBackend),
    ("nemesys", "NemesysPump", FakeNemesysPump),
    ("legacy", "QmixPumpBackend", FakeQmixBackend),
])
def test_primary_failure_remains_controlling_when_close_also_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool_name: str,
    backend_name: str,
    factory: type[FakeQmixBackend] | type[FakeNemesysPump],
) -> None:
    module = load_tool(tool_name)
    events: list[str] = []
    failure = "reference" if tool_name != "legacy" else "initialize"
    monkeypatch.setattr(module, backend_name, lambda **kwargs: factory(events, fail=failure, close_fails=True, **kwargs))

    assert module.main(["--confirm", CONFIRM]) == 1
    assert failure in events
    assert events[-1] == "close"
    stderr = capsys.readouterr().err
    assert "failed" in stderr.lower()
    assert "connection cleanup failed" in stderr.lower()
    if tool_name == "refill":
        assert "refill" not in events


@pytest.mark.parametrize("tool_name, backend_name, factory", [
    ("refill", "QmixPumpBackend", FakeQmixBackend),
    ("nemesys", "NemesysPump", FakeNemesysPump),
    ("legacy", "QmixPumpBackend", FakeQmixBackend),
])
def test_cleanup_failure_after_success_is_non_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool_name: str,
    backend_name: str,
    factory: type[FakeQmixBackend] | type[FakeNemesysPump],
) -> None:
    module = load_tool(tool_name)
    events: list[str] = []
    monkeypatch.setattr(module, backend_name, lambda **kwargs: factory(events, close_fails=True, **kwargs))

    assert module.main(["--confirm", CONFIRM]) == 1
    assert events[-1] == "close"
    assert "connection cleanup failed" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("tool_name, backend_name, factory", [
    ("refill", "QmixPumpBackend", FakeQmixBackend),
    ("nemesys", "NemesysPump", FakeNemesysPump),
    ("legacy", "QmixPumpBackend", FakeQmixBackend),
])
def test_primary_failure_with_successful_cleanup_remains_non_success(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    backend_name: str,
    factory: type[FakeQmixBackend] | type[FakeNemesysPump],
) -> None:
    module = load_tool(tool_name)
    events: list[str] = []
    failure = "reference" if tool_name != "legacy" else "initialize"
    monkeypatch.setattr(module, backend_name, lambda **kwargs: factory(events, fail=failure, **kwargs))

    assert module.main(["--confirm", CONFIRM]) == 1
    assert events[-1] == "close"


def test_refill_keyboard_interrupt_preserves_130_when_close_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_tool("refill")
    events: list[str] = []

    class InterruptingRefill(FakeQmixBackend):
        def reference_move(self) -> None:
            self.events.append("reference")
            raise KeyboardInterrupt

    monkeypatch.setattr(
        module,
        "QmixPumpBackend",
        lambda **kwargs: InterruptingRefill(events, close_fails=True, **kwargs),
    )
    assert module.main(["--confirm", CONFIRM]) == 130
    assert events[-2:] == ["stop", "close"]


@pytest.mark.parametrize("tool_name, backend_name, factory, interruption", [
    ("nemesys", "NemesysPump", FakeNemesysPump, "reference"),
    ("legacy", "QmixPumpBackend", FakeQmixBackend, "initialize"),
])
def test_keyboard_interrupt_preserves_130_and_attempts_close(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    backend_name: str,
    factory: type[FakeQmixBackend] | type[FakeNemesysPump],
    interruption: str,
) -> None:
    module = load_tool(tool_name)
    events: list[str] = []

    class InterruptingBackend(factory):  # type: ignore[misc, valid-type]
        def _event(self, name: str) -> None:
            self.events.append(name)
            if name == interruption:
                raise KeyboardInterrupt

    monkeypatch.setattr(module, backend_name, lambda **kwargs: InterruptingBackend(events, **kwargs))
    assert module.main(["--confirm", CONFIRM]) == 130
    assert events[-1] == "close"
