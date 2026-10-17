# Pi5 Deployed State

## Current native-ROI acquisition — 2026-10-17

Owner approved software acquisition improvements while retaining normal FACE
fallback when pupil is unusable. Production now uses one existing full-range
detector before one FaceMesh call: cold/lost acquisition takes a native1.8×
padded selected crop, maps all landmarks back to original pixels, and measures
with unchanged aperture-v1 math. Healthy full-frame/ROI paths retain their mode;
ROI follows accepted mesh bounds. A0.6s reference rejects nonoverlapping visitors;
this is not identity/re-ID or multiple-visitor acceptance. Empty cold failures
do not repeatedly restart the graph. No thresholds/models, gain units, calibration
values, head-sign/body gates, hardware protocol or sender policy changed.

- Eight source/tool/test paths hash-verified local↔Pi; production is the
  pre-upgrade baseline plus UI diagnostics and this ROI delta, not the R1 visitor
  pipeline. Manifest/evidence linked below.
- Local175 tests pass; Pi34 focused tracker/shadow/math/calibration tests pass.
  Real models on both hosts: fresh full-frame failed at controlled photographic
  detector widths~65/91/104px while ROI succeeded; both succeeded~145/227px.
  Both retained10/10 shrinking warm samples; new blank-loss/reacquisition clears
  stale eyes/EMA. These are controlled image transforms, not labeled2m trials.
- Actual Pi pre-render captures178+91 frames contained torso/empty/desk scenes,
  no usable face. Detector false positives occurred; they do not validate pupil
  quality or distance recall. Derived metadata retained; task JPEGs deleted
  deliberately after analysis. Capture token/drop-in removed; controls400 again.
- Real Chromium desktop1440px/mobile390px: actual1280×720 camera JPEG loaded,
  no horizontal overflow/browser errors. Live ROI, per-slot geometry,
  **pre-EMA → raw-after-EMA → tuned output** all observed.
- Unchanged aperture-v1 formula has a separate vertical sensitivity: halve
  lid aperture while holding corners/iris fixed and vertical output doubles.
  No formula/calibration migration or unvalidated pupil-confidence gate added.
- Post-deploy150 live samples over30.410s:457 frames,15.028fps;137 ROI/13 full-frame,
  133 mesh-positive snapshots. Source snapshots include mean/single-eye/FACE/
  no-source. Scene-dependent counts are not accuracy or distance acceptance.
- Sender was stopped while six nodes initially OFFLINE/unhomed; failures
  preceded this algorithm deployment. Later node BOOT overlapped one malformed
  status header, retained as failed evidence. A NEW complete clean status/CFG/IK
  query showed six ONLINE/IDLE/homed/error-free, faultfalse; no header repair.
- First resumed unchanged sender session reported360 LOOK/360 matching echoes,
  including one initial FAULT move rejection and one existing-policy bounded
  CLEAR/OK CLEAR. No further rejection during the30s monitor. Echo is not MOVE ACK.
  After stopping it, fresh nodes reported IDLE positions11.539/14.577/19.045°
  for both eyes versus1.993° before; reported feedback, not independent mechanical
  direction/accuracy certification. No HOME/reset/firmware flash was sent.
- Final resumed session observed307 LOOK/307 echoes, zero rejection/CLEAR.
  Camera PID136647 and sender PID146887 active/enabled, NRestarts0, one owner per
  camera/serial device, no drop-in, health200. Saved calibration remained clean:
  gain3.9/3/3.45/3.7, limit1.0, two neutrals,
  SHA`2f797a4c4ab2f1f43bd50b50352075b8bf4911c5de87441287af90e3b28c4749`.
  Sender checksum pin unchanged. Old observe-only owner-test policy remains,
  not fail-closed installation acceptance; RAM/reboot limitations remain.

Evidence: [`deploy/roi-acquisition-20261017T114130Z/verification.json`](../deploy/roi-acquisition-20261017T114130Z/verification.json).
Exact rollback checkpoints/metadata: `archive/roi-acquisition-20261017T114130Z/`
and `/home/pi5/track-eye-research/roi-acquisition-20261017T114130Z/`.

