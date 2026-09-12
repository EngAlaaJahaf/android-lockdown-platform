# PHASE 1 REPORT — Control Plane (CLI)

Generated: 2026-09-11 23:17:43 UTC

## Registry
- devices: 4
- policies persisted: 6
- assignments recorded: 0
- evidence rows: 2
- audit entries (hash-chained): 2

## CLI surface (scripts/alp.py)
bootstrap · login · whoami · logout · devices · enroll · policies · apply ·
jobs · approvals · audit · sim · report

## Honesty invariants
- apply without --real: source=SIMULATED → PASS structurally impossible.
- apply --real: only ADB-observable lanes enter the actual map; missing lanes
  stay UNKNOWN (verdict UNKNOWN/PARTIAL, never fake PASS).
- evidence_id is minted by the Director before verification and stamped
  PENDING→result; PASS requires a real device observation.
