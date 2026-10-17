"""Shipment status machine (§5.4). A report can only be issued from REVIEWED,
which is principle 2.1 (the system never files) expressed as a state machine."""

from app.domain.enums import ShipmentStatus as S
from app.errors import AppError, ErrorCode

TRANSITIONS: dict[S, set[S]] = {
    S.DRAFT: {S.UPLOADING, S.ARCHIVED},
    S.UPLOADING: {S.UPLOADING, S.QUEUED, S.ARCHIVED},
    S.QUEUED: {S.PROCESSING, S.FAILED, S.ARCHIVED},
    S.PROCESSING: {S.AWAITING_REVIEW, S.FAILED, S.ARCHIVED},
    S.FAILED: {S.QUEUED, S.UPLOADING, S.ARCHIVED},
    # Re-analysis is allowed until a report has been issued.
    S.AWAITING_REVIEW: {S.REVIEWED, S.QUEUED, S.UPLOADING, S.ARCHIVED},
    S.REVIEWED: {S.REPORT_ISSUED, S.AWAITING_REVIEW, S.QUEUED, S.UPLOADING, S.ARCHIVED},
    S.REPORT_ISSUED: {S.ARCHIVED},
    S.ARCHIVED: set(),
}

# States in which documents may be added, removed or retyped.
EDITABLE = {S.DRAFT, S.UPLOADING, S.FAILED, S.AWAITING_REVIEW, S.REVIEWED}
ANALYZABLE = {S.UPLOADING, S.FAILED, S.AWAITING_REVIEW, S.REVIEWED}
DECIDABLE = {S.AWAITING_REVIEW, S.REVIEWED}


def can_transition(current: S | str, target: S | str) -> bool:
    return S(target) in TRANSITIONS[S(current)]


def assert_transition(current: S | str, target: S | str) -> None:
    if not can_transition(current, target):
        raise AppError(
            ErrorCode.SHIPMENT_NOT_REVIEWABLE,
            f"A shipment in status {S(current).value} cannot move to {S(target).value}.",
            details={"status": S(current).value, "target": S(target).value},
        )