Persistence checkpoint: the exact saved calibration is also versioned at
[`deploy/roi-acquisition-20261017T114130Z/output-calibration.saved.json`](../deploy/roi-acquisition-20261017T114130Z/output-calibration.saved.json),
SHA`2f797a4c4ab2f1f43bd50b50352075b8bf4911c5de87441287af90e3b28c4749`.
This is an explicit recovery snapshot, not an automatic restore profile.
The local ignored `output-calibration.json` was refreshed from the Pi, not the
reverse; runtime calibration and participant data remain excluded from ordinary
source sync. Save/sync required no service restart or tuning change.

## Historical face/pupil diagnostic UI — 2026-10-17

Owner reported unreliable cold/reacquisition around2m, retained tracking after
closer acquisition, and a visible face despite the UI saying NO FACE.
That distance behavior is an accepted owner observation, not a measured success
rate from this session.

**Deployed change is presentation only:** `track_eye/web.py`, `rendering.py`
and diagnostic serialization in `app.py`. Tracking, models, thresholds, selector,
gains/signs and sender algorithms remain the pre-upgrade baseline. Visitor/YOLOX
pipeline remains absent/disabled; independent full-range detection does not
initialize FaceMesh. Public `face_detected` retains its original landmark
meaning and false still implies no raw/output eyes.

- Web separates Full-range detector, FaceMesh landmarks, pupil geometry for
  each display slot, tuned XY and internal shadow (explicitly not hardware).
  Shows detector score/native bbox pixels and pupil width/radius/aperture/
  inside-lid geometry. Availability is not calibrated pupil confidence.
- Camera overlay now has two compact diagnostic lines and a yellow independent
  detector box, even when FaceMesh is absent. Removed misleading NO FACE and
  BOTH PUPILS TRACKED assertions. Error/stale/disabled states do not display old
  detections as current; desktop/mobile layouts were exercised in real Chromium.
- Live pre-change150 samples contained5 detector-valid/mesh-absent observations;
  exact status/JPEG frame IDs37241 and37254 were paired. A fully visible135px
  face in37254 had production landmarks, but fresh local full-frame replay did
  not. Observing internal graph outputs showed detection score0.601, one ROI,
  zero accepted landmark sets. Same JPEG cropped243×228 around the independent
  detector box returned landmarks at unchanged thresholds; subsequent warm
  calls used prior landmark ROIs without another detection packet.
- This implicates acquisition/ROI/landmark acceptance, not just missing initial
  detection. Replay used compressed rendered JPEGs on local Mac, not raw Pi
  frames or labeled2m trials. The partial-out-of-frame37241 crop also failed
  and is not used as proof of a fully visible-face bottleneck. No thresholds
  were lowered and the crop path was not deployed.
- Before the necessary camera restart, stopped the sender, checkpointed disk/
  RAM and saved the exact current tuning through `/output/save`: gain
  **3.9/3/3.45/3.7**, soft_limit1.0, two original neutrals. Readback and restart
  preserve these values; dirty=false/load_error=null.
  New calibration SHA:
  `2f797a4c4ab2f1f43bd50b50352075b8bf4911c5de87441287af90e3b28c4749`.
  Updated only the matching pin in current local/Pi profile and installed sender
  config, retaining root ownership/mode. Previous saved95f6a91e… is backed up.
- Camera PID91620 and sender PID91756 active, unique camera/serial owners.
  Before sender resume obtained fresh status/CFG/calculation-only IK: all six
  online/homed/error-free. No new CLEAR/HOME/reset/flash or policy change.
- Existing153 tests pass in the isolated Pi tree; local153 passed before final
  presentation-only refinements. Six UI fixture states exercised, plus actual
  Pi desktop1440px/mobile390px with loaded1280×720 image and no browser errors.
  Post-deploy150 samples over~30s:14.22fps, no invariant/protocol/rejection errors,
  LOOK44→171 with matching echoes;142 detector+mesh,1 mesh-only,7 detector-only.
  Scene changed; these counts are not tracking accuracy or distance acceptance.

Current evidence:
[`deploy/face-acquisition-20261017T110216Z/verification.json`](../deploy/face-acquisition-20261017T110216Z/verification.json).
Detailed metadata/audit: `archive/face-acquisition-20261017T110216Z/` and
`/home/pi5/track-eye-research/face-acquisition-20261017T110216Z/`.
Old observe-only owner-test/RAM master/reboot limitations below still apply.

