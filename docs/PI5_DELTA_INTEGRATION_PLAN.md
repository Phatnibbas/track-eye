# Plan chi tiết: Pi5 USB → ESP32 Delta master

Tier: **project**. Scope hiện tại là scaffold và validation, không bật production
emission, không flash firmware bên khác và không promote fallback shadow.
Evidence ban đầu: `PI5_DELTA_VALIDATION_2026-10-08.md`.

> **Milestone protocol mới nhất:** chốt matching text format/units + bounded
> live proof 3000/3000 IK và 50/50 qua 5 fd-reopen sessions. Không chốt physical
> reconnect/reset/lifecycle, live look forwarding hoặc motor movement. Tạm tách
> robot fault khỏi protocol assessment; xem `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`
> và `PI5_MASTER_DATA_CONTRACT.md`. Các số test/robot snapshot dưới là lịch sử.

> **Cập nhật mới nhất:** owner chọn display-left và trial IK 2°. Đã có 36/36
> camera-derived IK commands echo/target-match trên master. Owner duyệt neutral
> bench, nhưng fresh status có n1/n3 offline/homed=0 nên abort trước clear/look.
> Chưa phát host motor command hoặc chứng minh robot chuyển động đúng camera.
> Evidence: `PI5_CAMERA_TO_MASTER_2026-10-08.md`.

> **Hiện tại sau đổi dây/cổng:** USB enumerate; master phục hồi RAM-only và đáp
> ứng status/cfg/IK. Diagnostic 125 s thu 124 snapshot hoàn chỉnh, không transport
> exception. Robot gate vẫn BLOCKED: FAULT, n1 offline, n2/n3 chưa home và có
> báo HARD_RESET. Scaffold 32 test trên Pi pass. Không host motion TX/rollout.
> Evidence: `PI5_DELTA_REVALIDATION_NEW_CABLE_2026-10-08.md`.

## Kiến trúc đích

```text
Pi track_eye.app (camera owner duy nhất)
 → calibrated OutputTrackingResult, hai display slots
 → target boundary: normalize output / active_soft_limit
 → explicit slot-to-one-Delta routing
 → mapping normalized XY → az/tilt, twist=0
 → rate-limited latest-target serial worker
 → look az tilt twist ms\n, USB-UART 115200
 → ESP32 master IK → ESP-NOW → 3 node → một mắt Delta

Master text RX → bounded line parser → readiness/fault state → TX gate + logs
```

Adapter là compatibility backend cho firmware text có sẵn. Không thay accepted
logical normalized target contract bằng góc motor; chỉ phiên dịch ở ranh giới
backend. Codec binary 20-byte không tương thích parser hiện tại. Việc mapping
hướng robot nằm host là khác thiết kế ESP-owned mechanics trước đây và phải
được ghi nhận rõ khi chọn integration, không âm thầm đổi contract.

## Scaffold đã tạo

- `delta_bridge/core.py`: pure Mapping, đọc calibrated production status,
  fail-closed MasterState; rig signs/range/duration/node IDs/timings phải khai báo.
- `delta_bridge/config.py`: schema strict, reject duplicate/unknown/missing keys,
  booleans/nonfinite values; không có rig defaults và không chấp nhận mode emit.
- `delta_bridge/serial_transport.py`: Linux USB-UART read-only, UTF-8 bounded lines,
  exclusive open, partial writes, deadline và quarantine lỗi; không gửi motor commands.
- `delta_bridge/planner.py`: latest-only dry-run proposals, freshness server/local,
  rate-limit, discard khi fault/restart/stale; không có motion writer.
- `tools/delta_master_monitor.py`: read-only status monitor, bounded session,
  log RX hex/timestamps; dừng khi lỗi, không reconnect/retry loop.
- `tools/delta_bridge_dry_run.py`: HTTP observer, log đề xuất lệnh, không mở serial.
- `tools/delta_serial_probe.py`: status/cfg/ik probe, dừng nếu thấy REPL/traceback.
- `tools/delta_repl_inspect.py`: đọc allowlist firmware sau crash đã xác nhận;
  không dùng khi master đang chạy.
- `tests/test_delta*.py`: 31 test trên Pi hiện tại, Windows skip 9 PTY tests.

Mapping 5° và y-sign=-1 trong dry-run phiên đầu là **giả thuyết thử nghiệm**, không
phải mechanical calibration. Đã bỏ bound 12° và mọi mặc định phụ thuộc rig khỏi
code. `config/*.template.json` cố ý để null/empty: chưa đo/chưa chọn thì không chạy.
Slot `left` trong dry-run cũ không quyết định eye routing. Bounds [-1,1], uint16 ms,
schema và tên protocol command là hợp đồng kỹ thuật, không phải rig tuning.

