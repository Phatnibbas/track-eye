# Checklist chốt riêng Pi5 → ESP32 master

Tier project. Không bao gồm readiness/homing/ESP-NOW/motor mechanics. Checklists
không cấp phép bypass robot gate hoặc gửi motion khi FAULT.

## A. Format/semantics

- [x] PDF và actual master source có cùng text command `look az tilt twist ms`.
- [x] Pi serializer dùng numeric ASCII, space-delimited, decimal dot, newline.
- [x] Degree/millisecond và absolute-neutral orientation được mô tả.
- [x] Không nhầm JSON/raw XY/EYES/EyeTargetFrame với command master.
- [x] Source parser test nhận đúng field order/duration và tách IK/MOVE.
- [x] Camera display-left→IK đã có 36 matching live responses.
- [ ] Physical direction/neutral tương ứng normalized target: thuộc rig gate,
      không là điều kiện parser agreement; không ký nhận camera-to-motion đúng.

Có thể chốt **semantic compatibility trong workload kiểm chứng** nếu artifacts
khớp; không cần chờ node homing để xác nhận decoder hiểu command.

## B. Steady-state transport

- [x] Hoàn thành declared corpus trong một session, không missing/duplicate/
      wrong echo/malformed UTF-8/merged IK/timeout/disconnect.
- [x] RX parser chịu fragmented/coalesced lines và async UTF-8 diagnostics;
      vẫn bounded/deadline, không repair frame bị hỏng.
- [x] Ghi median/p95/max response host timing và observed cadence, không gọi motor latency.
- [x] Giữ camera/web runtime active và ghi before/after health/config hash.
- [x] Lưu code/campaign/source checksums, raw artifact + derived report.

Một mẫu 5 phút ở 10 Hz pass chỉ cho phép ghi “pass steady-state sample này”, không
cho phép ghi “24/7 ổn định” hoặc khẳng định loss probability/SLA production.

## C. Session lifecycle, phải đánh giá riêng

- [x] Reopen fd 5 session, typed query/echo proof mỗi session, không restore baud cũ.
- [ ] Fresh attach sau cắm cáp khi master boot sớm hơn Pi: chưa test có kiểm soát.
- [ ] Pi process crash/restart và stale buffered target: chỉ software logic đã test.
- [ ] Pi reboot/power-cycle + ESP reboot: chưa test host identity/version/ready handshake.
- [ ] Invalid/control-byte/oversize injection trên bench master riêng: chưa test live,
      actual source test cho thấy reader không robust.
- [ ] Root cause các UnicodeError/USB losses cũ được giải thích hoặc mitigation đã
      đo hiệu quả, không chỉ khôi phục RAM sau mỗi lần lỗi.

Reopen pass không đóng các item fresh physical attach/reset. Lỗi node reset
không đương nhiên là lỗi protocol USB; nếu node diagnostics làm control replies
bị merge thì đó là interface robustness issue dù nguyên nhân node ở downstream.

## D. Kiến nghị milestone

1. **Chốt wire contract và prototype adapter trước**, giữ text tương thích master.
2. **Chốt bounded steady-state evidence riêng**, nếu đạt corpus; không viện robot
   fault để bỏ qua malformed/timeout của interface.
3. **Chưa chốt production-ready USB lifecycle** cho tới reader/handshake/attach
   gates được kiểm chứng với tác giả firmware.
4. **Tạm để motor integration sau**; khi ready mới xác minh full look→ACK→reported
   positions→observed motion. Không dùng IK để chứng minh forwarding live.

Khuyến nghị cơ chế mới phải ghi tier rõ: typed transport worker/status state ở
project Pi; byte-reader/version/request ID/watchdog ở firmware bên tác giả. Không
thêm JSON/binary encoder trên Pi mà không có matching decoder trên master.

## Kết quả đã đo

2026-10-08: 3000/3000 IK ở 10 Hz trong ~301 s; 5 fd-reopen sessions tổng 50/50;
raw byte replay cùng kết quả, không pending/dang dở frame cuối. Chi tiết/tolerance
và rejected attempts: `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`. Initial merged
FAULT/STAT vẫn tồn tại, không được repair; corpus chỉ chạy sau valid snapshot.