## Historical E2E restoration — 2026-10-17

Owner explicitly authorized CLEAR and restoration of the old running chain.
Camera and sender source remain the synchronized pre-upgrade `b8387c0` baseline;
no algorithm upgrade was deployed. Camera was not restarted during restoration.

### Changes and verified prerequisites

- Confirmed a clean MicroPython prompt after the prior traceback; inspected
  surviving `Master/main/P/K` globals and WDT disabled. Read actual board files
  with small streaming hashes: main/proto3/spm_ik/neutral3/eyes all five match
  inspected local/Pi reference bytes.
- Restarted the already-loaded command loop once, with RAM-only
  `AUTO_HOME_AT_START=False`, `AUTO_REHOME=False`,
  `Master.resend_last_move=no-op`. No source import/recompile, reset or flash.
  Both eyes loaded neutral15/15/15, active eyes1+2.
- Sent one explicit owner-authorized `clear`; received `OK CLEAR`. Fresh status
  before/after reports all six ONLINE, IDLE, homed, errNONE, master faultfalse.
  Positions were1.993° before camera output; this is not a neutral15° position.
- Actual status/CFG/typed-IK validation completed10/10 synthetic queries,
  maximum reference error0.000477°, no motion. The initial camera-only IK window
  skipped all10 unavailable pupil samples; it is not camera E2E proof.
- Updated only `calibration_sha256` in installed sender config and
  `config/delta-v3-stream-current-pi5.json`: old47cfed0f… → actual saved95f6a91e….
  Full saved SHA:
  `95f6a91e3809b9f57666f9f1063e13ec088a0b2352fa07206ef2af2cef62fa13`.
  Config SHA is now
  `1c5750bcabcac6a66d4ebebd19115928a637ff83efba62e8104394578aa573ea`.
  Root ownership/mode retained. The stale checksum latch was archived, not
  discarded; calibration/fallback/firmware source files were not overwritten.
- Existing sender code SHA remains
  `11d805d02c652b6388f77584d431c44b876a868e1c9b16b60034fb5e08af199d`;
  selector SHA remains
  `24e60d3aa1cbb75cd427b774737f82066d58e9a7a925e1139ec6b6c4e92538ce`.
  Same binocular-mean/single-eye/face policy, head-sign gatefalse, 5Hz target,
  tilt×10/cap15°, deadband1°, first request3000ms then500ms, freshness250ms.
- Completed sender session: independent replay verifies **1325/1325 LOOK**
  plus one startup calculation-only IK against actual received wire bytes and
  six live CFG/reference limits, max reference error0.000529°, no robot/command
  errors, no pending reply excluded. Stop completed normally, exit0/no latch.
  Log-entry spacing minimum0.196s is post-write logging, not an exact UART TX
  timestamp; do not assert a strict measured0.200s floor from it.

### Final exercised state

- Read-only live monitor: **300 samples over300.04s**, no health/invariant,
  protocol or rejection errors, measured14.33fps by camera sequence delta.
  Sender LOOK counter advanced779→1325 during this window. Sources observed:
  two-eye pupil, either single eye, FACE_POSITION and explicit WAIT_SOURCE.
  WAIT_SOURCE/deadband pause is expected, not replay or a fabricated fresh target.
- After the completed run, temporarily stopped only the sender to obtain a
  fresh actual node query with exclusive serial ownership. All six ONLINE,
  IDLE, homed, errNONE, faultfalse. Positions1/4=16.457°,2/5=20.555°,
  3/6=8.389° versus1.993° before motion; reported targets16.461/20.549/8.384°.
  This is node-reported position feedback, not independent installation/gaze
  accuracy or externally observed mechanical-direction certification.
- Final sender restarted after complete readback/drain and left **active**:
  PID43166, same unit/ExecStart, NRestarts0; fresh94LOOK/94echo observed afterwards.
  Camera PID14833 remained active throughout restoration, health200,
  decoded JPEG1280×720, unique camera owner. Sender alone owns ttyUSB0.
  Both services enabled, no drop-in, no camera restart or calibration save.
