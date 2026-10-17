# Nội dung trao đổi với tác giả firmware — đề xuất, chưa thực thi

Có thể gửi phần dưới để thống nhất interface; không phải lệnh cho agent tự flash
board hoặc tự thay protocol.

---

Mình đang nối Pi5 tracking sang ESP32 master qua CH340 USB-UART. Đã đọc PDF bàn
giao ngày 07/10 và source main.py/delta_proto.py/spm_ik.py/neutral.txt trên board.
Pi sẽ gửi **text `look az tilt twist ms\n` ở 115200**, với góc độ, ms integer;
không gửi raw camera XY/JSON/payload binary vào parser text hiện có.

Đã kiểm chứng camera display-left bằng 36 IK commands thật: master echo đúng
polar và trả motor targets phù hợp source. Robot lỗi offline/reboot được tách
khỏi proof decode, chưa có host LOOK được gửi vì readiness gate không giữ được.
Soak/reopen kết quả mới nhất xem `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`.

Các observation cần phối hợp (chưa khẳng định root cause):

1. Có lần attach/open serial nhận byte rác, master `UnicodeError` ở
   `sys.stdin.read(1)` và rơi REPL. RAM recovery chạy được khi giữ 115200.
   Muốn kiểm tra transition từ host tty default (đã thấy 9600/echo) sang raw 115200,
   modem-lines và input reader; không mặc định toàn bộ do firmware hay do cáp.
2. Có RX `FAULT ...STAT ...` và `FAULT ...IK ...` ghép trong một dòng ở đầu session.
   Không có request ID, khó phân biệt stale partial diagnostic với reply mới.
3. Protocol current thiếu bounded line/strict argc/finite validation. Đã negative
   test actual AST reader/parser; không cố gửi bytes hỏng vào robot đang lắp.
4. `IK` in trước `send_move`; cần phân biệt parse acceptance, queued movement,
   node ACK, reported completion và physical completion.
5. Node timeout bảo vệ mất master, không bảo vệ Pi mất feed trong khi master ping.
6. PDF có TX_POWER_DBM=8.5/rehome_max=2 nhưng source master/protocol đã đọc khác;
   cần nhận bản canonical/latest thay vì patch trên snapshot không rõ revision.

Nhờ gửi đủ `pc/eye_movie.py`, `motor_node.py`, tests và release/revision đang dùng.
Đề xuất change firmware tối thiểu, backward-compatible và có gate riêng:

- bounded ASCII byte-reader không crash vì input invalid;
- command ACK có version/session/request ID và echo rõ content;
- newline/framing bảo đảm cho control replies, diagnostics tách type;
- finite/range/argc check và reject không dispatch;
- host freshness watchdog + rig-approved safe state, không auto-clear lỗi.

Không cần chuyển sang JSON/binary ngay. Nếu đổi format phải implement/parser
test cả hai đầu và có capability/version handshake. Các thay đổi nguồn/driver
node vẫn là công việc phần cứng riêng; chưa gọi motor chain ổn từ IK results.

---
