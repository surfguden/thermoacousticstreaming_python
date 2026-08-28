from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar


T = TypeVar("T")


class EvidenceBasis(str, Enum):
    REQUESTED = "requested"
    APPLIED = "applied"
    OBSERVED = "observed"
    DERIVED = "derived"


class EvidenceFreshness(str, Enum):
    FRESH = "fresh"
    CACHED = "cached"
    UNKNOWN = "unknown"


class VerificationScope(str, Enum):
    SOFTWARE = "software"
    PROTOCOL = "protocol"
    PHYSICAL = "physical"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class EvidenceValue(Generic[T]):
    value: T | None
    basis: EvidenceBasis
    freshness: EvidenceFreshness
    verification: VerificationScope
    observed_at_utc: datetime | None
    source_operation: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SubsystemEvidence:
    values: dict[str, EvidenceValue[Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceSnapshot:
    captured_at_utc: datetime
    camera: SubsystemEvidence
    tec: SubsystemEvidence
    pump: SubsystemEvidence
    valve: SubsystemEvidence
    experiment: SubsystemEvidence


class RuntimeEventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING_CONFIGURATION = "blocking_configuration"
    HARDWARE_FAULT = "hardware_fault"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    timestamp_utc: datetime
    severity: RuntimeEventSeverity
    subsystem: str
    operation: str
    message: str
    may_continue: bool
    operator_next_action: str | None = None
    evidence_refs: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        severity: RuntimeEventSeverity,
        subsystem: str,
        operation: str,
        message: str,
        may_continue: bool,
        operator_next_action: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> "RuntimeEvent":
        return cls(
            timestamp_utc=datetime.now(timezone.utc),
            severity=severity,
            subsystem=subsystem,
            operation=operation,
            message=message,
            may_continue=may_continue,
            operator_next_action=operator_next_action,
            evidence_refs=evidence_refs,
        )