- Final RAM tuning observed3.9/3/3.45/3.7, limit1.0, two original neutrals,
  dirty=true/load_error=null. Saved disk remains10/3/2.5/6.2, limit1.5 and SHA95f6a91e….
  Preserve both: do not discard live tuning by restarting camera. A later
  deliberate Save must also update the sender pin while sender is stopped;
  its periodic protected-file check correctly rejects an uncoordinated change.
- No HOME/reset/flash, altered travel/signs, new algorithm, new commit or push.
  This verifies a running established E2E session, not reboot/24-7 reliability.
  Compact evidence:
  [`deploy/e2e-restore-20261017T102933Z/verification.json`](../deploy/e2e-restore-20261017T102933Z/verification.json).

### Preserved failures and operating limits

Two startup attempts are preserved: supervision first read a stale old status
file and stopped during startup; existing cancellation code then sent CFG and
latched missing-CFG. The next start rejected an orphaned partial CFG prefix.
A maintenance session completed fresh status/CFG/IK before the successful start.
No parser allowlist was relaxed and no partial frame counted as a valid reply.

An initial long-window sampler aborted immediately on `dirty=true`: live tuning
had changed, not a serial fault. Saved disk stayed10/3/2.5/6.2, limit1.5, two
neutrals. Observed RAM became3.9/3/3.45/3.7, limit1.0 with the same neutrals.
These live values were preserved without automatically saving over disk.

The restored policy is still **observe-only-owner-test**: host output is not
fail-closed on node readiness, and bounded robot-error CLEAR is enabled as in
the old profile (5s cooldown, three consecutive attempts, ACK required).
Do not treat this as an unattended installation safety profile. No HOME/reset,
firmware write or new algorithm. The firmware reader's prior UnicodeError path
is not repaired by RAM recovery; recurrence must stop/quarantine, not auto-retry.
RAM overrides are lost on master reset; power-cycle/USB reconnect and24/7
operation have not been accepted by this restoration.

Evidence and backup root:
`/home/pi5/track-eye-integration-audit-20261008/e2e-restore-20261017T102933Z/`;
local copy: `archive/e2e-restore-20261017T102933Z/`.
Contains sender/config/state backup, actual board hashes, recovery/CLEAR raw
records, validation, preserved failed starts and live-wire evidence.

## Historical rollback — 2026-10-17 17:20 +07

Owner requested rollback before the algorithm upgrade and a simpler field
pipeline. Selected commit: `b8387c02988b1d2eee8ad5d19d74d31360e2d676`,
the 10:26 local/Pi synchronization checkpoint. It retains the existing Delta
integration but predates R1/visitor/YOLOX changes.

- Local branch: `rollback/pre-upgrade-20261017T101814Z`, based at `b8387c0`.
  No new commit, history rewrite or push. Runtime code is exactly the baseline;
  only current context/design notes and rollback evidence are added afterwards.
- Pi: 127/127 baseline tracked files byte-matched before restart. Removed 63
  known post-upgrade/research paths, all checkpointed first; unrelated legacy
  files, `.venv`, `benchmark_data/` and `validation_data/` were not deleted.
- `track-eye.service` active/running, PID14833, NRestarts0, original ExecStart,
  no drop-ins, sole `/dev/video0` owner. No visitor pipeline or YOLOX remains
  in active source. Original head/face/HOG shadow diagnostics remain as baseline;
  the proposed lean pipeline has not been implemented/deployed.
- `track-eye-delta.service` was active PID750 after a reboot, already latched
  on calibration-checksum mismatch, LOOK/echo counters0. Explicitly stopped
  before camera mutation; MainPID0, failed/exit1 retains the latch, enabled
  unchanged. USB is now present but has no owner; no fresh robot state queried.
  No serial commands, CLEAR/HOME, firmware change or sender resume.
- Saved calibration untouched: SHA256
  `95f6a91e3809b9f57666f9f1063e13ec088a0b2352fa07206ef2af2cef62fa13`,
  gains10/3/2.5/6.2, soft_limit1.5, both neutrals, dirty=false, load_error=null.
  The baseline loader was exercised against this document before restart;
  values match the pre-upgrade live calibration snapshot.
- Fallback, external sender config and sender tool hashes unchanged. Sender
  still pins old calibration SHA `47cfed0f…`; restoring old calibration or
  clearing the latch to bypass it is not part of this rollback. Stop is not a
  motor STOP. Both services remain enabled; no reboot acceptance is claimed.

