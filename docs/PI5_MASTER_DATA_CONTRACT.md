# Pi5 ↔ ESP32 Delta master — hợp đồng dữ liệu thực tế

Tier: project. Tài liệu mô tả protocol đã tồn tại, không tự nâng nó thành protocol
production được chứng nhận. Căn cứ: PDF `firmware/Delta_EYE - Hướng dẫn bàn giao
hệ thống điều khiển.pdf` trang 6,8,14 và source `firmware/main.py` trên master đã
được đọc/đối chiếu byte-for-byte ngày 2026-10-08.

## 1. Kết luận về khả năng hiểu dữ liệu

Master **có parser text rõ ràng**, không chỉ nhận một blob bytes mơ hồ. Pi phải
chuyển output camera sang tọa độ cực đúng contract trước khi gửi. Parser không
biết `(x,y)` camera là gì và không tự biết tín hiệu đến từ mắt trái/phải nào.

```text
output_left (dimensionless calibrated display slot)
 → normalize / active soft_limit
 → explicit mapping / installation signs / angle scale
 → text command 'look az tilt twist ms\n'
 → master parses floats + milliseconds
 → IK → motor targets → ESP-NOW MOVE (khi readiness cho phép)
```

Đã có proof 36 camera-derived `ik` queries echo đúng góc và trả IK phù hợp source.
Đây là semantic/framing proof trong mẫu, không phải USB restart stability hoặc
motor delivery proof. Kết luận kiểm thử dài hơn nằm ở report audit riêng.

Audit bổ sung: **3000/3000 IK ở 10 Hz trong ~301 s**, và **50/50 qua 5 fd-reopen
sessions**, raw byte replay khớp. Không chốt physical cable reconnect/power-cycle
hoặc production long-run. Xem `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`.

## 2. Transport và framing

| Thuộc tính | Contract đã đối chiếu |
|---|---|
| Vật lý hiện tại | Pi USB host → CH340 USB-UART → ESP32 master stdin |
| Serial | 115200 baud, host raw 8N1, không software/hardware flow control |
| Host encoding | ASCII commands; decimal separator dấu chấm, không dấu phẩy locale |
| Frame | Một command trên một dòng, kết thúc LF (`\n`) |
| Firmware input | Chấp nhận CR hoặc LF; CRLF và empty lines được bỏ qua |
| TX output firmware | Dòng text UTF-8 (diagnostics có tiếng Việt), thường CRLF |
| Packet boundary | USB read/write chunk KHÔNG phải boundary command; parser phải buffer theo newline |
| Owner | Một process giữ port; không mở Thonny/probe/bridge cùng lúc |

Cáp Type-C không đồng nghĩa native USB CDC trên ESP. Device hiện thực đo được là
CH340 USB-UART. `delta_proto.py` binary little-endian là protocol **master→nodes**,
không phải Pi→master.

## 3. Wire command chuẩn của Pi sender

```text
look <az_deg> <tilt_deg> <twist_deg> <duration_ms>\n
```

Ví dụ đọc được bằng mắt người:

```text
look 90.000 2.000 0.000 500\n
```

Byte ASCII tương ứng:

```text
6c 6f 6f 6b 20 39 30 2e 30 30 30 20 32 2e 30 30 30 20
30 2e 30 30 30 20 35 30 30 0a
```

| Field | Ý nghĩa | Không phải |
|---|---|---|
| `look` | Lệnh hướng nhìn và yêu cầu di chuyển | JSON key / packet magic |
| `az` | Hướng nghiêng quanh CAD Z; 0° theo CAD +X | Pan motor hoặc x camera |
| `tilt` | Độ nghiêng hướng nhìn khỏi neutral Z | y camera hoặc tilt servo |
| `twist` | Xoay quanh chính trục nhìn | Head roll bắt buộc |
| `ms` | Thời gian chuyển động yêu cầu, số nguyên milliseconds | Timestamp hoặc sample ID |

