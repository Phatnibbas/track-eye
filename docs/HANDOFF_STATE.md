# Handoff State — 2026-09-23

## Decision

- Shadow mechanism: operational.
- Gate 1: framework defined; acceptance collection blocked.
- Gates 2–6: blocked/not started as recorded in `PROJECT_FRAMEWORK.md`.
- Effective fallback emission: `disabled-shadow-only`.
- Do not claim validated behavior at 2 m, in adverse lighting, or with multiple
  visitors.

## Verification evidence

- Local and Pi full suites: 47/47 passed.
- Local and Pi focused fallback suites: 27/27 passed.
- Deterministic probes passed 20,000 randomized selector steps and 20,000
  codec cases on both machines.
- Pi service: active + enabled, PID `2838`, one camera owner, no restart errors.
- `/healthz`: HTTP 200, `healthy=true`, fresh frame.
- Live empty-scene sample: 600 reads over 29.95 seconds, zero HTTP/invariant
  failures, 476 source frames, 600 `NONE/INVALID`, fps
  min/median/max `15.03/16.21/16.87`.
- All sampled candidate ages were nonnegative; `frame_sequence == sample_id`.
- Production had no stale raw/output eyes in all 600 no-face samples.
- Fallback checksum remained `33c86e3c36ab90f7`.
- Output calibration checksum remained
  `8782caf8391b6dd3e9f8321d09b818f537293bb7d571e95ed5a75b045ebb4a2f`.
- Emission remained `disabled-shadow-only`; HOG body remained invalid and
  unselected; `validation_data/` remained empty.

The validation found and fixed one real selector defect: initial acquisition
from `NONE` bypassed `promote_s`. Initial pupil and degraded candidates now
obey the configured stability interval. The regression failed before the fix
and passes afterward. No timing value or fallback configuration changed.

## Runtime identity (local == Pi)

- `track_eye/app.py`: `8121a23c333350b69c556efc238609b00f27374af5fd7c80003b7d5c5943a1dd`
- `track_eye/fallback.py`: `8c4ddfd34c6932750e8c7e73ed35e392073392465e3b882799ed3ccf426aa5ab`
- `tests/test_fallback.py`: `1e4d34fc8eae8aa2136e4b36d7d7431dd50c9c97ce4c9b1c7577683fc683ec9f`
- `track_eye/pupil_quality.py`: `97034dbcc5cf2aa39aec9579eab910ff4c320c603139ea8413786a533c3a53fe`
- `track_eye/shadow.py`: `3e11f751f1667653f947818005cbdacef329c71a4e702146f2ce5ee0f5efd784`
- `track_eye/validation.py`: `54b64d77c53761ae4b3f4655f15bb3b68dee64e8c71bc16179000eac50c0dd9f`
- `fallback-config.json`: `76345b7d2b9318a736d58e530583c7f1a45601900c1c6503c605a9025dce8144`
- `models/face_landmarker.task`: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`

## Documentation identity (local == Pi after sync)

- `AGENTS.md`: `ab407da040ec001db5534e9603a9c9e5899ee16bcf6a90e816692dd80b0af253`
- `README.md`: `3715607c756aba7ad57a5970a895887246d66d8c38bddcfcf2edc26546c398e6`
- `docs/PROJECT_FRAMEWORK.md`: `dc4d4739c60a4ba1c930166fdd0315ab23f60f82f1c0da8af69286af2853bf35`
- `docs/PI5_DEPLOYED_STATE.md`: `001d447d08ad948ee2ba75f12a9d65ed266e857a1a792a25d9adc6e6b021e085`
- `docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md`: `3e07db707ea511cf0ecdfb213de098bd6348cf3427489df93b1f591770e15d05`
- `docs/GATE1_PROTOCOL_TEMPLATE.md`: `b4aea9ba38793fe0a1895dd4fc3760cd6f63cd594093dfbdf63cd796356343c6`

## Corrected framework findings

- Current token is checked in the JSON body, not as an HTTP bearer token.
- Missing capture metadata still defaults to `"unlabeled"`; current tooling is
  not acceptance-ready.
- Exposure metadata is caller-supplied, not camera-control readback.
- Participant and visit IDs are absent, so split leakage cannot be audited.
- Keep-five cleanup is not auditable specific-session deletion.
- `TrackedVisitor.nearest` does not implement multi-person tracking: detectors
  collapse candidates before it and it only logs a nearest source center.
- `max_held_s` provides a software bound, but its value and all selector timing
  remain behaviorally unvalidated.
- Per-slot slew can make effective left/right outputs differ transiently while
  converging to one shared degraded-source target; Gate 3/rig acceptance must
  decide whether that transition is acceptable.

## Finalized execution plan — pupil, head, face only

Body/person fallback is deferred. Keep its diagnostics available, keep
`body_enabled=false`, and do not spend this slice replacing or tuning HOG.
Active priority is:

```text
PUPIL -> HEAD -> FACE -> HELD -> INVALID
```

Execute in this order:

1. **Gate 1 preflight**
   - enforce strict scenario/lighting/consent/split metadata;
   - add opaque participant and visit IDs;
   - read actual camera exposure controls;
   - configure validation auth outside Git;
   - freeze metric definitions, numerical limits, confidence target, and
     collection matrix.
2. **Pupil validity**
   - label each eye independently for center/left/right/up/down, blink,
     one-eye occlusion, glasses, distance, and lighting;
   - fit quality thresholds only on `tuning`;
   - exit when both eyes have accepted horizontal/vertical separation,
     bounded head leakage/jitter/latency, quantified false accept/reject, and a
     frozen one-eye-loss policy on `heldout`.
3. **Head fallback**
   - collect mirrored-path neutral, yaw-left/right, pitch-up/down, still, and
     eyes-only episodes;
   - establish axes/signs, monotonic range, neutral/scale, jitter, availability,
     eyes-only leakage, and latency;
   - set `head_sign_validated=true` only after frozen held-out evidence passes.
4. **Face fallback**
   - measure raw-frame recall, empty-scene false activation, confidence,
     box stability, direction, ROI/gain, latency, and reacquisition across
     distance, lighting, pose, and partial occlusion;
   - specify spatial visitor acquisition/retention/handoff without identity
     recognition;
   - freeze score threshold and mapping only after held-out evidence passes.
5. **Selector calibration**
   - freeze source mappings first;
   - tune promotion, demotion, absolute hold, absence expiry, and per-slot slew
     on complete tuning episodes;
   - verify priority, bounded freeze/transition step, no avoidable `INVALID`,
     no source flapping, and accepted one-eye-loss behavior.
6. **Held-out shadow acceptance**
   - freeze code/model/config/calibration checksums;
   - report coverage, first-motion latency, maximum frozen interval, jitter,
     transition step, false activation, source-flap rate, and FPS per condition
     and worst condition;
   - keep emission disabled after software acceptance; transport and rig remain
     separate Gates 5–6.

Previous runtime rollback:
`/home/pi5/track-eye-rollbacks/20260916-094907-blocker-sweep/`.

Current fallback rollback:
`/home/pi5/track-eye-rollbacks/20260923-161342-fallback-validation/`.

Documentation rollback:
`/home/pi5/track-eye-rollbacks/20260923-160019-framework-audit/`.