Verification: 153/153 tests pass locally and in an isolated Pi baseline tree.
Post-rollback HTTP/output smoke: 150 healthy samples over30.04s, measured
14.35fps by sequence delta, no invariant/HTTP errors, JPEG1280×720, health200.
All150 observations had production face output and the offline shared selector
chose PUPIL_BOTH_MEAN; that exercise opened no serial link. Publish-to-HTTP
age P95 was64.6ms, **not capture-to-decision latency**. No fatal camera startup
traceback/error observed. These results do not certify 3m pupil accuracy.

Evidence: [`deploy/rollback-20261017T101814Z/verification.json`](../deploy/rollback-20261017T101814Z/verification.json),
[`smoke.json`](../deploy/rollback-20261017T101814Z/smoke.json) and
[`source-manifest.json`](../deploy/rollback-20261017T101814Z/source-manifest.json).
Simplified installation design: `PROJECT_FRAMEWORK.md`, installation redesign.

Recovery checkpoints (not commands to auto-restore):

- Local: `/Users/makerlabvn/orca/projects/track-eye-rollback-backups/20261017T101814Z/`;
  `local-worktree-before.tar.gz`, `working.diff`, `checkpoint.json`, ignored weights.
- Committed R1 preserved by branch `backup/pre-rollback-20261017T101814Z`
  at `b88ebb5`; uncommitted Nano/context/evidence preserved in stash
  `49c64f99219c411e1f347f10d9487be7ff268a84`.
- Pi: `/home/pi5/track-eye-rollback-backups/20261017T101814Z/`;
  `pi-source-before.tar.gz`, `sender-state-before.tar.gz`, `units.before.txt`.

## Historical preservation snapshot — 2026-10-17 10:26 +07

This section and the older bodies below are historical observations from the
preservation sync, not the current service/calibration state above.

| Service | Live identity observed for this snapshot | Ownership |
|---|---|---|
| `track-eye.service` | PID `726`, active since 2026-10-14 21:41:32 +07, `NRestarts=0` | Unique camera owner; `/home/pi5/track-eye`, canonical `track_eye/` |
| `track-eye-delta.service` | PID `30339`, active since 2026-10-14 22:50:31 +07, `NRestarts=0` | Unique Delta serial owner; `/home/pi5/track-eye-delta`, external `delta_bridge/` |

These are dated observations, not a guarantee about a future PID or device state.
The local tree now preserves both the canonical tracker and the external Delta
bundle (tools, tests/fixtures, firmware reference, profiles and service unit).
The external sender is active and emits shared binocular-mean, single-eye or
valid-face targets. Head remains sign-gated (`false`). The internal
`track_eye.app` fallback remains `disabled-shadow-only`; it neither invokes the
binary codec nor sends hardware commands.

The deployed external policy is `observe-only-owner-test`: LOOK may be sent
despite node readiness diagnostics; this is not a safe default deployment profile.
Current scheduling is capped at 5 Hz, tilt is multiplied by 10 and capped at
15°, with a 1° angular direction deadband after scaling/capping. Previously
owner-approved robot-error auto-CLEAR is bounded by 5 s cooldown and 3 consecutive
attempts; geometry/USB/REPL failures do not authorize recovery. This sync does
not authorize CLEAR, HOME, reset, replay, firmware flash or a sender restart.
The active policy is recorded, not newly approved by these documents.

**Calibration has two distinct states; preserve both without saving or restart.**
Disk gains (left/right/up/down) are `3/3/2.5/3.75`, with no saved neutrals.
RAM gains are `10/3/2.5/6.2`, with two neutrals and `dirty=true`. Saving would
overwrite the disk evidence; restarting would discard the unsaved RAM state.
Read `deploy/pi5-snapshot-2026-10-17/manifest.json` for exact preserved paths and
`deploy/pi5-snapshot-2026-10-17/runtime-observation.json` for the dated runtime
observation, alongside the saved calibration, live tuner snapshot and current
Delta configuration in that snapshot directory.

