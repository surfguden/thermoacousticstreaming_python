from __future__ import annotations

import pytest

from thermo_acoustic.application import Application
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig, build_hardware_bundle
from thermo_acoustic.tec import (
    TEC_TARGET_MAX_C,
    TEC_TARGET_MIN_C,
    MeerstetterTecBackend,
    SimulatedTecBackend,
    TecAbortedError,
    TecController,
    TecError,
    TecStatus,
)
from thermo_acoustic.workflows import Experiment2, ExperimentSeries2, TemperatureSeries


class RecordingTecBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.status = TecStatus(
            current_temperature_c=25.0,
            target_temperature_c=25.0,
            output_stage_static_on=False,
            ready=True,
        )

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))

    def read_status(self) -> TecStatus:
        self.calls.append(("read_status",))
        return self.status

    def set_output_stage_static_on(self) -> None:
        self.calls.append(("set_output_stage_static_on",))
        self.status = TecStatus(
            current_temperature_c=self.status.current_temperature_c,
            target_temperature_c=self.status.target_temperature_c,
            output_stage_static_on=True,
            ready=True,
        )

    def set_target_temperature(self, temperature_c: float) -> None:
        self.calls.append(("set_target_temperature", temperature_c))
        self.status = TecStatus(
            current_temperature_c=temperature_c,
            target_temperature_c=temperature_c,
            output_stage_static_on=self.status.output_stage_static_on,
            ready=True,
        )

    def write_config(self) -> None:
        self.calls.append(("write_config",))


class FailingStatusTecBackend(RecordingTecBackend):
    def read_status(self) -> TecStatus:
        self.calls.append(("read_status",))
        raise TecError("status read failed")


def test_temperature_series_parses_comma_and_semicolon_text():
    series = TemperatureSeries.from_text("20.0, 21.5; 23")

    assert series.temperature_points_c == [20.0, 21.5, 23.0]
    assert series.enabled is True


def test_temperature_series_rejects_targets_outside_local_safety_range():
    with pytest.raises(ValueError, match="local safety range"):
        TemperatureSeries.from_text(str(TEC_TARGET_MIN_C - 0.1))

    with pytest.raises(ValueError, match="local safety range"):
        TemperatureSeries(temperature_points_c=[TEC_TARGET_MAX_C + 0.1])


def test_tec_controller_defaults_to_disabled_simulation_without_hardware():
    controller = TecController()

    assert controller.enabled is False
    assert controller.simulate is True
    assert isinstance(controller._backend(), SimulatedTecBackend)


def test_tec_controller_applies_static_setpoint_and_writes_config():
    backend = RecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend)

    controller.initialize()
    status = controller.apply_static_setpoint(18.5)

    assert status.target_temperature_c == pytest.approx(18.5)
    assert status.current_temperature_c == pytest.approx(18.5)
    assert backend.calls == [
        ("connect",),
        ("read_status",),
        ("set_output_stage_static_on",),
        ("set_target_temperature", 18.5),
        ("write_config",),
        ("read_status",),
    ]


def test_tec_controller_initialize_closes_backend_when_status_read_fails():
    backend = FailingStatusTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend)

    with pytest.raises(TecError, match="status read failed"):
        controller.initialize()

    assert controller.initialized is False
    assert backend.calls == [("connect",), ("read_status",), ("close",)]


def test_tec_controller_waits_for_stable_status_without_hardware_sleep():
    backend = SimulatedTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend)
    controller.initialize()
    controller.apply_static_setpoint(20.0)

    status = controller.wait_until_stable(
        20.0,
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )

    assert status.ready is True
    assert status.current_temperature_c == pytest.approx(20.0)


def test_tec_controller_wait_until_stable_supports_abort(monkeypatch):
    backend = RecordingTecBackend()
    backend.status = TecStatus(
        current_temperature_c=10.0,
        target_temperature_c=20.0,
        output_stage_static_on=True,
        ready=False,
    )
    controller = TecController(enabled=True, simulate=True, backend=backend)
    controller.initialize()
    monkeypatch.setattr("thermo_acoustic.tec.time.sleep", lambda _seconds: None)

    calls = 0

    def should_abort() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    with pytest.raises(TecAbortedError, match="aborted"):
        controller.wait_until_stable(
            20.0,
            tolerance_c=0.1,
            min_settle_s=0.0,
            max_wait_s=10.0,
            poll_interval_s=1.0,
            should_abort=should_abort,
        )


