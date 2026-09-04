from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest

from thermo_acoustic.ad2_capture_tooling import Ad2CapturePrimaryAndCleanupError, REAL_AD2_W1_CONFIRMATION


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATHS = (
    ROOT / "tools" / "capture_ad2_wavegen_scope.py",
    ROOT / "tools" / "capture_ad2_wavegen_scope_matplotlib.py",
)


def import_tripwire_ad2():
    raise AssertionError("AD2Sdk must not be constructed during offline import")


def load_tool(path: Path, monkeypatch):
    instruments = types.ModuleType("thermo_acoustic.instruments")
    instruments.AD2Sdk = import_tripwire_ad2
    monkeypatch.setitem(sys.modules, "thermo_acoustic.instruments", instruments)
    if path.name.endswith("matplotlib.py"):
        matplotlib = types.ModuleType("matplotlib")
        matplotlib.__path__ = []
        pyplot = types.ModuleType("matplotlib.pyplot")
        matplotlib.pyplot = pyplot
        monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)
        monkeypatch.setitem(sys.modules, "matplotlib.pyplot", pyplot)
    module_name = f"{path.stem}_offline_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeAd2:
    def __init__(self, *, capture_error: BaseException | None = None, cleanup_error: BaseException | None = None) -> None:
        self.capture_error = capture_error
        self.cleanup_error = cleanup_error
        self.events: list[str] = []

    def initialize(self) -> None:
        self.events.append("initialize")

    def get_phdwf(self) -> int:
        return 1

    def config_wfg(self, _config) -> None:
        self.events.append("config_wfg")

    def capture_scope(self, **_kwargs) -> list[float]:
        self.events.append("capture_scope")
        if self.capture_error is not None:
            raise self.capture_error
        return [0.0, 0.1, 0.0]

    def wfg_start_stop_all_ch(self, _running: bool) -> None:
        self.events.append("stop_wfg")

    def cleanup(self) -> None:
        self.events.append("cleanup")
        if self.cleanup_error is not None:
            raise self.cleanup_error


class FakeAxes:
    transAxes = object()

    def plot(self, *_args, **_kwargs) -> None: pass

    def axhline(self, *_args, **_kwargs) -> None: pass

    def set_title(self, *_args, **_kwargs) -> None: pass

    def set_xlabel(self, *_args, **_kwargs) -> None: pass

    def set_ylabel(self, *_args, **_kwargs) -> None: pass

    def grid(self, *_args, **_kwargs) -> None: pass

    def text(self, *_args, **_kwargs) -> None: pass


class FakeFigure:
    number = 1

    def tight_layout(self) -> None: pass

    def savefig(self, path: Path, **_kwargs) -> None:
        Path(path).write_bytes(b"offline fake plot")


class FakePyplot:
    def subplots(self, **_kwargs):
        return FakeFigure(), FakeAxes()

    def show(self, **_kwargs) -> None: pass

    def fignum_exists(self, _number: int) -> bool:
        return False

    def pause(self, _interval: float) -> None: pass


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_ad2_capture_tool_import_is_hardware_inert(monkeypatch, path):
    module = load_tool(path, monkeypatch)

    assert module.AD2Sdk is import_tripwire_ad2


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_ad2_capture_help_is_inert_before_ad2_construction(monkeypatch, capsys, path):
    """TEST-AD2-CAPTURE-HELP-INERT-001: regression coverage for the incident."""
    module = load_tool(path, monkeypatch)

    def fail_if_constructed():
        raise AssertionError("AD2Sdk must not be constructed for --help")

    monkeypatch.setattr(module, "AD2Sdk", fail_if_constructed)
    monkeypatch.setattr(sys, "argv", [path.name, "--help"])

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 0
    assert "REAL AD2 / REAL W1 OUTPUT" in capsys.readouterr().out