Latest baseline inspected for this sync: `20261014-200150`, tracking
`738/1166 = 63.3%`, zero camera read failures. It supersedes September
“latest-inspected” wording, but does not certify direction, motor completion,
accuracy, unattended reliability or hardware safety.

This is preservation/source synchronization only: no upgrade, service restart,
hardware change or calibration persistence. Commit is local only; no push is
implied. Historical test counts below are not verification of this sync.

### Synchronization verification

- Integrated suite: **153/153 passed locally** and **153/153 passed on Pi**.
  Pi used a clean Git-equivalent checkpoint with the existing production venv;
  the deployed root's legacy `test_rendering.py`/`test_web.py` collide with
  combined-suite discovery after Delta tools prepend the root to `sys.path`.
  No legacy runtime file was deleted and no import workaround was added.
- Removed imported assertions tied to human error wording and a host-speed
  quota of 100 status replies in 1.2 seconds. Kept error types, readiness,
  no-motion, no-retry and protocol behavior assertions; runtime code is unchanged.
- Post-sync read-only smoke: 20 HTTP samples, 41 fresh-frame sequence advances,
  14.02–14.85 reported fps, health HTTP 200 and decoded 1280×720 JPEG.
  No stale-eye, frame/sample mismatch or health violations. The offline shared
  selector consumed live HTTP observations: 15 pupil-mean and 5 no-source samples;
  it did not open serial or send commands.
- Camera/sender PIDs remained `726`/`30339`; saved config, installed service units
  and the active sender source matched the preserved checksums. RAM tuning
  remained dirty. Full evidence: `deploy/pi5-snapshot-2026-10-17/verification.json`.
- Common tracked files are mirrored under `/home/pi5/track-eye`. The running
  sender remains under `/home/pi5/track-eye-delta`; it was not restarted or moved.
  Pre-sync overwritten files are backed up under
  `/home/pi5/track-eye-sync-backups/20261017-pre-upgrade/`.
- Ignored local `archive/` preserves audit evidence, sender logs/backups and
  root-level legacy copies. These are not active source or committed participant
  captures. Ordinary sync must continue preserving Pi-owned calibration/data.

## 2026-09-23 fallback mechanism validation

Authoritative observations after deploying the initial-promotion fix:

- `track-eye.service` active and enabled; PID `2838` was the single canonical
  process and sole `/dev/video0` owner;
- `/healthz` returned HTTP 200 with fresh capture;
- fallback config checksum remained `33c86e3c36ab90f7`;
- output calibration checksum remained
  `8782caf8391b6dd3e9f8321d09b818f537293bb7d571e95ed5a75b045ebb4a2f`;
- emission remained `disabled-shadow-only`; calibration, head sign, and body
  selection remained disabled;
- fallback source SHA-256:
  `8c4ddfd34c6932750e8c7e73ed35e392073392465e3b882799ed3ccf426aa5ab`;
- fallback test SHA-256:
  `1e4d34fc8eae8aa2136e4b36d7d7431dd50c9c97ce4c9b1c7577683fc683ec9f`;
- 27/27 focused fallback tests and 47/47 full tests passed locally and on Pi;
- a deterministic property probe passed 20,000 randomized selector steps and
  20,000 codec cases identically on local and Pi;
- a 600-read, 29.95-second live empty-scene sample had zero HTTP/invariant
  failures, 476 source frames, 600 `NONE/INVALID` decisions, no future
  candidate timestamps, and 15.03/16.21/16.87 minimum/median/maximum reported
  fps;
- production `face_detected=false` implied all raw/output eyes were absent in
  all 600 samples; shadow decisions never replaced production output;
- HOG body remained invalid and unselected;
- `validation_data/` remained empty.

The audit found one selector defect: source `promote_s` was enforced only when
replacing an existing source, not during initial acquisition from `NONE`.
`FallbackSelector` now gates initial pupil and degraded candidates as well.
The regression failed before the fix and passes after it. Active-age
diagnostics are also clamped nonnegative for synthetic and live clocks.

No accepted timing value changed; `fallback-config.json` was not modified.
The service was intentionally recycled to load the corrected selector. No
post-restart service errors were present.

Rollback:
`/home/pi5/track-eye-rollbacks/20260923-161342-fallback-validation/`.

