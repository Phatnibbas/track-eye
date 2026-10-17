# Track Eye — context hiện hành

## Current authority override — 2026-10-17 preservation sync

Read `PI5_DEPLOYED_STATE.md` for the current dated two-service identity,
calibration RAM/disk divergence and snapshot references. Local source now includes
canonical tracker and external Delta bundle. Sender PID30339 is active with
5 Hz maximum, tilt×10 capped15°, 1° scaled-direction deadband and bounded
robot-error CLEAR (5 s/max3); policy remains `observe-only-owner-test`.
Mean/single-eye/face is external output; head gate remains false; internal
fallback is shadow-only. “Final”, left-only, no-sender, 15 Hz and no-clear
statements below describe earlier checkpoints, not this current state.
No new motion/recovery authorization, restart, upgrade, calibration save or push
is implied. Disk calibration and dirty RAM calibration must both be preserved.
Historical counts below are not tests of the October17 source sync.

Cập nhật 2026-10-14. Đây là tài liệu cấp **project**, checkpoint không tự cấp
phép chạy lại chuyển động hoặc bật sender production.

## Checkpoint mới nhất — generation 3

**Newest output override (22:50):** 5 LOOK/s max; `tilt=min(15°, old_tilt×10)`,
az/twist/signs unchanged; deadband**1° on scaled direction**, not XY1/0.1.
Bounded owner-approved robot CLEAR (5s cooldown,max3 consecutive,OK CLEAR), not
geometry/USB/REPL errors; no HOME/reset/firmware limits changes. Same shared-source
selection. Sender active, measured229/229 LOOK echoes, actual tilt0.144..15°,
TXmin202ms; sample had no live CLEAR. Read `DELTA_OUTPUT_SCALE_2026-10-14.md`.
Older rate/scale/no-clear statements below are historical superseded policies.

**Latest owner-approved test override:** host sender configured
`observe-only-owner-test`, sends LOOK despite node FAULT/offline/unhomed reports;
does not modify firmware gates or clear/home/reset. Default gated config retained.
PID11947 active, snapshot632/632 LOOK echoed; raw completed snapshot255/255.
USB/REPL/bad framing/wrong echo still quarantine. Autostart enabled, 15Hz target,
two-eye XY mean/single-eye/valid face, head still sign-gated. Prior latched state
below is historical; see latest section in `DELTA_CONTINUOUS_2026-10-14.md`.

> **Continuous deployment supersedes trial-only state below (2026-10-14):**
> owner approved XY 50/50 both-eye mean, remaining-eye mode, head/face fallback,
> continuous 15 Hz target scheduling and boot autostart. Separate
> `track-eye-delta.service` enabled/running, `/home/pi5/track-eye-delta/`.
> No neutral intermediate: slow first live target 3000 ms; latest-only afterwards.
> Head is still runtime-sign-gated/inactive, face live. Read
> `DELTA_CONTINUOUS_2026-10-14.md`. Actual sampled TX ~14.3 Hz when sending;
> 1215/1215 raw verified LOOK, 877 recomputed true binocular means. Production
> camera/calibration/fallback unchanged; external adapter now emits hardware data.
> No post-install reboot acceptance or 24/7/direction claim. Faults latch/disarm,
> no auto-clear/home/REPL recovery. The prior trials are historical evidence.

**Final live state:** sender enabled/active but **FAULT_LATCHED**, no serial TX.
Final session251/251 LOOK echoed then n4 OFFLINE. Owner approved manual resume
only after clean validation; new validation instead observed n6 POWER_ON BOOT
and partial FAULT, no commands/snapshots. Latch kept; not continuous tracking now.

- Owner đã thay local `firmware/` bằng master3/proto3/spm_ik; cả ba khớp source
  đọc từ board. **6 node /2 Delta**, không dùng v1 ACK/queue/status semantics.
- Contract/review: `DELTA_V3_USB_CONTRACT_2026-10-14.md`; live outcome:
  `DELTA_V3_VALIDATION_2026-10-14.md`.
- Owner báo master↔node đã chốt, chọn **display-left → cả hai Delta** cho shared
  trial; giữ hai perception slots riêng, không average hay suy routing anatomical.
- `look` chỉ có một common orientation, không hai targets độc lập; không có OK MOVE.
- Có initial attach/open **UnicodeError→REPL**. Được duyệt recovery RAM với
  auto-home/rehome/restored-target replay tắt; **flash không sửa**, reset mất policy.
- Sau recovery: **3000/3000 synthetic IK +18/18 camera IK** verified, raw replay.
- Đã duyệt/gửi **1 neutral LOOK 3000 ms +2 camera LOOK 500 ms**. Echo 3/3;
  neutral có fresh post-duration IDLE positions gần 15°. Owner thấy cả hai Delta
  có chạy, chưa xác nhận hướng đúng. Camera trial dừng vì eye trở thành unusable
  sau IK, không đủ budget 20 s. Không auto-retry hoặc gửi STOP/neutral khi fail.
- Last post-trial check đủ 6 node IDLE/online/homed/error-free. Tất cả là timed
  evidence; đọc mới trước hardware. Không có serial sender chạy nền.
- Current Pi calibration hash `47cfed0fc3641f816aa9ac5c7ac0f72d11a3ed84e3e47bc06cff658b87884983`,
  gains 3/3/2.5/3.75, soft_limit=1.5, neutrals=[]; giữ current Pi-owned state.
- Tests mới **83/83 Pi**, **74 pass +9 skip Windows**, production **47/47**.
  Lifecycle reader/physical reconnect/unattended watchdog và direction vẫn mở.

Các mục từ kiến trúc/contract/checkpoint 2026-10-08 phía dưới là **baseline lịch sử
v1**, không là current robot generation. Đọc v3 contract/outcome trước chúng.