@pytest.mark.parametrize("path", TOOL_PATHS)
@pytest.mark.parametrize("argv", ([], ["--confirm", "wrong-token"]))
def test_ad2_capture_requires_exact_confirmation_before_ad2_construction(monkeypatch, path, argv):
    module = load_tool(path, monkeypatch)

    def fail_if_constructed():
        raise AssertionError("AD2Sdk must not be constructed without the exact confirmation")

    monkeypatch.setattr(module, "AD2Sdk", fail_if_constructed)
    monkeypatch.setattr(sys, "argv", [path.name, *argv])

    with pytest.raises(SystemExit, match="REAL AD2 / REAL W1 OUTPUT"):
        module.main()


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_confirmed_tool_preserves_primary_failure_and_cleans_up_once(monkeypatch, path):
    module = load_tool(path, monkeypatch)
    ad2 = FakeAd2(capture_error=RuntimeError("capture failed"))
    monkeypatch.setattr(module, "AD2Sdk", lambda: ad2)
    monkeypatch.setattr(sys, "argv", [path.name, "--confirm", REAL_AD2_W1_CONFIRMATION])

    with pytest.raises(RuntimeError, match="capture failed"):
        module.main()

    assert ad2.events == ["initialize", "config_wfg", "capture_scope", "cleanup"]


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_confirmed_tool_successfully_finalizes_and_cleans_up_once(monkeypatch, tmp_path, path):
    module = load_tool(path, monkeypatch)
    ad2 = FakeAd2()
    monkeypatch.setattr(module, "AD2Sdk", lambda: ad2)
    monkeypatch.setattr(sys, "argv", [path.name, "--confirm", REAL_AD2_W1_CONFIRMATION])
    monkeypatch.setattr(module, "CSV_PATH", tmp_path / "capture.csv")
    if path.name.endswith("matplotlib.py"):
        monkeypatch.setattr(module, "PNG_PATH", tmp_path / "capture.png")
        monkeypatch.setattr(module, "plt", FakePyplot())
    else:
        monkeypatch.setattr(module, "SVG_PATH", tmp_path / "capture.svg")

    module.main()

    assert ad2.events == ["initialize", "config_wfg", "capture_scope", "stop_wfg", "cleanup"]


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_confirmed_tool_retains_primary_and_cleanup_failures(monkeypatch, path):
    module = load_tool(path, monkeypatch)
    primary_error = RuntimeError("capture failed")
    ad2 = FakeAd2(capture_error=primary_error, cleanup_error=RuntimeError("cleanup failed"))
    monkeypatch.setattr(module, "AD2Sdk", lambda: ad2)
    monkeypatch.setattr(sys, "argv", [path.name, "--confirm", REAL_AD2_W1_CONFIRMATION])

    with pytest.raises(Ad2CapturePrimaryAndCleanupError) as exc_info:
        module.main()

    assert exc_info.value.primary_error is primary_error
    assert str(exc_info.value.cleanup_error) == "cleanup failed"
    assert exc_info.value.__cause__ is primary_error
    assert ad2.events == ["initialize", "config_wfg", "capture_scope", "cleanup"]


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_captured_evidence_is_finalized_before_cleanup_failure(monkeypatch, tmp_path, path):
    module = load_tool(path, monkeypatch)
    ad2 = FakeAd2(cleanup_error=RuntimeError("cleanup failed"))
    monkeypatch.setattr(module, "AD2Sdk", lambda: ad2)
    monkeypatch.setattr(sys, "argv", [path.name, "--confirm", REAL_AD2_W1_CONFIRMATION])
    csv_path = tmp_path / "capture.csv"
    monkeypatch.setattr(module, "CSV_PATH", csv_path)
    if path.name.endswith("matplotlib.py"):
        png_path = tmp_path / "capture.png"
        monkeypatch.setattr(module, "PNG_PATH", png_path)
        monkeypatch.setattr(module, "plt", FakePyplot())
        expected_output = png_path
    else:
        svg_path = tmp_path / "capture.svg"
        monkeypatch.setattr(module, "SVG_PATH", svg_path)
        expected_output = svg_path

    with pytest.raises(RuntimeError, match="cleanup failed"):
        module.main()

    assert csv_path.exists()
    assert expected_output.exists()
    assert ad2.events == ["initialize", "config_wfg", "capture_scope", "stop_wfg", "cleanup"]
