"""Owner-selected binocular XY mean/single-eye/head/face adapter.

Consumes published observations, never changes tracking or fabricates quality.
Head requires the production axis/sign gate. No body or held-shadow replay.
"""
from dataclasses import dataclass
import math

from .core import finite_number


@dataclass(frozen=True)
class SharedTarget:
    source: str
    xy: tuple[float, float] | None
    reason: str


def bounded_pair(values):
    if not isinstance(values, (list, tuple)) or len(values) != 2 or not all(finite_number(v) for v in values):
        return None
    return tuple(max(-1.0, min(1.0, v)) for v in values)


class SharedSelector:
    def __init__(self, frame_max_age_s, candidate_max_age_s, require_inside_lid):
        for value in (frame_max_age_s, candidate_max_age_s):
            if not finite_number(value) or value <= 0:
                raise ValueError('explicit positive freshness bounds required')
        if type(require_inside_lid) is not bool:
            raise ValueError('explicit geometry plausibility policy required')
        self.frame_age = frame_max_age_s
        self.candidate_age = candidate_max_age_s
        self.inside = require_inside_lid
        self.reset()

    def reset(self):
        self.previous_sequence = None
        self.previous_uptime = None
        self.pending_source = None
        self.pending_since = None

    def _none(self, reason):
        self.pending_source = self.pending_since = None
        return SharedTarget('NONE', None, reason)

    def select(self, status, now, receive_age_s):
        if (not isinstance(status, dict) or not finite_number(now) or not finite_number(receive_age_s)
                or receive_age_s < 0):
            return self._none('invalid status/clock')
        age = status.get('last_frame_age_seconds')
        if (status.get('healthy') is not True or status.get('capture_alive') is not True
                or not finite_number(age) or age < 0 or age + receive_age_s > self.frame_age):
            return self._none('capture unavailable or stale')
        baseline = status.get('baseline')
        tuning = status.get('output_tuning')
        if (not isinstance(baseline, dict) or baseline.get('state') != 'idle'
                or not isinstance(tuning, dict) or tuning.get('load_error') is not None
                or tuning.get('neutral_state') != 'idle'):
            return self._none('baseline/calibration operation or load error')
        seq, uptime = status.get('frame_sequence'), status.get('uptime_seconds')
        if type(seq) is not int or seq <= 0 or not finite_number(uptime) or uptime < 0:
            return self._none('invalid production sequence/uptime')
        if (self.previous_sequence is not None and (seq < self.previous_sequence or uptime < self.previous_uptime)):
            self.reset()
            self.previous_sequence, self.previous_uptime = seq, uptime
            return self._none('production restarted; discard old decision')
        if self.previous_sequence is not None and seq <= self.previous_sequence:
            # Sampling at 15 Hz may see the same ~14 Hz camera frame twice.
            # Do not refresh/send it, but don't restart candidate promotion
            # merely because an otherwise-fresh frame was sampled twice.
            return SharedTarget('NONE', None, 'duplicate production frame; no replay')
        self.previous_sequence, self.previous_uptime = seq, uptime
        fallback = status.get('fallback')
        if not isinstance(fallback, dict) or fallback.get('sample_id') != seq or fallback.get('config_error') is not None:
            return self._none('missing/inconsistent source observations')
        config = fallback.get('config')
        if not isinstance(config, dict):
            return self._none('missing runtime source configuration')
        calibration = tuning.get('calibration')
        gain = calibration.get('gain') if isinstance(calibration, dict) else None
        soft = gain.get('soft_limit') if isinstance(gain, dict) else None
        eyes = []
        for slot in ('left', 'right'):
            eye = status.get('output_' + slot)
            observation = fallback.get('pupil_' + slot)
            quality = observation.get('quality') if isinstance(observation, dict) else None
            inside_ratio = quality.get('iris_inside_lid') if isinstance(quality, dict) else None
            if (status.get('face_detected') is not True or not isinstance(eye, dict)
                    or not finite_number(soft) or soft <= 0 or not isinstance(observation, dict)
                    or observation.get('valid') is not True
                    or (self.inside and (not finite_number(inside_ratio) or not 0 <= inside_ratio <= 1))):
                eyes.append(None)
                continue
            values = (eye.get('x'), eye.get('y'))
            eyes.append(bounded_pair(tuple(v / soft for v in values)) if all(finite_number(v) for v in values) else None)
        left, right = eyes
        if left is not None and right is not None:
            self.pending_source = self.pending_since = None
            return SharedTarget('PUPIL_BOTH_MEAN', tuple((a+b)/2 for a,b in zip(left,right)),
                                '50/50 normalized XY; published geometry validity, not labeled tracking truth')
        if left is not None or right is not None:
            self.pending_source = self.pending_since = None
            return SharedTarget('PUPIL_LEFT' if left is not None else 'PUPIL_RIGHT',
                                left if left is not None else right, 'single usable eye')
        candidates = fallback.get('candidates')
        head_blocked = config.get('head_sign_validated') is not True
        for source, key in (('HEAD_POSE', 'head_pose'), ('FACE_POSITION', 'face_position')):
            cand = candidates.get(source) if isinstance(candidates, dict) else None
            age = cand.get('age_s') if isinstance(cand, dict) else None
            if (not isinstance(cand, dict) or cand.get('valid') is not True
                    or not finite_number(age) or age < 0 or not 0 <= age + receive_age_s <= self.candidate_age
                    or (source == 'HEAD_POSE' and head_blocked)):
                continue
            target = bounded_pair(cand.get('target'))
            source_policy = config.get(key)
            promote = source_policy.get('promote_s') if isinstance(source_policy, dict) else None
            if target is None or not finite_number(promote) or promote < 0:
                continue
            if self.pending_source != source:
                self.pending_source, self.pending_since = source, now
            if now - self.pending_since < promote:
                return SharedTarget('NONE', None, 'promote-gated ' + source)
            return SharedTarget(source, target, 'fresh candidate; head axis/sign blocked' if head_blocked
                                else 'fresh candidate; not pupil motion')
        return self._none('no fresh usable source; head axis/sign unvalidated' if head_blocked else 'no fresh usable source')


def slew_xy(previous, target, elapsed_s, limit_per_s):
    if (bounded_pair(previous) is None or bounded_pair(target) is None or not finite_number(elapsed_s)
            or elapsed_s < 0 or not finite_number(limit_per_s) or limit_per_s <= 0):
        raise ValueError('invalid explicit slew input')
    dx, dy = target[0]-previous[0], target[1]-previous[1]
    distance = math.hypot(dx, dy)
    scale = 1.0 if distance == 0 else min(1.0, elapsed_s*limit_per_s/distance)
    return previous[0]+dx*scale, previous[1]+dy*scale