## Phase 0 — xác định source và ownership

1. Giữ snapshot deploy và hash; không overwrite repo local cũ bằng bản Pi.
2. Tìm đúng Git source revision của `track_eye/` đang deploy; nếu không còn source,
   lập bản import có review từ snapshot, không nhập calibration/cache/log/model
   vô điều kiện. Chưa tích hợp thẳng vào `pupil_spike.py` legacy.
3. Lấy đầy đủ `motor_node.py`, `pc/eye_movie.py`, tests từ tác giả firmware.
4. Chốt một hay hai mắt Delta; chọn display slot cho mỗi master, không tự average.
5. Đọc AGENTS và framework của source mới trước khi thay đổi.

Exit: có source canonical, đầy đủ runtime/node dependencies và quyết định routing.

## Phase 1 — giải quyết serial reader blocker (ưu tiên cao nhất)

1. Người vận hành đứng cạnh rig, vùng chuyển động trống, có thể ngắt nguồn motor.
2. Backup/đọc đủ main/protocol/IK/neutral; đối chiếu SHA256 và firmware versions.
3. Với motor tách nguồn hoặc được tác giả xác nhận an toàn, cho phép restart master
   bằng thao tác có giám sát. Không auto Ctrl-D/reset trong bridge.
4. Configure 115200 raw trước command; kiểm tra USB ID, UART, DTR/RTS/HUPCL và
   thời điểm boot. Listen boot + idle, xác định master không phải REPL.
5. Gửi từng `status`, `cfg`, `ik 0 0 0`; dừng ngay nếu traceback, disconnect hoặc REPL.
6. Thu timestamp/raw byte hex lỗi, thử bounded idle/command cycles; không retry
   liên tục hoặc gửi protocol commands vào REPL.
7. Nếu tái hiện lỗi stdin, phối hợp tác giả sửa LineReader tối thiểu: byte-oriented
   bounded ASCII parser, bỏ byte không hợp lệ, CR/LF handling, line-length bound,
   nonblocking reads; không đổi safety logic để tránh crash.
8. Mỗi thay đổi firmware phải có backup/hash, approval và rollback; không sửa chỉ
   vì một probe lỗi khi nguyên nhân host chưa được loại trừ.

Exit đề xuất: >=100 status exchanges + 10 phút idle, không UnicodeError/reset/REPL;
đây là bench gate đề xuất, không chứng minh vận hành dài ngày.

## Phase 2 — readiness, workspace và safety chỉ đọc

1. Đọc status đầy đủ: master không FAULT; ba node online, không ERROR/HOMING.
2. Đọc cfg từng node: min/max/maxhz/accel/homedir; không dùng fallback config làm
   giới hạn rig đã xác minh.
3. Xác minh neutral đúng rig và state homed. Nếu chưa home, dừng và xin phép homing
   có giám sát; bridge không tự home/clear/calib.
4. `ik` các hướng nhỏ và `range`; đọc đầy đủ phản hồi. Range tính toán chưa xét collision.
5. Xác minh mất host có safety riêng: master hiện ping node liên tục kể cả mất Pi,
   vì vậy node link watchdog **không thay thế host freshness watchdog**.
6. Chọn chính sách khi mất tracking/HTTP/USB: stop, bounded return-neutral hay
   giữ có timeout. Không phát repeated neutral/clear khi FAULT.

Exit: ready evidence, workspace envelope, host-loss policy và stop semantics được chốt.

## Phase 3 — implement/test transport độc lập

Modules tiếp theo: `serial_transport.py`, `controller.py`, `config.py` và fake master.

- Một process giữ serial; stable by-id nhưng CH340 không có unique serial phải
  pin by-path/explicit identity nếu có nhiều board giống nhau; không chọn port đầu tiên.
- Open không toggle reset lines chủ động; verify state sau reconnect, không auto resume.
- RX worker bounded bytes/line/queue; xử lý split/coalesced lines, UTF8 lỗi, CR/LF,
  unknown diagnostics, disconnect và boot transcript.
- Latest target queue depth 1; 10 Hz initial cap, tuyệt đối không quá 15 Hz.
- Mỗi command ghi ms rõ ràng; không resend superseded motion, không đồng nhất
  `OK MOVE` với completion.
- Fail-closed khi FAULT/ERR/REPL/offline/unhomed/stale; cần full status fresh.
- Throttle status polling và lưu full snapshots; readiness parser hiện tại chỉ scaffold,
  cần xử lý master queue/inflight khi streaming và polling timing thực tế.
