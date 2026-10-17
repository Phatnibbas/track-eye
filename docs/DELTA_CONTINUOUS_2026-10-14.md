# Shared output + continuous sender — deployed 2026-10-14

Tier **project/deployment**, owner-approved new output integration. Supersedes
display-left-only and finite-trial restrictions for this adapter, not robot gates.

> Latest output update: **5LOOK/s, tilt×10 capped15°, angular deadband1°**,
> bounded owner-approved robot CLEAR. See `DELTA_OUTPUT_SCALE_2026-10-14.md`;
> earlier15Hz/no-clear policies here are retained historical evidence.

## Latest owner override — 22:31 onward, Pi↔master test

Owner explicitly approved LOOK transmission despite node OFFLINE/FAULT/unhomed
reports. Deployed `node_state_policy=observe-only-owner-test`; default `gate`
profile preserved separately. This supersedes the prior fault-latched state below.

- Host no longer queries/gates on robot readiness/position/IDLE. Node diagnostics
  are recorded, not host TX blockers. Firmware's own gates remain unchanged.
- No clear/home/reset/firmware patch, no fake motor acceptance. `ERR move` and
  command rejections counted separately from sent commands and exact IK echoes.
- USB/REPL/invalid framing, unknown replies, wrong echo/reference mismatch still
  quarantine; never emit text LOOK into observed REPL.
- Source selection/freshness/mean50/50/slew, 15Hz target scheduling, 2° scale,
  3000ms first live target and 500ms subsequent requests unchanged. First wait
  only respects requested duration, not node-reported completion in this test.
- Autostart remains enabled; node-fault latch was preserved under
  `state/node-fault-owner-overridden-20261014.json` by explicit approval.
- First override startup stopped on a known partial old diagnostic. A separate
  fix discards only a recognized startup diagnostic tail with no query outstanding,
  saves raw hex and does NOT repair/count it as a valid response. Partial IK/REPL,
  unknown input or outstanding response must not be discarded. Earlier latch
  preserved as `state/partial-tail-preserved-20261014.json`.
- Latest observed state: worker PID11947 active, **632 LOOK /632 exact echoes**;
  source counts mean545/right16/left18/face53. WAIT_SOURCE when no usable source;
  remains alive and resumes only on fresh new observations.
- Raw replay through latest completed transaction in a captured live snapshot:
  **255 LOOK/255 matching standalone replies +1 startup IK**, no ERR move there.
  Snapshot ended mid-next response; its tail is explicitly excluded rather than
  counted as packet loss or reported complete. Log SHA256
  `c0ceb8ab84eed88e86939d6fe9c2b607cb9ba1db6fa1fbf5f8566ab7f3cdfea6`.
- **100/100 tests pass on Pi**, including owner-test mode transmitting through
  injected node errors/FAULT/boot, counting rejections, while still rejecting
  REPL/duplicate IK. Production camera/calibration/fallback hashes unchanged.

Current deployed config equals `config/delta-v3-stream-owner-test-20261014.json`.
Previous code/config retained at `backups/owner-test-20261014/`. Startup hardware
behavior/24-7 stability/motor delivery not certified by host echo. No reboot test.

## Owner-selected behavior

> **Prior state before explicit override: FAULT_LATCHED, no motion TX.** Service remains enabled/active
> as a visible latched worker, not active tracking. Final corrected deployment
> produced 251/251 matching LOOK then master reported `ERR n4 OFFLINE` at 22:14:32.
> Owner approved one manual resume ONLY after clean fresh validation. That check
> failed: `EVT n6 BOOT fw=3 reset=POWER_ON` followed by partial `FAULT n6 ...`;
> zero IK/LOOK TX, no clean snapshot. Latch was not removed or bypassed.

- Two usable pupil outputs: **50/50 mean of normalized XY**, then convert to polar.
- One usable eye: use remaining eye, source label LEFT/RIGHT.
- Neither eye: HEAD_POSE if production axis/sign gate and fresh candidate valid;
  otherwise fresh FACE_POSITION after runtime promote_s.
- No valid source: worker stays alive, sends no new LOOK; last movement can
  finish/hold. No body, stale HELD target or fabricated neutral output.
- Auto-start Pi service, continuous target scheduling **15 Hz**, latest-frame-only.
- No neutral command/near-neutral startup requirement. First actual live target
  takes requested **3000 ms**, waits for fresh post-duration IDLE before tracking.
  No auto-clear/home/reset/REPL recovery or firmware file writes.

Per-eye perception remains independent; averaging is only the shared actuator
adapter. Both robot eyes receive common orientation supported by current v3.

## Deployment and controls

- `track-eye-delta.service`: enabled, separate from `track-eye.service`; currently
  active **FAULT_LATCHED** and no serial ownership/TX after fault.
- Code/config/reference: `/home/pi5/track-eye-delta/`.
- Entry: `tools/delta_v3_stream.py --config config.json --emit-owner-approved`.
- Source selector: `delta_bridge/shared_source.py`; strict v3 parser/reference unchanged.
- Status: `/home/pi5/track-eye-delta/state/status.json`.
- Bounded rotating TX/RX log: `state/tx-rx.jsonl`, 10 MiB ×4 including current.
- Fault latch: `state/fault-latch.json`. USB/REPL/invalid framing, failed echo,
  unsafe robot state after tracking locks output; no automatic recovery/retry.
