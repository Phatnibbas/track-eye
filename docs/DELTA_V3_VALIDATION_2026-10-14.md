# Pi5 ↔ Delta master v3 — kết quả validation 2026-10-14

Tier **project**, không rollout production. Contract/source review:
`DELTA_V3_USB_CONTRACT_2026-10-14.md`. Owner xác nhận master↔node đã chốt chạy;
lần này kiểm chứng host/USB/parser và trial shared camera target có giám sát.

## Kết luận ở đúng mức bằng chứng

**Functional communication đã kiểm chứng:**

- Local firmware mới khớp ba file source đọc từ board byte-for-byte.
- Phiên sau RAM recovery: **3000/3000** generated IK và **18/18** live-camera IK;
  echo góc đúng, đủ 6 motor, reference numerical match, raw replay độc lập với summary.
- Một neutral `LOOK` và hai live-camera `LOOK` được gửi; **3/3** matching IK echoes.
- Status sau neutral báo đủ sáu node IDLE gần 15°; sau camera trial báo đủ sáu
  node IDLE/error-free ở target cuối. **Owner quan sát cả hai Delta có chạy**.

**Chưa được chốt "USB production ổn định":**

- Attach/open đầu lần này có invalid bytes + **UnicodeError → REPL**; original
  reader chưa được sửa. Không xóa failure khi established-session corpus pass.
- Trial camera budget 20 s **không hoàn thành**, dừng do camera unusable sau IK.
- Chưa xác nhận mechanical direction chính xác, long-distance/pupil quality,
  physical reconnect, power-cycle hoặc unattended host-freshness fail-safe.
- Không có continuous sender chạy nền, không thay production camera/fallback.

## Owner decisions/authorizations trong session

1. Đã báo robot master↔node chạy ổn; recorded as owner acceptance, không audit lại
   RF/encoder/mechanics để thay kết luận owner.
2. Duyệt đọc board + recovery RAM với auto-home/rehome tắt, không flash/move.
3. Chọn **display-left → cả 2 Delta** (same orientation), không gộp/average hai mắt.
4. Duyệt riêng **one-shot `look 0 0 0 3000`**: từ home ~1.993° tới motor-neutral
   15°, khoảng 13° motor excursion, rồi trial 2° camera có fresh gates.
5. Owner quan sát **"Cả hai Delta có chạy"**; không chọn xác nhận đúng hướng.

## Identity và conservation

- `/home/pi5/track-eye/track_eye` canonical production; local legacy tree không deploy.
- `track-eye` PID 729, NRestarts=0 xuyên các kiểm tra; health HTTP 200.
- Camera một owner, UGREEN by-id; shadow fallback vẫn disabled-shadow-only.
- Current calibration SHA256
  `47cfed0fc3641f816aa9ac5c7ac0f72d11a3ed84e3e47bc06cff658b87884983`.
  Gain 3/3/2.5/3.75, soft_limit=1.5, neutrals=[]; giữ nguyên user-owned state.
- Fallback SHA256
  `76345b7d2b9318a736d58e530583c7f1a45601900c1c6503c605a9025dce8144`, không đổi.
- Serial current by-path `platform-xhci-hcd.0-usb-0:2:1.0-port0`, CH340 1a86:7523.
- Board file neutral3: cả hai eye `(15,15,15)`; eyes.txt `12`; vergence runtime 0.
- Master/IK/proto3 hashes ghi trong contract; không ghi file board/calibration,
  không clear/home/change eyes/verg/speed/limits, không reset/Ctrl-C/Ctrl-D.
- Kernel since 20:48 tới kiểm tra 21:22 không có new entries; trước đó có
  disconnect/cắm lại. Không chứng nhận nguyên nhân hoặc lifecycle sạch.

## Failed lifecycle và RAM recovery

Probe initial-query nghe trước TX: bytes invalid + traceback main.py line 826,
`sys.stdin.read(1)` UnicodeError. Không protocol commands gửi vào REPL.

Đọc source/state bằng REPL không interrupt/reset. Source board == local.
Nạp whole-file bằng `exec(open(...).read())` bị MemoryError allocating 32000;
import lại sau gc cũng MemoryError allocating 1423. Không loop retry cùng method.
Kiểm tra globals thấy Master/main/P/K còn loaded, mới chạy lại bằng definitions
cũ với policy sau, trước khi khởi tạo master:

```text
AUTO_HOME_AT_START=False
AUTO_REHOME=False
Master.resend_last_move = no-op
```

Log có RAM_POLICY và startup master3 đúng MAC/source. Flash giữ policy true;
reset sẽ mất RAM policy. Phiên evidence này là **RAM-recovered session**, không
fresh original startup. Không làm recovery này thành automatic reconnect feature.

## Calculation corpus

Config explicit `config/delta-v3-validation-20261014.json`:
10 Hz mục tiêu, seed 20261014, 3000 commands, az axes/random decimals,
tilt 0..2°, twist=0, expected eyes 1+2, verg=0. Status mỗi 300 queries.

- Total duration **334.15 s** gồm status exchanges và 30 s camera phase.
- Generated queries **3000/3000**, camera samples **60**, camera IK **18/18**,
  **42 skipped** vì no usable production eye. Không thay fallback/neutral.
- Max same-source double-reference difference **0.000531333°**;
  tolerance **0.001°** là numeric compatibility, không motor accuracy.
- Host response timing gồm validation overhead:
  median **56.81 ms**, p95 **63.64 ms**, max **76.90 ms**.
- **13** complete six-node status snapshots, fault=False/online/homed/error-free.
- No diagnostics/failures trong corpus. No failed framing repair.
- Raw bytes strict UTF-8/newline replay xác nhận 3018 matching standalone replies,
  no outstanding query/partial tail. Source/reference không independent IK truth.

