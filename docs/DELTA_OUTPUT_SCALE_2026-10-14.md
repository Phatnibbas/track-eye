# Output scale/rate/deadband update — 2026-10-14 22:50 +07

Tier **project/deployment**. Explicit owner test instructions supersede earlier
15 Hz /2° /no-CLEAR configuration. Camera perception/calibration/firmware unchanged.

## Exact output contract

1. Select shared normalized XY: mean50/50 when both usable, remaining eye when
   one usable, gated head then fresh face otherwise. Same selector as previous.
2. Explicit sign/offset mapping retained. Original trial tilt scale is 2°.
3. **Output tilt = min(15°, original tilt ×10)**. Azimuth is direction, not gain;
   twist remains0. Never multiply motor-node angles or firmware-neutral15°.
4. **Deadband1° after scale/cap**, compare to last actual wire orientation:
   `distance((tilt*cos(az), tilt*sin(az)), previous vector) <1°` → no LOOK.
   Evaluate candidate after slew also; first valid target sends, zero included.
   Small frame changes accumulate relative to last SENT target, not prior frame.
5. Maximum **5 LOOK/s**. Lower rate when held by deadband/no fresh source is intended.

Examples with normalized radius `r` (<=1):

| r | Original tilt | New tilt |
|---:|---:|---:|
| 0.1 | 0.2° | 2° |
| 0.3 | 0.6° | 6° |
| 0.5 | 1° | 10° |
| 0.75 | 1.5° | 15° |
| 1 | 2° | 15° (cap) |

Same tilt/az output at cap means no new command. Az359→1 handled geometrically,
not a spurious358° change. Deadband is NOT1 normalized XY and not1° per motor.
User confirmed angular direction semantics via question; supersedes prior0.1 XY.

Current config `config/delta-v3-stream-owner-test-20261014.json`:
`poll_hz=5`, `mapping.max_tilt_deg=2`, `tilt_multiplier=10`,
`output_tilt_cap_deg=15`, `deadband_deg=1`. Slew2 normalized units/s unchanged.
At5Hz that means max0.4 normalized-vector displacement per tick; first live target
requested3000ms, subsequent500ms. No separate neutral approach.

## Owner-approved CLEAR and robot diagnostics

Test mode `observe-only-owner-test` remains: node status doesn't block host LOOK.
Robot FAULT/ERR-node, or `ERR move` FAULT/ERROR cause pending CLEAR request.
Send only at a transaction boundary, with **5 s cooldown**, max**3 consecutive**
when error persists; require master's **OK CLEAR**. A command with matching echo
and no observed robot rejection clears the consecutive budget, not a physical
completion claim. No cached target retry; after CLEAR reacquire new HTTP target.
First new source after CLEAR may re-send even within deadband; explicit logged
exception, no blind movement replay.

No HOME/reset/flash or altered limits. CLEAR cannot repair offline connectivity,
missing home, geometry outside travel, REPL or USB. Geometry/parameter rejection
is counted, not repeatedly cleared. Startup/source/reference checks remain.

Larger finite targets outside inspected IK/travel are still sent for owner test;
master owns rejection. No automatic cap reduction beyond15° or forced success.
New reply must be standalone/echo correct to count; error response counted separately.

## Deployment and observed results

- Service `track-eye-delta` enabled/active, current sampled PID30339.
- Code/config `/home/pi5/track-eye-delta/`, status and rotating logs under `state/`.
- Previous config/code preserved in `backups/5hz-15deg-20261014/` and
  `backups/angular-deadband-20261014/`.
- First update startup failed on old partial IK suffix from controlled stop.
  Original log retained. Fix: finish in-flight transaction on SIGTERM; at startup
  permit only recognized pre-query stale motor-list suffix (or known diagnostic)
  to be logged/discarded. Never discard REPL/full IK/unknown pending new replies.
  Original fault saved as `state/old-response-tail-preserved-20261014.json`.
- Dedicated tests cover gain/cap, angular wrap, deadband accumulation, bounded
  CLEAR/ACK/cooldown/exhaustion, no CLEAR on geometry, protocol gates retained.
- Last completed-transaction live raw replay **229 LOOK /229 matching replies**
  +1 startup IK, zero rejections. Actual tilt**0.144..15.000°**.
- TX intervals min**0.201957s**, median**0.203523s** (~4.91Hz while sending).
  No sub0.2s burst; zero deadband violations in229 actual LOOKs.
- Worker sample showed135 deadband skips; 55 additional commands in20s, other
  ticks skipped for source/deadband. Do not report5 every second irrespective of input.
- **No live CLEAR occurred in this measured sample** because no robot fault.
  CLEAR behavior verified in tests, not falsely reported as live hardware proof.
- Raw completed log SHA256
  `cf0c720594aeec6d156ace07d0495b7835896a4cf90b546fa69bc13bf256a290`.
- Evidence: `/home/pi5/track-eye-integration-audit-20261008/continuous-20261014/214432/`
  `5hz-15deg-completed-log.jsonl`, `5hz-15deg-raw-report.json`, observation, tests.

Motor targets may differ strongly/nonlinearly from polar tilt due IK/neutral;
do not treat motor excursion as an extra output gain requirement. Physical
direction/accuracy and startup24/7 remain unverified. Camera app unchanged,
head axis/sign still gated. No commit/push or firmware write.