- Stop: `sudo systemctl stop track-eye-delta` (stops new TX, **not** motor STOP).
- Disable autostart: `sudo systemctl disable --now track-eye-delta`.
- Do not delete fault latch without inspecting reason and fresh live robot state.

Boot waits for unique CH340 VID/PID and by-id path, allowing USB port relocation.
CH340 has no unique serial; >1 matching adapter blocks, not guessed selection.
One sender owns serial, one production process owns camera. Only HTTP observation,
no second camera open. Systemd restart=no; worker stays visibly fault-latched.

Config starts with trial mapping **max 2°**, x_sign=+1,y_sign=-1,twist=0;
normal requested duration 500 ms, normalized XY slew 2 units/s. These are explicit
deployment choices, not certified signs/physical calibration or generic defaults.
Live min/max + fresh six-node ready gate apply; normal motor-step bound 2°,
first live-target bound 28° (current node range 2..30), duration 3000 ms.
No approach to a separate neutral target, no replay of historical target.

## Head limitation (not hidden)

Pi config has `head_sign_validated=false`. Head diagnostics produce raw matrix
proxies but HEAD_POSE candidate is invalid for motion. Adapter respects that gate;
**head fallback is implemented but currently inactive**, not falsely enabled.
Face fallback does run. Need labeled head-axis/sign verification before enabling
the head candidate. Current pupil quality gate also remains uncalibrated;
numeric iris-center/lid ratio 0..1 is geometric plausibility, not confidence truth.

Production `track_eye.app`/calibration/fallback files were not modified. Production
status still reports `disabled-shadow-only` because its internal selector remains
diagnostic. **External adapter now emits selected fresh candidates to hardware**;
do not use the app's shadow label to claim the whole system has no output.

## Evidence, failures retained and exact limits

Pi audit: `/home/pi5/track-eye-integration-audit-20261008/continuous-20261014/214432/`.

- Before install, current boot read-only status/CFG/neutral IK passed with original
  running master; no RAM recovery in this continuous deployment step. Earlier
  UnicodeError failure remains relevant for other physical attach/startup paths.
- Full software suite **96/96 on Pi**; Windows skips Linux transport fixtures.
- Isolated IK-only worker sample 30 s selected face and returned verified replies.
- Initial service worked but source adapter incorrectly treated `iris_inside_lid`
  as bool. Real target inspected: ratio is numeric. Corrected to finite 0..1,
  tests use actual numeric-shaped fields; earlier face-only observations retained.
- Scheduler initially waited an extra tick. Fixed TX-start-based rate limiting;
  no catch-up burst, acquire newest frame after waiting.
- Corrected 60 s live observation: **296/296 healthy**, no HTTP observation errors;
  **459 additional LOOK/459 matching echoes**, mean, single-left, single-right
  and face all observed. Invalid/duplicate/no-source keeps process running.
- Raw latest-session snapshot: **1215 LOOK /1215 standalone echoed replies**,
  startup 1 IK/1 reply, 145 status and 6 CFG. No pending command/partial RX tail
  or ERR/FAULT/WARN STOP in snapshot. Six motor targets compatible with inspected
  source, max difference 0.000532872° within numeric 0.001° bound.
- Recomputed **877 XY means** from logged actual left/right outputs/soft_limit:
  all equal configured 50/50 average. Sources count: mean877,left167,right79,face92.
- Active TX intervals: min **68.35 ms**, median **69.75 ms** (~14.3 Hz);
  short-gap median69.65 ms; zero intervals<66 ms. Long gaps are no-source/first
  movement/status queries, not claimed full-frame continuous 15 commands/s.
- Raw snapshot SHA256:
  `97a71db0ba072f18d1c0959e8857e3fc44bf54896a081e81e537918e0d55a2be`.
- Scheduler/source updates performed controlled sender stop/update/start only,
  pre-update files retained; production camera was not restarted by these actions.
- Final age-negative guard update had separate controlled sender restart; this
  last session reached **251 LOOK/251 echo**, then **n4 OFFLINE** stopped TX.
  Earlier 1215/1215 proof is a prior session, not final uninterrupted runtime.
- Read-only follow-up showed six ON/IDLE/homed/err=NONE lines, but header merged
  with old partial bytes, so not accepted as clean readiness evidence.
- Owner-approved manual resume validation failed before any command: observed
  **n6 BOOT reset=POWER_ON** + unterminated FAULT diagnostic. Zero synthetic/camera
  IK, zero status snapshots. No actual resume/latch removal/clear/home/reset.

Service enablement proves configured autostart. **No new Pi reboot/power-cycle
acceptance test was performed after installation**, and no unattended 24/7 SLA,
physical direction or independent motor precision claimed. Head branch not live
validated. A host crash cannot send STOP; firmware lacks Pi-feed watchdog.

## Next focused verification

1. Owner observes combined pupil/one-eye/face directions; keep no-source hold policy.
2. Head axis/sign check if head fallback required, not a magic flag flip.
3. Controlled power-up verification with owner at rig; preserve any reader failures,
   coordinate firmware reader fix if reproduced. No automatic flash or recovery.

No commit/push. Sender is enabled under approval but **currently fault-latched**;
continuous tracking is blocked pending fresh robot/protocol diagnosis. The feature
is deployed, not certified operational 24/7 or successfully resumed.
