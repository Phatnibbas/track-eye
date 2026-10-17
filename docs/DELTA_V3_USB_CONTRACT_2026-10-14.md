# Delta v3 — hợp đồng Pi5 ↔ master đã đọc

Tier **project**, cập nhật 2026-10-14. Firmware do tác giả robot quản lý; không
flash/đổi protocol trong review này. Owner báo master↔node đã chốt hoạt động;
đó là owner acceptance, không phải phép đo độc lập ở lần audit Pi↔master.

## Identity và state

Đã đọc file trên board sau observed reader crash và đối chiếu byte-for-byte:

| File | SHA256 |
|---|---|
| main.py (36464 bytes) | `2b0525c078ad2f2134ed3f80ddf8a15d77c2894361a381eaf2990a7ae3821a9c` |
| proto3.py | `8e8db1cf0c623b0f052441fa445dca27555820810b0faf65a45c52f33dc9172d` |
| spm_ik.py | `004a201260935a6693e7523292adb47369c257e2290a88a1bf156cdc6d52166d` |

Board-owned `neutral3.txt`: mắt 1 `(15,15,15)`, mắt 2 `(15,15,15)`;
`eyes.txt`: `12`. Không tự chọn neutral từ phép đo camera hoặc neutral fixture.
Source matched không đủ suy RAM runtime luôn đúng flash: policy recovery dưới.

## USB commands và meanings

USB là CH340 USB-UART, host 115200 8N1 raw, TX ASCII dấu chấm/newline,
RX UTF-8 diagnostics. Không là ESP-NOW binary, JSON hay tracking EyeTargetFrame.

```text
ik az_deg tilt_deg twist_deg\n
look az_deg tilt_deg twist_deg duration_ms\n
status\n
cfg\n
```

- `ik` và `look` dùng cùng parser góc, cùng `look_targets()`.
- `ik` tính orientation và giới hạn, in sáu motor khi eyes=12; không send_move.
- `look` parse thêm integer milliseconds và gọi `send_move` cho active mask.
- Angles là absolute orientation so với robot-neutral; không x/y camera hoặc delta.
- `ms` là requested duration, có thể bị kéo dài tới minimum; zero/negative khác
  chế độ và host sender không được dựa vào firmware clamp thay range gate.
- Source nhận optional fields và extra tokens, không strict finite/argc validation.
  Host phải serialize typed đủ fields, reject NaN/Inf/control bytes.

### Một hướng chung, không hai target độc lập

`look az tilt ...` tác động **mọi mắt đang bật** theo cùng base orientation.
Từng mắt cộng vergence và `EYE_CFG.az_offset`, dùng neutral và signs riêng:

```text
eye_gaze(eye,az,tilt) → spm_ik.ik → neutral3[eye] + MOTOR_SIGN * delta theta
```

Topology từ `proto3.EYES`: eye1→n1,n2,n3; eye2→n4,n5,n6. EYE_CFG side L/R là
robot physical labels, không phải display-left/right của camera.

**Không có USB command mang hai `(az,tilt,twist)` độc lập trong source này.**
Không average hai mắt, không mặc định left→eye1, không đổi `eyes 1/2` mỗi frame:
`eyes` ghi flash state, stop mắt vừa tắt, clear fault state và có thể bật auto-home.
Display-left trial mapping cũ chỉ được dùng cho calculation probe; nếu gửi LOOK
với eyes=12, cả hai Delta sẽ nhận base orientation display-left. Cần owner chọn
  shared-target mode rõ ràng hoặc author thêm command 2 targets để giữ độc lập.

Owner đã chọn shared **display-left → cả hai Delta** cho bounded live trial
ngày 14/10. Trial dùng 1 approved neutral +2 camera LOOK; xem validation report.
Không áp dụng shared routing này làm default general binocular contract.

## USB response và v3 status

```text
IK az=90.0 tilt=2.0 twist=0.0 -> n1=... n2=... n3=... n4=... n5=... n6=...
STAT fault=False eyes=1+2 verg=0.00
STAT n1 ON IDLE err=NONE homed=1 sw=1 pos=... target=...
... active nodes only
ENC ...
PWR ...
```

Host phải xác minh active eyes/vergence và exact unique node set; legacy
`queue=0 inflight=-` gate không dùng được. Diagnostics có thể chen giữa replies;
USB chunks không phải line boundaries. Phải buffer UTF-8 tới newline và bound.

### Không có ACK MOVE như v1

V3 MOVE latest-wins/broadcast repeated, không v1 node ACK queue hoặc USB `OK MOVE`.
IK được in **trước** parsing ms và readiness gate. IK đúng vẫn có thể theo sau
bởi `ERR move`; không dùng nó để xác nhận movement acceptance/completion.

`send_move()` đặt **n.target và n.pos vào đích ngay trên master**, trước khi phát
MOVE. STATUS query cập nhật pos từ node, nhưng target chỉ cập nhật một số event.
Do đó snapshot tức thì sau command không độc lập chứng minh motor tới đích.
Không chờ/đếm `OK MOVE` mà bản này không in, không tuyên bố ACK chain từ IK.

ESP-NOW nội bộ: magic D7/version3, payload `<Hiiiiii` (uint16 ms + 6 signed
millidegrees), 26-byte payload + 6-byte header. Không gửi gói này vào USB parser.
15 MOVE/s cap là firmware limiter; host probe 10 IK/s không đo motor FPS.

## Lifecycle issue thực quan sát

Initial probe 20:48 đọc bytes không hợp lệ rồi traceback:
`main.py:826 sys.stdin.read(1)` → UnicodeError → MicroPython REPL.
Probe **không gửi bất kỳ status/cfg/ik** vì nghe trước và quarantine.
Kernel trước đó có disconnect/cắm lại; không kết luận cáp/EMI/baud/modem-lines là
root cause. Tty mới enumerate default 9600/canonical/echo là evidence, không
causal proof. LineReader hiện không bounded và không catch UnicodeError.

Owner duyệt RAM recovery, không flash và không home. Nạp chuỗi source và import
lại source đều MemoryError; chỉ khi xác minh globals Master/main/P/K còn loaded
mới gọi main cũ, với **AUTO_HOME_AT_START=false, AUTO_REHOME=false,
Master.resend_last_move=no-op**. Log startup/policy lưu đầy đủ.

Flash vẫn AUTO_HOME_AT_START/REHOME=true. RAM policy chỉ có hiệu lực cho phiên đó;
reset sẽ quay lại policy flash. Không tự reset/restart/auto-clear để che lỗi.
Established-session soak sau recovery không chứng nhận fresh physical attach.

## Tầng triển khai hiện tại

- **Project/audit:** `delta_bridge/v3.py`, `tools/delta_v3_validate.py`,
  `config/delta-v3-validation-20261014.json`. Status/CFG/typed IK only.
- **Production Pi:** không thêm serial sender, camera owner/service giữ nguyên,
  fallback shadow-only. Current camera calibration chưa có saved neutrals.
- **Firmware:** không sửa file flash; bounded reader/version/request ID là proposal
  phối hợp tác giả, không authorization thực hiện.
- **Archive:** proof/tests v1 20261008 không đại diện v3; không gọi legacy suite
  pass nếu source canonical đã được owner thay bằng generation3.

Before enabling camera-driven LOOK: decide shared/independent routing, verify
fresh complete ready state và current live limits, neutral/sign/camera mapping,
disarm on disconnect/fault/REPL, no stale replay, one serial owner. Transport
calculation tests không cấp phép gộp hai display slots hoặc bật fallback.