Decision: fallback priority, state, codec, freshness, hold, and transition
mechanisms pass software validation. Behavioral source validity, mappings,
timings, multi-person behavior, effective emission, transport, and rig remain
blocked.

## 2026-09-16 shadow deployment and post-deployment audit

Deployed shadow components:

- `track_eye/fallback.py`: six-state selector, strict schema-1 config, monotonic timing, bounded slew/hold machinery, tested 20-byte codec;
- `track_eye/shadow.py`: pinned Tasks Face Landmarker, full-range FaceDetection, HOG latest-frame body worker;
- `track_eye/pupil_quality.py`: per-eye geometry and calibrated-output-domain velocity diagnostics;
- `track_eye/validation.py`: explicit mirrored pre-render JPEG capture, manifest, decision rows, summary, cleanup;
- `track_eye/app.py`: shadow composition, status, overlay, validation endpoints;
- `fallback-config.json`: `emission_enabled=false`, `calibrated=false`, checksum `c79127d8a2f23827`;
- `models/face_landmarker.task`: SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`, 3,758,596 bytes.

The audit found and corrected defects that the initial 34-test report missed:

1. synchronous head/face candidates were timestamped after the selector's `now`, so they were rejected as future samples;
2. pupil loss collapsed independent left/right held targets onto one coordinate;
3. losing the old source while a better source was inside its promotion gate could transiently emit `INVALID`;
4. malformed config types could escape safe fallback, string booleans were coerced, and the checksum omitted `pupil_quality`;
5. the codec accepted non-finite coordinates and non-positive soft limits;
6. selector pupil targets used raw rather than calibrated output coordinates;
7. out-of-frame face boxes lacked separate raw/clipped diagnostics;
8. validation rows omitted selected targets, shutdown did not finalize active capture, and same-second sessions could collide.
9. status snapshots were assembled from separate tracking/output/shadow generations, so published face/output/shadow fields could belong to different frames; publication is now atomic under one lock with same-frame tracking/output/shadow and a published FrameHub sequence.

Post-fix evidence:

- local/Pi SHA-256 matched for the seven corrected source/test files (`track_eye/fallback.py`, `track_eye/pupil_quality.py`, `track_eye/shadow.py`, `track_eye/validation.py`, `track_eye/app.py`, `tests/test_fallback.py`, `tests/test_shadow_math.py`); `track_eye/tracker.py`, `track_eye/rendering.py`, `fallback-config.json`, and the pinned model also matched their deployed hashes;
- health returned 200 with one app process, one camera owner, and steady ~13.6–13.9 fps;
- live status selected real `FACE_POSITION_DEGRADED` and used `HELD_TARGET` across intermittent face-detector misses;
- visual browser smoke showed the live frame and shadow overlay;
- repeated samples showed `frame_sequence == sample_id` and internally consistent face/pupil/shadow fields (for example `FACE_POSITION_DEGRADED` while pupils were absent);
- saved output calibration `8782caf…` and benchmark artifacts remained unchanged;
- rollback: `/home/pi5/track-eye-rollbacks/20260916-084439-fallback-audit/`.

This proves shadow execution and mechanism safety checks only. Effective fallback emission remains disabled, the codec is not called by `track_eye.app`, and no ESP32 transport exists.

Release blockers:

- head axis/sign/neutral/range and pupil-quality thresholds require labeled participant data;
- face ROI/gain/direction and transition timing require labeled installation data;
- HOG body detection produced score `0.0` on observed visitor and empty frames, so detector suitability—not only calibration—is unresolved;
- multi-person continuity/handoff is absent;
- validation captures are JPEG, omit exposure/lighting metadata, and use unauthenticated LAN controls;
- ESP32 parser/transport/watchdog and mechanical direction/slew/safe-state require hardware-in-loop validation.

## Prior snapshot validated on 2026-09-15

## Authority and paths

- SSH: `ssh pi5` (`pi5.local`, user `pi5`, key authentication).
- Deployment root: `/home/pi5/track-eye`.
- Production package: `/home/pi5/track-eye/track_eye`.
- Runtime calibration: `/home/pi5/track-eye/output-calibration.json`.
- Baseline artifacts: `/home/pi5/track-eye/benchmark_data`.
- Installed unit: `/etc/systemd/system/track-eye.service`.
- The deployment root has no `.git`; use checksums, not Git commands, to identify deployed files.

The canonical source, tests, tools, service template, install script, packaging files, README, and `servo_link.py` matched their local checksums at validation time.

## Live service

`track-eye.service` is enabled and has been active since 2026-09-11.

```ini
[Service]
Type=simple
User=pi5
WorkingDirectory=/home/pi5/track-eye
ExecStart=/home/pi5/track-eye/.venv/bin/python -u -m track_eye.app --device /dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0 --web-host 0.0.0.0 --web-port 8080
Restart=on-failure
RestartSec=5
```

Observed live status:

- process listening on `0.0.0.0:8080`;
- `/healthz` returned HTTP 200;
- `capture_alive=true`, `healthy=true`;
- last-frame age about 3 ms at inspection;
- observed processing rate about 14.2–14.4 fps;
- baseline state `idle`;
- output tuner `dirty=false`, `load_error=null`.
- all 13 current unit tests passed on the Pi;
- HTTP smoke verified a fresh JPEG with a positive frame sequence while health remained 200.

Face state was false at inspection because no face was present. Face absence is not a camera health failure.

## Camera and runtime dependencies

- Stable device: `/dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0`.
- Resolved device: `/dev/video0`.
- Negotiated format: MJPG 1280x720 at 30 fps.
- Python 3.11.15.
- MediaPipe 0.10.14.
- OpenCV 4.13.0.
- NumPy 2.4.6.
- protobuf 4.25.9.

## Persisted output calibration

The live file is valid schema version 1 and is loaded cleanly:

```json
{
  "schema_version": 1,
  "gain": {
    "left": 4.0,
    "right": 4.0,
    "up": 3.5,
    "down": 3.45,
    "soft_limit": 1.5
  },
  "neutrals": [
    {
      "name": "eye_33_133",
      "x": -0.0727347096868543,
      "y": -0.17152310101834134
    },
    {
      "name": "eye_362_263",
      "x": -0.06194965835146265,
      "y": -0.16536567220835988
    }
  ]
}
```

These are runtime-owned values, not the code defaults. Ordinary source deployment must preserve this file.

## Latest inspected baseline evidence

Artifact: `tracking-baseline-20260907-141514.json`.

- tracking: 1134/1134 frames, 100%;
- camera read failures: 0;
- average processing rate: 16.94 fps;
- p95 frame time: 63.37 ms;
- eye `33_133`: minimum horizontal separation 1.59, minimum vertical separation 1.75;
- eye `362_263`: minimum horizontal separation 0.55, minimum vertical separation 1.37;
- normalized head drift for eye `362_263` was unavailable because its horizontal separation gate failed.

Interpretation: acquisition reliability was strong for that run. Robust directional separation and head-motion rejection were not fully validated for both eyes.

The artifact's gain section uses an older report shape and predates current output tuning. It is historical measurement evidence, not the source of the live calibration above.

## Legacy files on Pi

Root-level `rendering.py`, `web.py`, `tracking_baseline.py`, `test_rendering.py`, and `test_web.py` are older leftovers. The installed unit runs `track_eye.app`, so production imports the `track_eye/` package. Do not use the root-level copies as current source.

`pupil.log` is an old/non-UTF-8 artifact. Read current service output through `journalctl`.

## Operational checks

```bash
ssh pi5
sudo systemctl --no-pager --full status track-eye.service
sudo journalctl -u track-eye.service -n 100 --no-pager
curl -s http://127.0.0.1:8080/status.json
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/healthz
```

Run current tests without releasing the camera:

```bash
cd /home/pi5/track-eye
.venv/bin/python -m unittest discover -s tests -v
```

Do not run `tools/tracking_baseline.py` while the service owns the camera. For an explicitly requested standalone baseline, stop the service, run the baseline, then restart and revalidate service health.

## Deployment protocol

1. Change tracked local source first.
2. Run focused tests and a behavioral smoke path.
3. Sync only intended files.
4. Preserve `output-calibration.json` and `benchmark_data/`.
5. Compare checksums for deployed files.
6. Restart only when intentionally deploying runtime changes.
7. Check service status, startup journal, `/healthz`, `/status.json`, and changed behavior.
8. Update this snapshot.

Never store the Pi password in the repository or agent docs.