def test_tec_controller_wait_until_stable_times_out_explicitly(monkeypatch):
    backend = RecordingTecBackend()
    backend.status = TecStatus(
        current_temperature_c=10.0,
        target_temperature_c=20.0,
        output_stage_static_on=True,
        ready=False,
    )
    controller = TecController(enabled=True, simulate=True, backend=backend)
    controller.initialize()
    monkeypatch.setattr("thermo_acoustic.tec.time.sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="did not stabilize"):
        controller.wait_until_stable(
            20.0,
            tolerance_c=0.1,
            min_settle_s=0.0,
            max_wait_s=0.0,
            poll_interval_s=0.001,
        )


def test_real_meerstetter_backend_without_reviewed_client_refuses_to_connect():
    backend = MeerstetterTecBackend(port="COM9")

    with pytest.raises(TecError, match="No Meerstetter TEC client is configured") as error:
        backend.connect()

    assert "no device connection was attempted" in str(error.value)


def test_factory_selected_real_tec_refuses_before_client_or_device_io():
    bundle = build_hardware_bundle(
        HardwareRuntimeConfig(
            ad2_enabled=False,
            sim_ad2=True,
            camera_enabled=False,
            sim_camera=True,
            pump_enabled=False,
            sim_pump=True,
            valve_enabled=False,
            sim_valve=True,
            z_enabled=False,
            thorlabs_apt_serial="44533854",
            valve_resource="COM9",
            cetoni_config_path="unused",
            tec_enabled=True,
            sim_tec=False,
            tec_port="COM9",
        )
    )

    assert isinstance(bundle.tec.backend, MeerstetterTecBackend)
    assert bundle.tec.backend.client_factory is None
    assert bundle.tec.backend.client is None

    with pytest.raises(TecError, match="No Meerstetter TEC client is configured"):
        bundle.tec.initialize()

    assert bundle.tec.initialized is False
    assert bundle.tec.backend.client is None


def test_application_temperature_series_sets_each_target_then_runs_group(tmp_path):
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append((str(self.experiment_series.series_path), experiment.repeat_id))
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0), Experiment2(repeat_id=1)]),
    ]

    assert app.run_temperature_series(series, groups) is True
    assert [call for call in backend.calls if call[0] == "set_target_temperature"] == [
        ("set_target_temperature", 20.0),
        ("set_target_temperature", 25.0),
    ]
    assert app.run_calls == [
        (str(tmp_path / "t1"), 0),
        (str(tmp_path / "t2"), 0),
        (str(tmp_path / "t2"), 1),
    ]


def test_application_temperature_series_aborts_during_tec_stabilization(tmp_path):
    class AbortableTec(TecController):
        def __init__(self) -> None:
            super().__init__(enabled=True, simulate=True, backend=SimulatedTecBackend())
            self.targets = []

        def apply_static_setpoint(self, temperature_c: float) -> TecStatus:
            self.targets.append(temperature_c)
            return TecStatus(current_temperature_c=temperature_c, target_temperature_c=temperature_c)

        def wait_until_stable(self, target_temperature_c: float, **kwargs) -> TecStatus:
            should_abort = kwargs["should_abort"]
            assert should_abort() is True
            raise TecAbortedError("simulated abort")

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=AbortableTec())
            self.abort_checks = 0

        def listen_abort(self) -> bool:
            self.abort_checks += 1
            return self.abort_checks >= 2

        def run_experiment2(self) -> bool:
            raise AssertionError("experiment group must not run after TEC wait abort")

    app = TemperatureRunApplication()
    series = TemperatureSeries(temperature_points_c=[20.0], max_wait_s=10.0)
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]

    assert app.run_temperature_series(series, groups) is False
    assert app.status == "TemperatureSeriesAborted"


