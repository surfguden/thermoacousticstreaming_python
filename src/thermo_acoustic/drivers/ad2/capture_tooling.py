"""Safety support shared by the retained real-AD2 capture diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar


REAL_AD2_W1_CONFIRMATION = "CONFIRM_REAL_AD2_W1_OUTPUT"

T = TypeVar("T")


class Ad2CapturePrimaryAndCleanupError(RuntimeError):
    """Retains a failed capture operation and its secondary cleanup failure."""

    def __init__(self, primary_error: BaseException, cleanup_error: BaseException) -> None:
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        super().__init__(f"AD2 capture failed: {primary_error}; cleanup also failed: {cleanup_error}")


def require_real_ad2_w1_confirmation(confirm: str | None) -> None:
    if confirm != REAL_AD2_W1_CONFIRMATION:
        raise SystemExit(
            "Refusing REAL AD2 / REAL W1 OUTPUT without "
            f"--confirm {REAL_AD2_W1_CONFIRMATION}. This engineering diagnostic does not commission "
            "the acoustic chain, and no bundled amplitude is a trusted safe default."
        )


def run_capture_with_cleanup(ad2, capture: Callable[[], T], finalize_evidence: Callable[[T], None]) -> T:
    """Run capture/finalization, then clean up once without masking primary failures."""
    result: T | None = None
    primary_error: BaseException | None = None
    try:
        result = capture()
        finalize_evidence(result)
    except BaseException as exc:
        primary_error = exc

    cleanup_error: BaseException | None = None
    try:
        ad2.cleanup()
    except BaseException as exc:
        cleanup_error = exc

    if primary_error is not None:
        if cleanup_error is not None:
            raise Ad2CapturePrimaryAndCleanupError(primary_error, cleanup_error) from primary_error
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error
    assert result is not None
    return result
