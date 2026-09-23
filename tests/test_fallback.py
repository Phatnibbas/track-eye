import math
import time
import unittest

from track_eye.fallback import (
    Candidate,
    EyePupilObservation,
    EyeState,
    FallbackConfig,
    FallbackSelector,
    SourceKind,
    config_from_dict,
    config_to_dict,
    decode_frame,
    encode_frame,
)


def _cand(source, x=0.2, y=-0.1, age_s=0.0, valid=True, now=1000.0):
    return Candidate(source, int((now - age_s) * 1e9), x, y, valid, 1.0, {})


class PriorityTests(unittest.TestCase):
    def _selector(self, **over):
        base = config_to_dict(FallbackConfig())
        base.update({"emission_enabled": False, "body_enabled": True})
        for source in ("pupil", "head_pose", "face_position", "body_position"):
            base[source] = {**base[source], "promote_s": 0.0}
        base.update(over)
        return FallbackSelector(config_from_dict(base))

    def test_pupil_beats_every_degraded_source(self):
        sel = self._selector()
        t = 1000.0
        cands = {
            SourceKind.HEAD_POSE: _cand(SourceKind.HEAD_POSE, now=t),
            SourceKind.FACE_POSITION: _cand(SourceKind.FACE_POSITION, now=t),
            SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t),
        }
        dec = sel.update(t, None, cands, ((0.3, 0.1), (-0.2, 0.05)))
        self.assertEqual(dec.active_source, SourceKind.PUPIL_LEFT)
        self.assertEqual(dec.left_state, EyeState.TRACKED_PUPIL)

    def test_head_beats_face_beats_body(self):
        sel = self._selector()
        t = 2000.0
        dec = sel.update(t, None, {
            SourceKind.HEAD_POSE: _cand(SourceKind.HEAD_POSE, now=t),
            SourceKind.FACE_POSITION: _cand(SourceKind.FACE_POSITION, now=t),
            SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t),
        }, None)
        self.assertEqual(dec.active_source, SourceKind.HEAD_POSE)
        self.assertEqual(dec.left_state, EyeState.HEAD_POSE_DEGRADED)
        # Face alone wins over body alone.
        sel2 = self._selector()
        dec2 = sel2.update(t, None, {
            SourceKind.FACE_POSITION: _cand(SourceKind.FACE_POSITION, now=t),
            SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t),
        }, None)
        self.assertEqual(dec2.active_source, SourceKind.FACE_POSITION)
        sel3 = self._selector()
        dec3 = sel3.update(t, None, {SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t)}, None)
        self.assertEqual(dec3.active_source, SourceKind.BODY_POSITION)

    def test_full_availability_sweep_follows_priority(self):
        import itertools

        for pupil, head, face, body in itertools.product([False, True], repeat=4):
            with self.subTest(pupil=pupil, head=head, face=face, body=body):
                sel = self._selector()
                t = 11000.0
                cands = {}
                if head:
                    cands[SourceKind.HEAD_POSE] = _cand(SourceKind.HEAD_POSE, now=t)
                if face:
                    cands[SourceKind.FACE_POSITION] = _cand(SourceKind.FACE_POSITION, now=t)
                if body:
                    cands[SourceKind.BODY_POSITION] = _cand(SourceKind.BODY_POSITION, now=t)
                compat = ((0.3, 0.1), (-0.2, 0.05)) if pupil else None
                dec = sel.update(t, None, cands, compat)
                if pupil:
                    expected = SourceKind.PUPIL_LEFT
                elif head:
                    expected = SourceKind.HEAD_POSE
                elif face:
                    expected = SourceKind.FACE_POSITION
                elif body:
                    expected = SourceKind.BODY_POSITION
                else:
                    expected = SourceKind.NONE
                self.assertEqual(dec.active_source, expected)

    def test_no_invalid_while_lower_source_valid(self):
        sel = self._selector()
        t = 3000.0
        dec = sel.update(t, None, {SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t)}, None)
        self.assertNotEqual(dec.left_state, EyeState.INVALID)
        # hold_s=0.6 bridges the gap first; expiry well past hold+demote gives INVALID with zeroed coords.
        mid = sel.update(t + 0.2, None, {}, None)
        self.assertEqual(mid.left_state, EyeState.HELD_TARGET)
        dec = sel.update(t + 5.0, None, {}, None)
        self.assertEqual(dec.left_state, EyeState.INVALID)
        self.assertEqual((dec.left_x, dec.left_y, dec.right_x, dec.right_y), (0.0, 0.0, 0.0, 0.0))

    def test_body_requires_explicit_enable_flag(self):
        sel = FallbackSelector(config_from_dict(config_to_dict(FallbackConfig())))
        t = 3100.0
        dec = sel.update(t, None, {SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t)}, None)
        self.assertEqual(dec.active_source, SourceKind.NONE)
        self.assertEqual(dec.left_state, EyeState.INVALID)

    def test_shared_degraded_targets(self):
        sel = self._selector()
        t = 4000.0
        dec = sel.update(t, None, {SourceKind.FACE_POSITION: _cand(SourceKind.FACE_POSITION, x=0.4, y=0.2, now=t)}, None)
        # Slew passes the first emit through exactly.
        self.assertEqual((dec.left_x, dec.left_y), (dec.right_x, dec.right_y))

    def test_stale_candidate_rejected(self):
        sel = self._selector()
        t = 5000.0
        stale = _cand(SourceKind.HEAD_POSE, age_s=50.0, now=t)
        dec = sel.update(t, None, {SourceKind.HEAD_POSE: stale}, None)
        self.assertEqual(dec.active_source, SourceKind.NONE)

    def test_initial_sources_respect_promotion_stability(self):
        t = 5800.0
        face_selector = self._selector(
            face_position={"promote_s": 1.0, "demote_s": 0.0, "expire_s": 2.0}
        )
        first_face = face_selector.update(
            t,
            None,
            {SourceKind.FACE_POSITION: _cand(SourceKind.FACE_POSITION, now=t)},
            None,
        )
        self.assertEqual(first_face.active_source, SourceKind.NONE)
        self.assertIn("promote-gated", first_face.reason)
        self.assertGreaterEqual(first_face.source_age_s, 0.0)
        stable_face = face_selector.update(
            t + 1.1,
            None,
            {SourceKind.FACE_POSITION: _cand(SourceKind.FACE_POSITION, now=t + 1.1)},
            None,
        )
        self.assertEqual(stable_face.active_source, SourceKind.FACE_POSITION)

        pupil_selector = self._selector(
            pupil={"promote_s": 0.2, "demote_s": 0.0, "expire_s": 1.0}
        )
        first_pupil = pupil_selector.update(
            t, None, {}, ((0.2, 0.1), (-0.2, 0.1))
        )
        self.assertEqual(first_pupil.active_source, SourceKind.NONE)
        stable_pupil = pupil_selector.update(
            t + 0.3, None, {}, ((0.2, 0.1), (-0.2, 0.1))
        )
        self.assertEqual(stable_pupil.active_source, SourceKind.PUPIL_LEFT)

    def test_promotion_requires_stability(self):
        sel = self._selector(head_pose={"promote_s": 5.0, "demote_s": 0.0, "expire_s": 10.0})
        t = 6000.0
        dec = sel.update(t, None, {SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t)}, None)
        self.assertEqual(dec.active_source, SourceKind.BODY_POSITION)
        # Head appears but must wait out its promote gate.
        dec = sel.update(t + 0.1, None, {
            SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t + 0.1),
            SourceKind.HEAD_POSE: _cand(SourceKind.HEAD_POSE, now=t + 0.1),
        }, None)
        self.assertEqual(dec.active_source, SourceKind.BODY_POSITION)
        self.assertIn("promote-gated", dec.reason)
        dec = sel.update(t + 6.0, None, {
            SourceKind.BODY_POSITION: _cand(SourceKind.BODY_POSITION, now=t + 6.0),
            SourceKind.HEAD_POSE: _cand(SourceKind.HEAD_POSE, age_s=0.0, now=t + 6.0),
        }, None)
        # Head track has been continuously valid since t+0.1.
        self.assertEqual(dec.active_source, SourceKind.HEAD_POSE)

    def test_source_loss_during_better_source_promotion_holds_target(self):
        sel = self._selector(
            head_pose={"promote_s": 1.0, "demote_s": 0.0, "expire_s": 2.0},
            body_position={"promote_s": 0.0, "demote_s": 0.0, "expire_s": 2.0},
            hold_s=0.6,
            slew_per_s=100.0,
        )
        t = 6500.0
        body = _cand(SourceKind.BODY_POSITION, x=0.4, y=0.2, now=t)
        sel.update(t, None, {SourceKind.BODY_POSITION: body}, None)
        head = _cand(SourceKind.HEAD_POSE, x=-0.2, y=0.1, now=t + 0.1)
        decision = sel.update(t + 0.1, None, {SourceKind.HEAD_POSE: head}, None)
        self.assertEqual(decision.left_state, EyeState.HELD_TARGET)
        self.assertEqual(decision.active_source, SourceKind.HELD)
        self.assertEqual(
            (decision.left_x, decision.left_y, decision.right_x, decision.right_y),
            (0.4, 0.2, 0.4, 0.2),
        )

    def test_absolute_hold_bound_wins_over_large_demote(self):
        sel = self._selector(
            pupil={"promote_s": 0.0, "demote_s": 5.0, "expire_s": 1.0},
            hold_s=0.6,
            max_held_s=0.6,
            body_enabled=True,
            slew_per_s=100.0,
        )
        t = 8600.0
        sel.update(t, None, {}, ((0.4, 0.1), (0.4, 0.1)))
        held = sel.update(t + 0.2, None, {}, None)
        self.assertEqual(held.left_state, EyeState.HELD_TARGET)
        expired = sel.update(t + 5.0, None, {}, None)
        self.assertEqual(expired.left_state, EyeState.INVALID)
        self.assertEqual(expired.active_source, SourceKind.NONE)

    def test_demotion_bridges_then_hands_off(self):
        sel = self._selector(pupil={"promote_s": 0.0, "demote_s": 0.4, "expire_s": 1.0})
        t = 7000.0
        dec = sel.update(t, None, {}, ((0.5, 0.25), (0.5, 0.25)))
        self.assertEqual(dec.left_state, EyeState.TRACKED_PUPIL)
        dec = sel.update(t + 0.1, None, {}, None)
        self.assertEqual(dec.left_state, EyeState.HELD_TARGET)
        self.assertAlmostEqual(dec.left_x, 0.5, places=2)
        self.assertIn("demote-gated", dec.reason)
        dec = sel.update(t + 2.0, None, {}, None)
        self.assertEqual(dec.left_state, EyeState.INVALID)

    def test_hold_expiry(self):
        sel = self._selector(hold_s=0.6)
        t = 8000.0
        sel.update(t, None, {}, ((0.4, 0.1), (0.4, 0.1)))
        dec = sel.update(t + 0.2, None, {}, None)
        self.assertEqual(dec.active_source, SourceKind.HELD)
        dec = sel.update(t + 5.0, None, {}, None)
        self.assertEqual(dec.active_source, SourceKind.NONE)

    def test_hold_preserves_independent_pupil_targets(self):
        sel = self._selector(
            pupil={"promote_s": 0.0, "demote_s": 0.4, "expire_s": 1.0},
            hold_s=0.6,
            slew_per_s=100.0,
        )
        t = 8500.0
        expected = (-0.8, -0.4, 0.7, 0.5)
        sel.update(t, None, {}, ((expected[0], expected[1]), (expected[2], expected[3])))
        during_demote = sel.update(t + 0.1, None, {}, None)
        self.assertEqual(
            (during_demote.left_x, during_demote.left_y, during_demote.right_x, during_demote.right_y),
            expected,
        )
        during_hold = sel.update(t + 0.5, None, {}, None)
        self.assertEqual(
            (during_hold.left_x, during_hold.left_y, during_hold.right_x, during_hold.right_y),
            expected,
        )

    def test_nonfinite_and_mismatched_candidates_are_rejected(self):
        sel = self._selector()
        t = 8750.0
        bad = Candidate(SourceKind.FACE_POSITION, int(t * 1e9), math.nan, 0.0, True, 1.0, {})
        decision = sel.update(t, None, {SourceKind.HEAD_POSE: bad}, None)
        self.assertEqual(decision.active_source, SourceKind.NONE)

    def test_gated_pupil_requires_both_eyes_fresh(self):
        sel = self._selector(pupil_mode="gated")
        t = 9000.0
        ns = int(t * 1e9)
        pupils = (
            EyePupilObservation("eye_33_133", ns, 0.1, 0.1, True, 1.0, {}),
            EyePupilObservation("eye_362_263", ns, 0.2, 0.2, True, 1.0, {}),
        )
        dec = sel.update(t, pupils, {}, None)
        self.assertEqual(dec.left_state, EyeState.TRACKED_PUPIL)
        stale = (
            EyePupilObservation("eye_33_133", ns, 0.1, 0.1, True, 1.0, {}),
            EyePupilObservation("eye_362_263", int((t - 50.0) * 1e9), 0.2, 0.2, True, 1.0, {}),
        )
        dec = sel.update(t + 0.1, stale, {SourceKind.HEAD_POSE: _cand(SourceKind.HEAD_POSE, now=t + 0.1)}, None)
        # Pupil demote grace (0.4 s) bridges with HELD first; head wins after.
        self.assertEqual(dec.left_state, EyeState.HELD_TARGET)
        dec = sel.update(t + 2.0, stale, {SourceKind.HEAD_POSE: _cand(SourceKind.HEAD_POSE, now=t + 2.0)}, None)
        self.assertEqual(dec.active_source, SourceKind.HEAD_POSE)

    def test_transition_reason_and_age_exposed(self):
        sel = self._selector()
        t = 10000.0
        dec = sel.update(t, None, {}, ((0.1, 0.1), (0.1, 0.1)))
        self.assertTrue(dec.reason)
        self.assertGreaterEqual(dec.source_age_s, 0.0)


