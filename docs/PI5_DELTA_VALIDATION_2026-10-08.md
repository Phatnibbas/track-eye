# Pi5 ↔ Delta master: validation 2026-10-08

## Kết luận

> **Mới nhất sau đổi dây/cổng:** USB đã enumerate lại, khôi phục master trong RAM
> thành công và đọc được status/cfg/IK. Mẫu 125 giây không transport exception,
> nhưng robot chưa ready: master FAULT, n1 offline, n2/n3 chưa home; có báo boot
> HARD_RESET của n2/n3. Xem `PI5_DELTA_REVALIDATION_NEW_CABLE_2026-10-08.md`.
> Các đoạn tiếp theo là snapshot/ledger lịch sử, không phải trạng thái mới nhất.

> **Cập nhật cuối phiên tiếp theo:** CH340 không còn enumerate, `/dev/ttyUSB0`
> và serial by-id không tồn tại. Người vận hành đã báo cắm lại/đổi dây, nhưng
> lần kiểm tra tiếp theo vẫn lỗi USB `-71`. Không kết luận board đã chạy hay vẫn
> ở REPL sau disconnect. Xem ledger dưới đây; nội dung ban đầu là snapshot lịch sử.

Pi/camera/tracking đang chạy; USB enumerate đúng master ESP32. **Giao thức master
chưa pass:** probe `status` làm firmware thoát với `UnicodeError` ở stdin reader,
board hiện ở REPL tại lần quan sát cuối. Không có lệnh home/look/move/clear/reset
hoặc flash nào được gửi. Không kết luận nguyên nhân hoặc gọi end-to-end thành công.

## Quan sát trực tiếp

- SSH `pi5@pi5.local`, IPv4 lúc kiểm tra `192.168.1.211`.
- Debian/Linux aarch64, kernel `6.18.34+rpt-rpi-2712`.
- Runtime `/home/pi5/track-eye`, không phải Git checkout; khác đáng kể repo local.
- Service `track-eye` active/enabled, PID 1912, entry `python -u -m track_eye.app`.
- Một production process giữ camera; không mở camera thứ hai hoặc restart service.
- Camera UGREEN `0c45:2283`, by-id
  `/dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0`.
- V4L2 xác nhận MJPG 1280×720, 30 fps capture. App status mẫu khoảng 16 fps;
  không được đồng nhất capture fps với processing fps.
- `/healthz` HTTP 200; capture fresh. Đây không phải bằng chứng pupil accuracy.
- Không có face trong mẫu dry-run 10 giây; chưa kiểm tra hướng nhìn người thật.
- Nhiệt độ tại một lần đọc 46.6°C; `throttled=0x0`.
- USB CH340 `1a86:7523`, by-id
  `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` → `/dev/ttyUSB0`.
- User pi5 thuộc `dialout`; trước probe không thấy process giữ serial.
- ESP32: MicroPython v1.29.0, Generic ESP32 module, build 2026-08-24.
- Board có `boot.py`, `main.py`, `delta_proto.py`, `spm_ik.py`, `neutral.txt`.
- `main.py` từ board khớp byte-for-byte local, SHA256
  `574028a015dc73ae87946b7913db759e0aa264d36b833d87cf67af5af6190055`.
- `delta_proto.py` từ board khớp byte-for-byte local, SHA256
  `a0bd545f81f40df666e36614b13305dd6380a1644c3da9c2a7a70a984b929814`.
- Chưa có bản đọc hoàn chỉnh được xác minh cho spm_ik/neutral từ board.

## Serial failure và tác động

Probe dùng Linux termios raw 115200 8N1, exclusive-open, không chủ động toggle
DTR/RTS và không gửi control characters. Sau 3 s nghe, gửi ASCII `status\n`:

```text
File "main.py", line 683, in <module>
File "main.py", line 671, in main
File "main.py", line 646, in read
UnicodeError:
MicroPython v1.29.0 ...
>>> us
NameError: name 'us' isn't defined
```

Probe phiên bản đầu còn gửi `cfg` và `ik 0 0 0` vào REPL, nhận NameError/SyntaxError;
không có chuyển động. Tool đã được sửa để abort protocol probe sau traceback/REPL.

Readback REPL đầu tiên cố base64 toàn bộ file và gặp MemoryError 40990 bytes;
đã chuyển sang stream chunk 192 bytes. Không thay đổi file board.

Chưa biết byte lỗi đến từ cấu hình/baud tại thời điểm chuyển tiếp, stale RX,
UART interference, cách MicroPython xử lý stdin hoặc vấn đề khác. Việc REPL đọc
được command dài sau đó chứng minh truyền text tại 115200 khả thi, không chứng minh
master reader ổn. `stty` sau probe là 9600 vì tool khôi phục cấu hình ban đầu.
Host không cố ý reset nhưng mở/đóng UART vẫn cần đo tác động modem-lines trên rig.

Master đã rơi REPL: vòng ping/supervision không còn chạy. Node timeout là hành vi
được tài liệu mô tả, chưa trực tiếp đo trạng thái node hoặc độ an toàn cơ khí.

## Runtime mới cần bảo toàn

- `track_eye.app` dùng raw tracker → OutputTuner → calibrated output.
- Head/face/body observations và selector chỉ shadow; không truyền ra hardware.
- Body selection false, head_sign_validated false, calibrated false.
- Codec 20-byte được implement nhưng master Delta chỉ nhận text `look`; không
  gửi trực tiếp codec binary vào stdin master.
- Giữ per-eye display slots; chưa chọn slot thực tế cho mắt Delta một cơ cấu.
- Output calibration SHA256 trước/sau:
  `8782caf8391b6dd3e9f8321d09b818f537293bb7d571e95ed5a75b045ebb4a2f`.