- Watchdog cục bộ bằng monotonic time, timeout write/read, no blocking tracker.
- Log commands/replies/transitions và timestamps, không log image/credentials mặc định.
- Default dry-run; chưa cung cấp production emit flag trước safety approval.

Tests: partial/malformed/duplicate/out-of-order status, boot/reconnect, no ACK,
device removal, write partial, line overflow, stale HTTP, repeated sequences,
frame counter restart, queue overwrite, rate-limit, startup and shutdown failure.
Test thật với PTY fake master trên Linux trước board. Không dùng loopback làm bằng
chứng master parsing hoặc actuator safety.

## Phase 4 — live target shadow

1. Dùng service hiện có và HTTP status để tránh camera owner thứ hai.
2. Người đứng trước camera: neutral, eyes-only trái/phải/lên/xuống, head-only,
   blink, mất mặt. Log cả hai output slots và lệnh đề xuất, không thu ảnh mặc định.
3. Kiểm tra output normalization bằng soft_limit live, baseline state và freshness.
4. Không lấy shadow head/face decision làm production target lúc gate chưa pass.
5. Đo negative no-face, nonfinite, frame freeze và HTTP failure → không proposal.

Exit: mapping đúng với intent software, không stale/invalid proposal; rig sign còn pending.

## Phase 5 — supervised motion bench

Chỉ sau approval chuyển động, source mapping và safety policy:

1. Home/calib theo tác giả nếu cần; chuẩn bị stop/ngắt nguồn.
2. Gửi neutral rồi 1–2° từng hướng, từng command chậm; xác nhận CAD orientation.
3. Sửa az_offset/sign trong config, không đảo tracking raw.
4. Tăng dần biên dưới range và collision envelope; không clamp riêng chân robot.
5. Kiểm tra stop effect, Pi bridge termination, kill tracker, rút USB, master reset,
   node reboot/offline, nguồn motor và system recovery. Không tự auto-clear.
6. Đo timing host TX/master response/status motion: response không đại diện cho
   thời gian cơ khí; cần quan sát rig để đo physical latency.
7. Soak 10 phút → 30 phút, log reset/FAULT/loss/jitter. PDF báo reset/bộ nhớ ở node
   chưa ổn định; không che lỗi bằng repeated rehome.

Exit: direction, limits, host-loss, faults, disconnect và soak pass trên rig thật.

## Phase 6 — production integration và rollback

1. Sau khi canonical source được xác định, chọn in-process submit-to-worker hay
   sidecar đọc HTTP. Sidecar thuận lợi prototype; in-process có freshness tốt hơn.
2. Thêm transport status riêng: mode, device, ready reason, target age, last TX/RX,
   rate/drop counts, FAULT và reconnect state; giữ semantics tracking/health nguyên.
3. Default disabled; explicit config bật một routed slot/backend.
4. Deploy chỉ file intended, backup service/source, giữ output calibration/benchmarks,
   compare hashes trước restart. Không đưa firmware tác giả vào deploy tự động.
5. Recheck one camera owner, health, status, calibration hash, latency và failure gates.
6. Fallback rollout là nhiệm vụ/gates riêng; không bật body/head/face vì serial đã pass.
7. Rollback disable bridge, khôi phục unit/source; dừng output theo safe-state đã chốt.

## Quyết định cần owner/tác giả

- Routing một mắt Delta dùng display-left hay display-right, hoặc cần hai master?
- Cho phép reset/recover master và supervised home/motion vào thời điểm nào?
- Có đầy đủ node source và PC sample mới nhất không?
- Safe state khi mất Pi/mất tracking là stop, neutral hay policy khác?
- Ai sở hữu mechanical mapping/config và có được sửa LineReader nếu tái hiện lỗi?

## Trạng thái hiện tại

Phase 0: đã snapshot, source reconciliation/routing pending.
Phase 1: sau đổi dây/cổng, master khôi phục RAM-only với auto-rehome tắt; đọc
status/cfg/IK và monitor 125 s không transport exception. Root cause crash trước
đó chưa chốt, chưa chứng minh boot/reconnect/long-run. Không sửa flash firmware.
Hardware BLOCKED ở readiness: n1 offline, n2/n3 chưa home, master FAULT sau báo
node reboot. Không auto-clear hoặc homing.
Scaffold: mapping + state + strict config + read-only transport/monitor + planner,
HTTP dry-run và PTY/negative tests đã có.
Phase 2–6: chưa pass. Không có effective serial motion hoặc production rollout.