def test_application_temperature_series_rejects_mismatched_group_count(tmp_path):
    app = Application()
    series = TemperatureSeries(temperature_points_c=[20.0, 25.0])
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2()])]

    with pytest.raises(ValueError, match="group count"):
        app.run_temperature_series(series, groups)


# -- Phase 1 of the v2 sequence-visualization feature: SetTecTarget/
# WaitTecStable wrap run_temperature_series()'s own TEC calls, once per
# temperature point (not folded into run_experiment2()'s own per-repeat
# steps -- see application.py's STEP_* design note for why). These tests
# confirm that placement precisely; run_experiment2()'s own step events are
# already covered exhaustively in test_full_flow_dry_run.py, so
# run_experiment2() is stubbed here rather than duplicated.


def _record_progress():
    calls: list[tuple[str, object]] = []

    def progress(kind: str, value: object) -> None:
        calls.append((kind, value))

    return progress, calls


def test_run_temperature_series_fires_set_tec_target_and_wait_tec_stable_per_point(tmp_path):
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls: list[str | None] = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append(progress)
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
    ]
    progress, progress_calls = _record_progress()

    assert app.run_temperature_series(series, groups, progress=progress) is True

    started = [value for kind, value in progress_calls if kind == "step_started"]
    completed = [value for kind, value in progress_calls if kind == "step_completed"]
    # One SetTecTarget/WaitTecStable pair per temperature point (2 points),
    # not one per repeat, and not folded into run_experiment2()'s own steps
    # (run_experiment2() is stubbed to fire none itself here).
    assert started == ["SetTecTarget", "WaitTecStable", "SetTecTarget", "WaitTecStable"]
    assert completed == started
    assert progress_calls == [] or all(kind != "step_failed" for kind, _ in progress_calls)
    # The same progress callable was threaded down into run_experiment2()
    # for both repeats, not silently dropped.
    assert app.run_calls == [progress, progress]


def test_run_temperature_series_step_failure_in_set_tec_target(tmp_path):
    class BrokenTecController(TecController):
        def apply_static_setpoint(self, temperature_c: float):
            raise RuntimeError("boom: apply_static_setpoint")

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=BrokenTecController(enabled=True, simulate=True, backend=SimulatedTecBackend()))

        def run_experiment2(self, progress=None) -> bool:
            raise AssertionError("run_experiment2 must not run after SetTecTarget fails")

    app = TemperatureRunApplication()
    series = TemperatureSeries(temperature_points_c=[20.0])
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]
    progress, progress_calls = _record_progress()

    with pytest.raises(RuntimeError, match="boom: apply_static_setpoint"):
        app.run_temperature_series(series, groups, progress=progress)

    assert [value for kind, value in progress_calls if kind == "step_started"] == ["SetTecTarget"]
    assert [value for kind, value in progress_calls if kind == "step_completed"] == []
    assert progress_calls[-1] == ("step_failed", ("SetTecTarget", "boom: apply_static_setpoint"))


def test_run_temperature_series_step_failure_in_wait_tec_stable(tmp_path):
    class BrokenTecController(TecController):
        def wait_until_stable(self, *args, **kwargs):
            raise RuntimeError("boom: wait_until_stable")

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=BrokenTecController(enabled=True, simulate=True, backend=SimulatedTecBackend()))

        def run_experiment2(self, progress=None) -> bool:
            raise AssertionError("run_experiment2 must not run after WaitTecStable fails")

    app = TemperatureRunApplication()
    series = TemperatureSeries(temperature_points_c=[20.0])
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]
    progress, progress_calls = _record_progress()

    with pytest.raises(RuntimeError, match="boom: wait_until_stable"):
        app.run_temperature_series(series, groups, progress=progress)

    assert [value for kind, value in progress_calls if kind == "step_started"] == ["SetTecTarget", "WaitTecStable"]
    assert [value for kind, value in progress_calls if kind == "step_completed"] == ["SetTecTarget"]
    assert progress_calls[-1] == ("step_failed", ("WaitTecStable", "boom: wait_until_stable"))
