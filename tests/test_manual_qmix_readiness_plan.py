from __future__ import annotations

import ast
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "hardware_tests" / "manual_qmix_read_only_readiness.py"


def test_manual_qmix_readiness_is_confirmation_gated_and_outside_pytest():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "__test__ = False" in source
    assert "CONFIRM_QMIX_READ_ONLY_READINESS" in source
    assert "Refusing to open/start Qmix" in source
    assert 'output_path.open("x"' in source


def test_manual_qmix_readiness_has_no_normal_motion_or_enable_calls():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    referenced_attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert called_attributes.isdisjoint(
        {
            "clear_fault",
            "enable",
            "calibrate",
            "restore_position_counter_value",
            "set_fill_level",
            "generate_flow",
            "aspirate",
            "dispense",
        }
    )
    assert "stop_pumping" in referenced_attributes