## Đọc để tiếp tục

1. `HANDOFF_CURRENT.md`: quyết định, checkpoint, những gì chưa được phép suy ra.
2. `PI5_MASTER_DATA_CONTRACT.md`: wire format, semantics, parser và ACK levels.
3. `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`: evidence, failed attempts, final results.
4. `PI5_DELTA_INTEGRATION_PLAN.md`: phase còn mở; không coi đoạn lịch sử là live state.

Đối với current firmware, thêm `DELTA_V3_USB_CONTRACT_2026-10-14.md` và
`DELTA_V3_VALIDATION_2026-10-14.md` ngay sau `HANDOFF_CURRENT.md`; v1 documents
không là reference live. `PI5_REVALIDATION_2026-10-14.md` giữ initial observation.

Các báo cáo validation trước là lịch sử có timestamp. `LOCAL_LEGACY_CONTEXT_2026-10-08.md`
giữ bản đồ tree local trước SSH; không dùng nó làm runtime canonical.

## Mục tiêu và kiến trúc thực tế

Per-eye pupil mirroring: đo chuyển động iris tương đối trong hốc mắt, không phải
screen/world gaze. Bản Pi còn có head/face/body candidates ở **shadow**, không
phát fallback hoặc điều khiển phần cứng.

```text
Pi production /home/pi5/track-eye
  camera → mirror → track_eye.tracker → OutputTuner → calibrated output
  ├→ renderer/web :8080
  └→ prototype độc lập đọc HTTP status, chọn display-left theo owner
      → normalize / active soft_limit → trial mapping sang az/tilt
      → USB-UART ASCII → ESP32 Delta master → IK
      → [MOVE chưa kiểm chứng live] ESP-NOW → 3 node → một mắt Delta
```

- Production service: `track-eye`, entry `python -u -m track_eye.app`.
- Pi deployment không là Git checkout; repo local này thiếu `track_eye/` hiện hành.
  Không overwrite Pi bằng `tools/pupil_spike.py` local cũ.
- `firmware/` do tác giả khác làm: ESP32 master + 3-RRR IK, không phải 4-servo follower.
- Legacy UDP `servo_link.py`/`EYES,...` không là đường output đích của nhiệm vụ này.
- Prototype source local: `delta_bridge/`, `tools/delta_*.py`, `tests/test_delta*.py`,
  `config/delta-*.json`; chỉ sync trong audit directory, chưa nối vào production.
- Pi audit: `/home/pi5/track-eye-integration-audit-20261008/`.

## Contract đã đối chiếu

USB thực là CH340 `1a86:7523` → UART, không mặc định native CDC. Text input:

```text
look az_deg tilt_deg twist_deg duration_ms\n
ik az_deg tilt_deg twist_deg\n     # chỉ tính, không MOVE
```

Host raw 115200 8N1, ASCII command/dấu chấm/newline; RX diagnostics UTF-8.
Master không nhận raw XY/JSON/legacy EYES/canonical binary EyeTargetFrame trực tiếp.
Hai protocol 20-byte tracking và ESP-NOW không tương đương nhau.

Owner chọn **display-left = output_left / eye_33_133**, không anatomical-left và
không average. Trial config 2°, x_sign=+1, y_sign=-1, az_offset=0, twist=0 được duyệt
cho probe; chưa physical direction calibration. Rig-specific settings ở config,
không biến trial/test fixtures thành defaults.

## Checkpoint đã đo và tạm chốt

- Camera-derived IK: **36/36** echo + reference match.
- Final steady-state IK corpus: **3000/3000**, ~301 s, nhịp mục tiêu 10 Hz.
- FD close/open: **5 sessions, 50/50**; không rút cáp/reset.
- Raw byte replay xác nhận cùng kết quả, không outstanding query/frame partial cuối.
- Reference numeric bound 0.001° cho soak, vì output `.3f` và khác biệt số học;
  **không phải motor accuracy**. Exact echoed polar vẫn phải khớp wire.
- Scaffold suite cuối **59/59 Pi**, **50 pass + 9 skip Windows**; Pi production
  suite **47/47**. Tests chỉ evidence phần mềm, không thay rig gates.

**Được chốt:** matching format/units + bounded established-session transmission.
**Chưa chốt:** physical reconnect/boot/reset/24-7 reliability, live look→ACK,
actual mechanical movement/direction, unattended fail-safe.

Đã thấy USB losses và UnicodeError vào REPL ở các lần attach/open; root cause
chưa chốt. Một soak fail do float-reference threshold và một fail do validator
partial-diagnostic handling đã được phân tích/regression; giữ artifacts thất bại.

## Bảo toàn và bước kế

- Giữ một camera owner; health 200 chỉ capture freshness, không pupil accuracy.
- Không thay Pi calibration, fallback config, models, runtime/service khi sync context.
- Fallback `disabled-shadow-only`; không bật body/head/face emission vì USB pass.
- Neutral bench đã duyệt nhưng **bị chặn trước clear/look** do n1/n3 offline;
  last observed robot state là snapshot, phải đọc lại trước mọi chuyển động.
- Không auto-clear/home/recover hoặc reuse stale targets; reconnect phải disarm.
- Lấy source canonical Pi và `motor_node.py`/`pc/eye_movie.py` từ tác giả; không
  tự import toàn bộ snapshot/history vào runtime.
- Tiếp theo đề xuất: lifecycle/reader/framing/handshake audit riêng, giữ text
  compatibility; motor chain xử lý sau. `DELTA_FIRMWARE_INTERFACE_HANDOFF.md`
  là prompt/tài liệu trao đổi, không authorization spawn/flash.
