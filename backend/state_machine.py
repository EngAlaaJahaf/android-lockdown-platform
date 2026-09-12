"""Device State Machine (§9 / EXECUTE §34) — states + allowed transitions.

States: UNMANAGED, ENROLLMENT_PENDING, CORPORATE_STANDARD, PARTIAL_LOCKDOWN,
PHONE_ONLY, FULL_LOCKDOWN, MAINTENANCE, RECOVERY, QUARANTINE, RETIREMENT.

Any transition outside the matrix is rejected and must be audited as a
No-Transition event by the caller.
"""
from __future__ import annotations

from typing import Optional

STATES = (
    "UNMANAGED", "ENROLLMENT_PENDING", "ENROLLED", "CORPORATE_STANDARD", "PARTIAL_LOCKDOWN",
    "PHONE_ONLY", "FULL_LOCKDOWN", "MAINTENANCE", "RECOVERY", "QUARANTINE", "RETIREMENT",
)

# allowed[from_state] = set of reachable states
_ALLOWED = {
    "UNMANAGED": {"ENROLLMENT_PENDING"},
    "ENROLLMENT_PENDING": {"ENROLLED", "UNMANAGED"},
    "ENROLLED": {"CORPORATE_STANDARD", "PARTIAL_LOCKDOWN", "PHONE_ONLY",
                 "FULL_LOCKDOWN", "MAINTENANCE", "RECOVERY", "QUARANTINE", "RETIREMENT"},
    "CORPORATE_STANDARD": {"ENROLLED", "PARTIAL_LOCKDOWN", "PHONE_ONLY", "FULL_LOCKDOWN",
                           "MAINTENANCE", "RECOVERY", "QUARANTINE", "RETIREMENT"},
    "PARTIAL_LOCKDOWN": {"CORPORATE_STANDARD", "PHONE_ONLY", "FULL_LOCKDOWN",
                         "MAINTENANCE", "RECOVERY", "QUARANTINE", "RETIREMENT"},
    "PHONE_ONLY": {"CORPORATE_STANDARD", "PARTIAL_LOCKDOWN", "FULL_LOCKDOWN",
                   "MAINTENANCE", "RECOVERY", "QUARANTINE", "RETIREMENT"},
    "FULL_LOCKDOWN": {"CORPORATE_STANDARD", "PARTIAL_LOCKDOWN", "PHONE_ONLY",
                      "MAINTENANCE", "RECOVERY", "QUARANTINE", "RETIREMENT"},
    "MAINTENANCE": {"CORPORATE_STANDARD", "PARTIAL_LOCKDOWN", "PHONE_ONLY",
                    "FULL_LOCKDOWN", "RECOVERY", "QUARANTINE", "RETIREMENT"},
    "RECOVERY": {"CORPORATE_STANDARD", "ENROLLED", "RETIREMENT"},
    "QUARANTINE": {"CORPORATE_STANDARD", "RECOVERY", "RETIREMENT"},
    "RETIREMENT": set(),   # terminal
}


class StateTransitionError(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    if current not in STATES or target not in STATES:
        return False
    return target in _ALLOWED[current]


def transition(current: str, target: str,
               also_target: Optional[str] = None) -> str:
    """Checks user-enum state map + optional legacy enrollment mapping."""
    if target == "ENROLLED":
        # ENROLLED is a short-lived gateway in the fleet model; we map it on
        # to CORPORATE_STANDARD once a policy snapshot is applied.
        if not can_transition(current, "ENROLLED"):
            raise StateTransitionError(f"{current} -> ENROLLED not allowed")
        if also_target and also_target != "CORPORATE_STANDARD":
            raise StateTransitionError("post-enrollment target must be CORPORATE_STANDARD")
        return "CORPORATE_STANDARD"
    if not can_transition(current, target):
        raise StateTransitionError(f"{current} -> {target} not allowed")
    return target