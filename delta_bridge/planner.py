"""Dry-run latest-target planner. No serial writer or motion enable exists here."""
from dataclasses import dataclass

from .core import Mapping, MasterState, finite_number, production_target


@dataclass(frozen=True)
class PlannerPolicy:
    frame_max_age_s: float
    local_max_age_s: float
    master_status_max_age_s: float
    proposal_rate_hz: float

    def __post_init__(self):
        for name, value in self.__dict__.items():
            if not finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be explicitly configured, finite and positive")


class ProposalPlanner:
    """One pending target, bounded local/server age and monotonic proposal cadence.

    New session/restarted frame counters clear pending state. Old targets cannot
    be replayed. A caller must separately validate rig routing/workspace and
    physical failsafe before a future emitter is implemented.
    """

    def __init__(self, mapping: Mapping, policy: PlannerPolicy):
        self.mapping = mapping
        self.policy = policy
        self.sequence = None
        self.uptime = None
        self.pending = None
        self.last_proposed_at = None
        self.last_clock = None
        self.reason = "no fresh target"
        self.superseded = 0

    def reset_session(self):
        self.sequence = self.uptime = self.pending = self.last_proposed_at = None
        self.reason = "explicit session reset; fresh target required"

    def _clock(self, now):
        if not finite_number(now) or now < 0 or (self.last_clock is not None and now < self.last_clock):
            self.pending = None
            self.reason = "invalid/non-monotonic local clock"
            return False
        self.last_clock = now
        return True

    def observe(self, status, received_at):
        if not self._clock(received_at):
            return
        if not isinstance(status, dict):
            self.pending = None
            self.reason = "malformed status"
            return
        sequence = status.get("frame_sequence")
        uptime = status.get("uptime_seconds")
        if type(sequence) is not int or sequence <= 0 or not finite_number(uptime) or uptime < 0:
            self.pending = None
            self.reason = "missing frame/session evidence"
            return
        if (self.uptime is not None and uptime < self.uptime) or (self.sequence is not None and sequence < self.sequence):
            self.reset_session()
            self.reason = "tracker restart/counter regression; discard transition sample"
            return
        self.uptime = uptime
        target = production_target(status, self.mapping, self.policy.frame_max_age_s)
        if target is None:
            self.pending = None
            self.reason = "no usable production target"
            self.sequence = sequence
            return
        if sequence == self.sequence:
            self.reason = "duplicate frame; local target age not refreshed"
            return
        self.sequence = sequence
        self.superseded += int(self.pending is not None)
        self.pending = (received_at, target)
        self.reason = "fresh target pending"

    def propose(self, master: MasterState, now):
        if not self._clock(now):
            return None
        if not master.ready(now, self.policy.master_status_max_age_s):
            # Do not retain movement across faults or readiness gaps.
            self.pending = None
            self.reason = "master status not ready/fresh; pending target discarded"
            return None
        if self.pending is None:
            return None
        received_at, target = self.pending
        if not 0 <= now - received_at <= self.policy.local_max_age_s:
            self.pending = None
            self.reason = "locally stale target"
            return None
        if self.last_proposed_at is not None and now - self.last_proposed_at < 1 / self.policy.proposal_rate_hz:
            self.reason = "rate limited; keep latest target only"
            return None
        self.pending = None
        self.last_proposed_at = now
        self.reason = "dry-run proposal only; no serial TX"
        return self.mapping.command(*target)