Smoke trước soak 10/10 pass; post-motion diagnostic 10/10 pass riêng. Không gộp
những sample nhỏ thành long-run motor delivery claim.

## Shared camera trial: gates và outcome

Trial config explicit `config/delta-v3-camera-trial-20261014.json`:
display-left, mapping 2°, x_sign=+1/y_sign=-1/az_offset=0/twist=0, 500 ms,
2 Hz mục tiêu, 20 s budget, fresh frame <=0.25 s, current calibration hash,
max per-command motor step 2°. Không hai camera slots độc lập trên wire.

Gate-only attempt trước authorization neutral: **0 IK/0 LOOK**, block vì current
1.993→15° vượt bound 2°; giữ artifact, không nới trial bound để ép chạy.

Owner-approved approach dùng separate explicit config:
3000 ms, max step 15°, live node limits 2..30°, timeout 12 s,
post-duration idle position tolerance 0.1°, cần 2 stable fresh snapshots.

### Neutral

- Fresh ready status + live CFG + neutral IK, không clear/home.
- **1** `look 0.000 0.000 0.000 3000`, matching echo sáu target 15°.
- Hai status sau requested duration báo sáu node IDLE, pos **14.995°**, target 15°.
- Đó là **node-reported position**, owner confirmation riêng cho physical motion.
  Không dùng optimistic n.pos do master set ở send_move để đếm completed sớm.

### Camera commands thật

```text
look 20.600 1.936 0.000 500  # latest frame_sequence 67510
look 64.553 0.638 0.000 500  # latest frame_sequence 67517
```

Mỗi command có fresh status, calculation check, newest camera frame + local
reference/live limits/step gate, matching master look echo. Khi latest frame
khác frame được probe, dùng target mới, không replay stale frame.

- Camera LOOK **2 sent / 2 echo verified**; neutral LOOK ghi riêng **1/1**.
- **5 samples skipped** do no usable eye, không thay bằng neutral/fallback.
- Run **10.60 s tổng**, dừng khi camera trở thành unusable ngay sau một IK query;
  **20 s camera trial không hoàn thành**. Không retry hoặc bật daemon.
- Original artifact thiếu camera-status row tại fail nên không chốt chính xác
  face loss/frame age/unhealthy field nào gây invalid. Không có evidence restart
  trong Pi checks. Đã thêm detailed HTTP gate logs + regression cho run kế.
- Khi abort, tool ngừng gửi; **không gửi STOP** hay neutral replacement. Lệnh cuối
  có thể hoàn tất/giữ target; firmware không có Pi-feed watchdog. "Disarm" ở tool
  nghĩa chặn TX mới, không khẳng định motor đã dừng ngay.

### Status sau trial và owner observation

Separate post-trial status cả sáu ONLINE/IDLE/homed/err=NONE:

| Node pairs | Reported position | Last target |
|---|---:|---:|
| n1, n4 | 15.300° | 15.296° |
| n2, n5 | 14.464° | 14.457° |
| n3, n6 | 15.252° | 15.249° |

Owner xác nhận thấy cả hai Delta có chạy. Direction đúng camera chưa xác nhận.
V3 không có USB `OK MOVE` hay per-MOVE node ACK; echo/status/observation được
tách riêng, không gọi chúng cùng một acknowledgment level.

## Software verification và artifact index

- Windows suite **83 total: 74 pass +9 Linux-specific skip**.
- Pi isolated workcopy **83/83 pass** (Python system 3.13).
- Pi production venv suite **47/47 pass**, không sửa production source.
- V3 actual AST parser/send_move tests; wrong eyes/vergence, missing/duplicate
  nodes, limits, REPL/duplicate/wrong echo, camera loss/stale, neutral timeout,
  no retry/clear/home, latest target và calibration-hash gates covered.
- Legacy 20261008 tests được pin immutable historical source ở
  `tests/fixtures/delta_v1_20261008/`; không dùng source v3 với expectations v1.

Pi evidence/workcopy:
`/home/pi5/track-eye-integration-audit-20261008/v3-validation-20261014/204814/`.

| Artifact | SHA256 |
|---|---|
| soak-3000-camera.jsonl | `237392e36d4002d3a2af2e20189ea54cc2cf385390077dff943c3e1572ea5e25` |
| neutral-camera-approved.jsonl | `3835116f091bec7126c3a24a541f657b0f761769903476a88848695fa0d8d46b` |
| post-trial-check.jsonl | `712a66737b5daf4df07ddc11392b731d25e66494189670a7b01af716194ef14b` |

Raw replay confirmed TX/replies: trial 4 IK +3 LOOK, all matched standalone echoes;
17 complete snapshots; no pending/partial tails. Post-check 10 IK and 3 snapshots.
Initial-query, board-read, MemoryError/recovery and gated attempt artifacts preserved.
Local downloaded evidence in approved temp `delta-v3-validation-204814/`.

## Next work, not automatic authorization

1. Controlled live-camera run with owner keeping face in frame; inspect new detailed
   gate logs. Do not silently rerun neutral/old targets after camera or serial loss.
2. Rig owner verifies shared target direction; signs remain trial config until then.
3. Author-coordinated bounded ASCII byte-reader, bad-byte reject/recovery and
   ready/version/session handshake, then fresh physical attach/reset validation.
4. Define host-loss safe state/STOP policy/watchdog before unattended daemon.
5. Keep two perception slots independent; shared-output is this explicitly chosen
   trial mode, not a general fallback/independent binocular contract.

No persistent serial service enabled, no firmware flash change, no commit/push.