Góc là **độ**, không radian. Đây là đích orientation tuyệt đối theo neutral robot,
không lệnh tăng/giảm tương đối. Chỉ một mắt Delta; không có hai eye slots trong
wire command này. Routing display-left được owner chọn ở Pi adapter.

Pi prototype luôn ghi đủ twist và ms. Firmware cho phép thiếu twist/ms nhưng
không nên dựa vào default khi integrating. Duration downstream uint16 0..65535;
sender motion yêu cầu >0 và trong bound, để tránh vô tình chọn fastest mode 0.
Master có thể kéo dài duration cho phù hợp khả năng motor; không bảo đảm đến đích
đúng ms host yêu cầu.

## 4. Mapping normalized XY → orientation

Với explicit config:

```text
x = clamp(output_left.x / active_soft_limit, -1,1)
y = clamp(output_left.y / active_soft_limit, -1,1)
rx = x_sign*x
ry = y_sign*y
az = degrees(atan2(ry,rx)) + az_offset  (wrap 0..360)
tilt = min(1, hypot(rx,ry))*max_tilt_deg
twist = configured twist
```

Trial được owner duyệt: x_sign=+1, y_sign=-1, az_offset=0, tilt scale 2°, twist=0.
Đó là ứng với display-right→CAD +X, display-up→CAD +Y, **chưa có observed physical
sign validation**. Không hardcode chúng thành defaults hoặc gọi chúng calibration.
Không gửi raw h/v, neutral/gain hay landmarks sang master hiện tại.

Các định dạng KHÔNG tương thích với master USB parser:

- `{"x":..., "y":...}` JSON;
- `EYES,Lpan,Ltilt,Rpan,Rtilt,gate` của legacy UDP servo;
- canonical binary EyeTargetFrame 20 bytes;
- packet `<BBBBH...` ESP-NOW;
- bốn tọa độ hai mắt hoặc chuỗi số thiếu command.

## 5. `ik` và `look`: điểm chung và khác

Master source `handle_line()` dùng cùng nhánh cho cả hai:

1. `split()` command theo whitespace.
2. `float(a[0]), float(a[1]), float(a[2])` → az/tilt/twist.
3. `look_targets()` → IK, neutral/MOTOR_SIGN và kiểm tra giới hạn từng node.
4. In `IK az=... tilt=... twist=... -> n1=... n2=... n3=...`.
5. **Chỉ `look`** mới parse integer ms và gọi `send_move()`.

`ik` chứng minh bộ góc được parse và tính; không làm motor chạy. Echo IK còn được
in **trước** readiness check `send_move`; vì vậy thấy IK không có nghĩa MOVE
được nhận/đã truyền xuống node. Ví dụ duration sai có thể in IK rồi `ERR`.

## 6. Các mức acknowledgement phải tách

| Phản hồi | Bằng chứng được phép kết luận |
|---|---|
| Serial write thành công | Host đã giao bytes cho driver, chưa biết board nhận |
| Echo `IK` khớp góc | Master parser/tính toán chấp nhận góc của command |
| `ERR look` / `ERR move` | Command bị từ chối; không coi IK trước đó là success |
| `OK MOVE` | Master đã hoàn tất ACK accounting cho MOVE; không phải motor tới đích |
| STAT node IDLE + pos/target gần đích | Node **báo** trạng thái/step position tới đích, không sensor proof |
| Quan sát/đo rig đúng hướng | Bằng chứng chuyển động cơ khí, vẫn cần label/timestamp |

ACK sequence của `delta_proto.py` chỉ master↔node. USB text **không có request ID**
gắn sample_id camera, không CRC/version/handshake. Không thể gắn `OK MOVE` với
mọi frame camera riêng biệt trong continuous streaming bằng protocol hiện tại.
Master còn cho phép latest MOVE thay inflight MOVE cũ; audit downstream coverage
phải đo riêng, không suy từ số OK đơn thuần.