## Test và artifacts

- Production tests trên Pi: 47/47 pass, không mở camera riêng.
- Scaffold tests: 8/8 local và Pi; mapping/invalid/stale/baseline/status/FAULT/REPL.
- HTTP dry-run: 100 samples/10 s, 0 errors, 0 proposed commands, serial TX false.
- Scaffold chỉ deploy ở thư mục audit, không sửa production package/service.
- Audit Pi: `/home/pi5/track-eye-integration-audit-20261008/` chứa snapshot source,
  probe transcripts, board readback và `dry-run-left.jsonl`.
- Snapshot source SHA256:
  `47384ee38782436e1d8ba4b186a43d8ac3e76a65d37d78083133ea9330ad81ae`.
- Snapshot local: `C:\Users\ninhh\AppData\Local\Temp\opencode\track-eye-deployed-20261008.tar.gz`.
- Không lưu mật khẩu vào repo/docs; file mật khẩu tạm đã xóa sau SSH calls.

## Chưa được validate

Ba node online/home/config, neutral đúng rig, IK và range trên board, dấu hướng,
slot mapping, motion, jitter/latency, watchdog khi Pi chết, USB reconnect,
power-cycle và vận hành lâu. Cần khôi phục master có giám sát trước khi thử tiếp.

## Ledger tiếp tục — không sửa flash

Baseline: text `status` đã làm master crash ở reader; chưa biết nguyên nhân.
Budget: thử nhỏ trên REPL/RAM, dừng ngay khi USB biến mất hoặc có lỗi chưa giải thích.
Rollback: file firmware không thay đổi; backup có checksum, thử RAM không persist.

| Iteration | Giả thuyết/thay đổi | Quan sát | Quyết định |
|---|---|---|---|
| 1 | Giữ 115200 giữa lần mở thay vì khôi phục 9600; ghi RX hex | Byte rác xuất hiện trước command mới, REPL có dòng dang dở | Cần làm sạch input; chưa quy lỗi cho LineReader |
| 2 | Ctrl-C trên REPL đã xác nhận, rồi thử text-reader RAM | `sys.stdin` là TextIOWrapper có `.buffer`; reader nhận đúng s,t,a,t,u,s,LF | Text reader không luôn lỗi; chưa có căn cứ patch firmware |
| 3 | Đọc file bằng chunk nhỏ và đủ thời gian | Đọc hoàn chỉnh 4 file; tất cả khớp local | Giữ backup |
| 4 | Gửi recovery `AUTO_REHOME=False; ...; main()` trong RAM | USB disconnect trong cửa sổ nhận, không giữ được đủ kết quả để xác minh thực thi | Không kết luận master đã phục hồi hoặc chính recovery gây mất USB |
| 5 | Kiểm tra sau người vận hành cắm lại/đổi dây | `lsusb` không có CH340, kernel enumerate lỗi -71 | Dừng serial, yêu cầu kiểm tra vật lý |

Iteration 1–3 chứng minh truyền text khả thi trong các lần đó. Không đo waveform
UART/modem-lines và không thu được byte đầu vào tại phía ESP của lần crash đầu;
baud-transition/stale-input chỉ là giả thuyết, không phải root cause đã xác nhận.

Backup thêm:

- `spm_ik.py`: SHA256 `004a201260935a6693e7523292adb47369c257e2290a88a1bf156cdc6d52166d`.
- `neutral.txt`: SHA256 `4464af2e4e63e47e968c7dba70fc14d62a3157f6cf0a5f4ba4d2f81a9baaa763`.
- Artifact Pi `board-stable-backup.json`; bản giải mã local nằm trong approved
  temp `delta-board-backup-20261008/`.
- `text-reader-experiment.json`, `repl-clean-state.json` giữ log thử reader.
- Kernel tại 14:12:21 disconnect; sau đó cannot-enable, not-accepting-address,
  `error -71`; vẫn xuất hiện tại kiểm tra 15:07. Câu kernel “Maybe cable is bad?”
  là lead, không phải chẩn đoán được xác nhận.

## Phần mềm cuối phiên

- Bridge tests trên Pi: **31/31 pass**, gồm 3 end-to-end monitor tests bằng PTY,
  6 PTY transport tests, planner/config/framing/state tests.
- Windows: **22 pass, 9 skip Linux-specific**; không báo 31 pass trên Windows.
- Fake master test có >=100 status responses, không gửi lệnh motor; không thay
  cho hardware gate 100 exchanges trên ESP thật.
- Negative cases: REPL/traceback kể cả chưa newline, malformed UTF-8, partial
  multibyte Vietnamese, overflow, device removal, second-open, stale/duplicate
  frame, source restart, FAULT, unknown/duplicate node, no shadow promotion.
- Production tests chạy lại: **47/47 pass**. Cuối phiên capture healthy, khoảng
  14.91 fps tại một mẫu, không face, fallback `disabled-shadow-only`.
- Calibration hash vẫn như ban đầu; production package/service không bị sửa.
- Chưa có motion sender. Read-only transport từ chối mọi command ngoài allowlist.

## Điều kiện tiếp tục phần cứng

Không retry serial khi chưa có device. Kiểm tra master riêng với cáp dữ liệu đã
biết tốt trên máy khác; thử cổng USB khác của Pi và kiểm tra nguồn board. Chỉ
đổi một yếu tố mỗi lần, ghi có/không enumerate. Không tắt/mở hub chứa camera
hoặc flash firmware để xử lý lỗi enumerate. Sau khi CH340 ổn định, xác minh
trạng thái master từ đầu; không auto resume recovery/motion theo trạng thái cũ.
