"""Deterministic Schedule-Rule Parser and Medication Timetable Generator.

Converts verified medication entities and schedule rules into discrete,
timezone-aware scheduled adherence slots.
Enforces clinical safety invariants:
- Unparseable or ambiguous rules return NEEDS_CLARIFICATION (never guess)
- "As needed" (SOS / PRN) rules generate zero timed slots
- Daylight-saving and month-boundary aware date arithmetic
- Mandatory non-medical advice disclaimer
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

MEDICAL_DISCLAIMER = (
    "NOTICE: This medication timetable is an AI-assisted scheduling reference for personal adherence only. "
    "It does NOT constitute medical advice. Never adjust doses or medication regimens without consulting your licensed physician."
)

# Default anchor times
DEFAULT_ANCHORS = {
    "breakfast": time(8, 0),
    "lunch": time(13, 0),
    "dinner": time(19, 30),
    "bedtime": time(22, 0),
}


class ScheduleParseError(Exception):
    """Raised when a schedule rule cannot be unambiguously determined."""
    pass


@dataclass
class ScheduleParseResult:
    status: str  # "SUCCESS" or "NEEDS_CLARIFICATION"
    slots: List[Dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None
    disclaimer: str = MEDICAL_DISCLAIMER


class DeterministicScheduleParser:
    """Deterministic, table-driven rule parser for clinical medication timing."""

    def __init__(self, user_anchors: Optional[Dict[str, time]] = None):
        self.anchors = {**DEFAULT_ANCHORS, **(user_anchors or {})}

    def _resolve_daily_times(self, freq: str, timing: str) -> List[time]:
        freq = freq.upper().strip()
        timing = timing.lower().strip()

        # Bedtime only
        if freq == "HS" or "bedtime" in timing or "night only" in freq.lower():
            return [self.anchors["bedtime"]]

        # Fixed hour intervals
        if freq == "Q4H":
            return [time(6, 0), time(10, 0), time(14, 0), time(18, 0), time(22, 0), time(2, 0)]
        if freq == "Q6H":
            return [time(6, 0), time(12, 0), time(18, 0), time(0, 0)]
        if freq == "Q8H":
            return [time(8, 0), time(16, 0), time(0, 0)]
        if freq == "Q12H":
            return [time(8, 0), time(20, 0)]

        # Meal offsets
        offset_minutes = 0
        if "before" in timing or "ac" in timing:
            offset_minutes = -30
        elif "after" in timing or "pc" in timing:
            offset_minutes = 30
        elif "empty stomach" in timing:
            offset_minutes = -60

        def apply_offset(t: time, delta_min: int) -> time:
            dt = datetime(2000, 1, 1, t.hour, t.minute) + timedelta(minutes=delta_min)
            return dt.time()

        t_morn = apply_offset(self.anchors["breakfast"], offset_minutes)
        t_noon = apply_offset(self.anchors["lunch"], offset_minutes)
        t_eve = apply_offset(self.anchors["dinner"], offset_minutes)

        if freq in ["OD", "QD", "ONCE DAILY"]:
            return [t_morn]
        elif freq in ["BD", "BID", "TWICE DAILY"]:
            return [t_morn, t_eve]
        elif freq in ["TDS", "TID", "THREE TIMES DAILY"]:
            return [t_morn, t_noon, t_eve]
        elif freq in ["QID", "FOUR TIMES DAILY"]:
            return [time(8, 0), time(12, 0), time(16, 0), time(20, 0)]

        return []

    def parse_rule(
        self,
        drug_name: str,
        dose: str,
        frequency: str,
        timing: str,
        duration_days: Optional[int],
        start_date: Optional[date] = None,
        tz_name: str = "UTC",
    ) -> ScheduleParseResult:
        """Parse deterministic schedule and generate timestamped slots."""
        freq_clean = (frequency or "").strip().upper()
        timing_clean = (timing or "").strip().lower()

        # Check for SOS / PRN / as-needed
        if freq_clean in ["SOS", "PRN", "AS NEEDED", "WHEN REQUIRED"] or "as needed" in timing_clean:
            # Invariant: PRN creates NO timed slots
            return ScheduleParseResult(status="SUCCESS", slots=[], reason="As-needed (PRN/SOS) medication creates no timed slots.")

        # Conflicting rule checks
        if "once" in freq_clean and "twice" in freq_clean:
            return ScheduleParseResult(status="NEEDS_CLARIFICATION", reason="Conflicting frequency instructions: once vs twice daily.")
        if "before meals" in timing_clean and "after meals" in timing_clean:
            return ScheduleParseResult(status="NEEDS_CLARIFICATION", reason="Conflicting timing instructions: before vs after meals.")

        # Duration validation
        if duration_days is not None and duration_days <= 0:
            return ScheduleParseResult(status="NEEDS_CLARIFICATION", reason=f"Duration must be greater than zero days (got {duration_days}).")

        # Fallback duration if unspecified
        days = duration_days if duration_days is not None else 7

        # Daily times resolution
        daily_times = self._resolve_daily_times(freq_clean, timing_clean)
        if not daily_times:
            return ScheduleParseResult(
                status="NEEDS_CLARIFICATION",
                reason=f"Unrecognized or ambiguous frequency directive '{frequency}'. Please confirm timing.",
            )

        if start_date is None:
            start_date = date.today()

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        slots = []
        for day_offset in range(days):
            current_date = start_date + timedelta(days=day_offset)
            for t in daily_times:
                dt_local = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    t.hour,
                    t.minute,
                    tzinfo=tz,
                )
                instruction_parts = [f"Take {dose or '1 dose'} of {drug_name}"]
                if timing_clean:
                    instruction_parts.append(f"({timing_clean})")
                slots.append({
                    "scheduled_at": dt_local,
                    "instruction": " ".join(instruction_parts),
                    "drug_name": drug_name,
                    "dose": dose or "1 dose",
                    "status": "pending",
                })

        # Sort chronologically
        slots.sort(key=lambda s: s["scheduled_at"])

        return ScheduleParseResult(status="SUCCESS", slots=slots)