Master forwarding theo source sau một `look` được readiness chấp nhận:

```text
degs * 1000 → signed integer millidegrees
payload = struct.pack('<Hiii', duration_ms, n1_mdeg, n2_mdeg, n3_mdeg)
ESP-NOW frame = struct.pack('<BBBBH', 0xD5, 1, CMD_MOVE, node_bitmask, seq) + payload
```

Payload 14 bytes + header 6 bytes cũng tổng 20 bytes, nhưng **hoàn toàn khác**
EyeTargetFrame 20 bytes network-order ở Pi package. Hai frame không dùng thay nhau.
AST test source chứng minh packing/order với dummy targets và readiness spy;
chưa quan sát MOVE bytes/ACK trên live node trong audit không chuyển động này.

## 7. Các rủi ro interface quan sát từ source và thiết bị

- `LineReader` đọc `sys.stdin.read(1)` text; UnicodeError không được bắt ở main
  loop và đã gặp trên board trong open/reconnect. **Root cause chưa chốt**.
- Buffer reader không có maximum line size; newline thiếu có thể tăng memory.
- Parser bỏ qua extra tokens, không strict argc; finite NaN/Inf validation không
  có rõ ở boundary. Host phải dùng typed serialization và reject nonfinite/injection.
- Master diagnostics chứa UTF-8 và có thể phát xen kẽ replies; đã thấy FAULT
  ghép với STAT/IK. Không sửa header bằng cách đoán rồi báo success.
- Không có ready banner versioned/capabilities request hay session nonce.
- USB reopen có thể có boot/stale RX/input; không auto resume target cũ.
- Sau USB enumerate mới, tty từng được quan sát default 9600/canonical/echo,
  trước khi host chuyển raw 115200. Khả năng baud/line-discipline transition làm
  nhiễu input là giả thuyết cần đo riêng, không phải nguyên nhân đã chứng minh.
- Node link watchdog bảo vệ mất master, không bảo vệ mất Pi trong khi master vẫn ping.
- File PDF ghi có PC sample `eye_movie.py` và node source, nhưng repo này thiếu;
  chưa review được reconnect/driver behavior bản đó.
- PDF ghi REHOME_MAX_TRIES=2 và TX_POWER_DBM=8.5; source local/board đã kiểm tra
  là rehome=10, không có TX_POWER_DBM. Không đồng nhất PDF với mọi deployed setting.

## 8. Đề xuất theo tier và scope

**Project/host adapter, nên làm trước:**

1. Giữ protocol text có sẵn; không gửi thêm binary/JSON mà master chưa implement.
2. Một worker/process giữ serial xuyên suốt session; RX parser UTF-8 bounded,
   typed TX ASCII/newline, no backlog, deadlines và log TX/RX.
3. Tách state `transport`, `protocol`, `robot_ready`, `motion_reported`;
   FAULT node không đồng nghĩa format mismatch và protocol pass không bật motion.
4. Restart/reconnect luôn về disarmed, invalidate old target, verify parser session.
5. Không retry motion đã bị superseded; rate cap và rig policy config explicit.

**Firmware phối hợp tác giả, cần approval/source revision riêng:**

1. Byte-oriented bounded command reader, CR/LF handling, reject invalid ASCII
   và oversized frame mà không rơi REPL; finite/range/argc checks.
2. Handshake/version + command ID echo + acceptance/rejection rõ; không đổi
   semantics lệnh cũ âm thầm. Node ACK khác master parse ACK.
3. Control replies luôn newline/framed; diagnostics tách loại/timestamp.
4. Host-freshness watchdog và safe state được rig-test; không dựa node ping timeout.
5. CRC/binary chỉ khi có evidence cần và cả hai bên implement; chuyển format
   không tự sửa USB power/cable/EMI/reader bugs.

Không thay board firmware trong audit này. Kết luận stability phải dựa artifact
soak/reopen, không ký nhận “ổn định” chỉ vì PDF nói giao diện đủ dùng.