class ConfigValidationTests(unittest.TestCase):
    def test_rejects_schema_and_bounds(self):
        with self.assertRaises(ValueError):
            config_from_dict({"schema_version": 999})
        with self.assertRaises(ValueError):
            config_from_dict({**config_to_dict(FallbackConfig()), "hold_s": 99.0})
        with self.assertRaises(ValueError):
            config_from_dict({**config_to_dict(FallbackConfig()), "face_roi": [0.9, 0.9, 0.1, 0.1]})
        with self.assertRaises(ValueError):
            config_from_dict({**config_to_dict(FallbackConfig()), "pupil_mode": "magic"})
        cfg = config_from_dict(config_to_dict(FallbackConfig()))
        self.assertFalse(cfg.emission_enabled)
        self.assertFalse(cfg.calibrated)

    def test_rejects_ambiguous_types_unknown_fields_and_unimplemented_emission(self):
        base = config_to_dict(FallbackConfig())
        for change in (
            {"emission_enabled": "false"},
            {"emission_enabled": True},
            {"face_roi": [0.1]},
            {"hold_s": None},
            {"typo_field": 1},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    config_from_dict({**base, **change})

    def test_checksum_includes_pupil_quality(self):
        base = config_to_dict(FallbackConfig())
        first = config_from_dict({**base, "pupil_quality": {"gate": "first"}}).checksum()
        second = config_from_dict({**base, "pupil_quality": {"gate": "second"}}).checksum()
        self.assertNotEqual(first, second)

    def test_rejects_invalid_hold_and_body_policy(self):
        base = config_to_dict(FallbackConfig())
        with self.assertRaises(ValueError):
            config_from_dict({**base, "max_held_s": 0.1, "hold_s": 0.6})
        with self.assertRaises(ValueError):
            config_from_dict({**base, "body_enabled": "false"})
        with self.assertRaises(ValueError):
            config_from_dict({**base, "multi_person": "identify"})



class PayloadContractTests(unittest.TestCase):
    def test_exact_20_bytes_and_canonical_example(self):
        packet = encode_frame(336941, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL,
                              0.742609, 0.234397, 0.551124, 0.250003, 1.5)
        self.assertEqual(len(packet), 20)
        self.assertEqual(packet.hex(" "), "45 59 01 01 00 05 24 2d 01 01 00 00 01 ef 00 9c 01 6f 00 a7")
        decoded = decode_frame(packet)
        self.assertEqual((decoded.left_x, decoded.left_y, decoded.right_x, decoded.right_y), (495, 156, 367, 167))

    def test_every_state_round_trip(self):
        for state in (EyeState.INVALID, EyeState.TRACKED_PUPIL, EyeState.HELD_TARGET,
                      EyeState.HEAD_POSE_DEGRADED, EyeState.FACE_POSITION_DEGRADED, EyeState.BODY_POSITION_DEGRADED):
            coords = (0.0, 0.0) if state == EyeState.INVALID else (0.5, -0.25)
            packet = encode_frame(7, state, state, *coords, *coords)
            decoded = decode_frame(packet)
            self.assertEqual(decoded.left_state, state)
            self.assertEqual(decoded.right_state, state)

    def test_invalid_requires_zero(self):
        with self.assertRaises(ValueError):
            encode_frame(1, EyeState.INVALID, EyeState.TRACKED_PUPIL, 0.1, 0.0, 0.0, 0.0)
        bad = encode_frame(1, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL, 0.0, 0.0, 0.0, 0.0)
        bad = bytearray(bad)
        bad[8] = 6  # unknown left state
        with self.assertRaises(ValueError):
            decode_frame(bytes(bad))

    def test_malformed_rejected(self):
        good = encode_frame(1, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL, 0.1, 0.2, 0.3, 0.4)
        with self.assertRaises(ValueError):
            decode_frame(good[:19])
        with self.assertRaises(ValueError):
            decode_frame(good + b"\x00")
        bad = bytearray(good)
        bad[0] = 0x00
        with self.assertRaises(ValueError):
            decode_frame(bytes(bad))
        bad = bytearray(good)
        bad[2] = 0x09
        with self.assertRaises(ValueError):
            decode_frame(bytes(bad))
        bad = bytearray(good)
        bad[10] = 0x01
        with self.assertRaises(ValueError):
            decode_frame(bytes(bad))

    def test_sample_id_wraps(self):
        packet = encode_frame(2 ** 32 + 5, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(decode_frame(packet).sample_id, 5)
        packet = encode_frame(2 ** 32 - 1, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(decode_frame(packet).sample_id, 2 ** 32 - 1)

    def test_rejects_nonfinite_coordinates_and_invalid_soft_limit(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    encode_frame(
                        1, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL,
                        value, 0.0, 0.0, 0.0,
                    )
        for soft_limit in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(soft_limit=soft_limit):
                with self.assertRaises(ValueError):
                    encode_frame(
                        1, EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL,
                        0.1, 0.0, 0.0, 0.0, soft_limit,
                    )


if __name__ == "__main__":
    unittest.main()
