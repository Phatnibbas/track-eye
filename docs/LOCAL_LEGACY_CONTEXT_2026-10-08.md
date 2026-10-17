# Track Eye — snapshot context tree local cũ (lịch sử)

Ngày đối chiếu: 2026-10-08. Đây là tài liệu cấp **project**, mô tả hiện trạng;
không phải chỉ dẫn tự động cho agent, không thay đổi runtime hay cấu hình triển khai.

> **Cập nhật sau SSH:** nội dung dưới đây mô tả tree local cũ, KHÔNG phải runtime
> đang deploy trên Pi. Pi chạy `track_eye.app` với output calibration và fallback
> shadow, service `track-eye`. Xem `docs/PI5_DELTA_VALIDATION_2026-10-08.md` và
> `docs/PI5_DELTA_INTEGRATION_PLAN.md` trước khi kết nối phần cứng.

## 1. Mục tiêu và ranh giới

Mục tiêu được ghi trong README và tài liệu pivot: camera trong hộp xem phim đọc
chuyển động iris của **từng mắt**, để mắt cơ khí nhại chuyển động tương đối trong
hốc mắt. Không phải ước lượng điểm nhìn trên màn hình hay một vector gaze gộp cả đầu.

- Giữ hai tín hiệu mắt độc lập ở tầng perception.
- Không dùng calibration màn hình trong runtime hiện tại.
- Chuẩn hóa hình học 2D theo khoé mắt giảm ảnh hưởng dịch chuyển, scale, roll;
  **không chứng minh bất biến với mọi yaw/pitch, che khuất hoặc biến dạng mí**.
- Iris landmark là proxy cho vị trí pupil; không có thuật toán segment pupil riêng.
- Cơ khí Delta_EYE mới có calibration `neutral.txt`; điều này khác calibration gaze.

## 2. Hai hệ actuator hiện đang cùng tồn tại

### A. Pipeline đã được nối trong code Track Eye

```text
USB camera
  → tools/pupil_spike.py: mirror → BGR/RGB → MediaPipe FaceMesh 478
  → measure_eye() × 2: iris offset trong hệ khoé mắt
  → EyeSmoother × 2 (EMA alpha=0.45)
  ├→ overlay/down-gain hiển thị → FrameHub JPEG → HTTP MJPEG :8080
  └→ EyeMapper × 2 → UDP :8770 → ESP32-S3 → PWM 4 servo
```

Servo output chỉ bật khi có `--udp-host`. `run_pupil.sh` gốc không truyền tham số
này mặc định. Không có đường gọi từ runtime này tới `firmware/main.py`.

### B. Delta_EYE trong `firmware/`

```text
Ứng dụng host [chưa có trong repo này]
  → USB serial: look az tilt twist ms
  → ESP32 master: main.py + spm_ik.py + delta_proto.py
  → ESP-NOW broadcast, bitmask + sequence + ACK
  → 3 node ESP32-C3 [motor_node.py chưa có]
  → A4988 + Nema17, hộp số 14:1 → 1 mắt cầu song song 3-RRR
```

PDF bàn giao ngày 07/10/2026 mô tả hệ B. Không được coi 3 motor là ba servo
pan/tilt độc lập hoặc gửi packet `EYES` vào master này. Chưa có adapter nối
per-eye `(h,v)` sang `look`, và chưa rõ hệ B sẽ thay thế một hay cả hai mắt.

## 3. Vai trò file

| File | Vai trò thực tế |
|---|---|
| `tools/pupil_spike.py` | Entry point vision, camera, đo mắt, EMA, overlay, gửi servo và lifecycle |
| `constants.py` | Khoé/mí/contour/iris indices; orbital và calibration constants còn dư, không dùng trong runtime này |
| `filters.py` | Runtime chỉ import `clamp`; `EMAFilter` và dead-zone helper không nằm trong đường xử lý chính |
| `servo_link.py` | Mapping một mắt sang góc pan/tilt, output EMA, UDP sender |
| `web_ui_server.py` | JPEG latest-frame hub, HTTP page và MJPEG; **không có WebSocket server** |
| `tools/servo_link_test.py` | Sender tín hiệu giả sweep/poses; không cần camera |
| `tools/vertical_diag.py` | Đo các normalization trục dọc, độ tách UP/DOWN và drift pha HEADDOWN; chưa được runtime import |
| `hardware/esp32s3_eye_follow.py` | Firmware UDP/PWM gốc; WiFi timeout boot 20 s, không có reconnect loop |
| `hardware/esp32s3_eye_follow-ninhh.py` | Biến thể retry WiFi vô hạn, reconnect, heartbeat, reset khi exception |
| `hardware/esp32s3_servo_test.py` | Test trực tiếp servo, có thể đi 0–180°, không dùng giới hạn cơ khí follower |
| `hardware/esp32s3_eye_circle.py` | Test hai mắt chạy vòng tròn trong biên hẹp |
| `run_pupil.sh`, `pupil.service`, `install_autostart.sh` | Launcher và triển khai Pi gốc |
| Các bản `*-ninhh` | Biến thể riêng; tên file không tự khiến chúng được runtime chọn |
| `firmware/main.py` | Delta master: serial parser, trạng thái node, ACK/retry, safety, IK targets, rate limit |
| `firmware/delta_proto.py` | Protocol ESP-NOW binary little-endian, identity MAC, config/state/error enums |
| `firmware/spm_ik.py` | IK 3-RRR theo hình học CAD, orientation tilt-and-torsion, kiểm tra ràng buộc |
| `firmware/neutral.txt` | Ba góc node trung tính: `12.857 12.857 12.857`; chưa xác minh đúng rig đang dùng |
| `docs/PIPELINE.html` | Walkthrough perception, một số mục triển khai và scope servo đã cũ |
| `docs/PIVOT_PUPIL_MIRROR_2026-07-02.md` | Lý do đổi từ gaze estimation sang pupil mirroring; trạng thái session mang tính lịch sử |
| `archive/` | Nghiên cứu, thiết kế và code lịch sử; bị gitignore, không thuộc import graph chính |
| `tests/` | Hiện chỉ thấy bytecode cache, **không có source `test_*.py`** |

## 4. Hợp đồng dữ liệu và tham số

### Perception

Với từng mắt:

```text
center = (c0+c1)/2
u = normalize(c1-c0)
v_axis = (-u.y, u.x)
h = dot(iris_center-center, u) / (eye_width/2)
v = dot(iris_center-center, v_axis) / (eyelid_height/2)
```

`iris_center` là trung bình 4 điểm vòng iris. `(h,v)` không bị clamp tại phép đo,
có thể vượt [-1,1]. Dấu phụ thuộc hệ khoé mắt và mirror; tên LEFT/RIGHT trên UI
không thay cho kiểm chứng ánh xạ mắt người ↔ mắt cơ khí.

- `eye['v']`: EMA rồi down-gain 1.5× cho hiển thị.
- `eye['v_servo']`: EMA trước down-gain; mapper bù chiều xuống riêng.
- Gauge gain H/V = 3.0/2.5, không phải gain actuator.
- Mất face → gửi `neutral`; không reset state smoother/mapper khi reacquire.
- Không có gate kiểm tra blink, độ mở mắt hay confidence từng iris.
- Confidence gauge `0.9` là số cố định khi có mắt, không phải xác suất model đo.

### UDP/PWM

```text
EYES,<Lpan>,<Ltilt>,<Rpan>,<Rtilt>,<gate>\n
gate = tracking | hold | neutral
```

- Mapping: deadband H/V 0.03/0.04, exponent 0.75/0.70, output EMA 0.5.
- Pan: neutral 80°, clamp 40–140°, gain 67.5, sign +1.
- Tilt: neutral 60°, clamp 20–110°, gain up/down 67.5/135, sign -1.
- Pins: Lpan 11, Ltilt 12, Rpan 13, Rtilt 14.
- PWM 50 Hz, pulse 500–2500 µs; slew tối đa 3° mỗi loop, sleep 20 ms.
- Watchdog 900 ms không nhận packet hợp lệ → target neutral.
- `hold` giữ **target** cũ và refresh thời điểm nhận; không đóng băng góc hiện tại.
- Receiver rút hết queue, chọn packet hợp lệ cuối cùng; không ACK/telemetry.
- Pi và firmware đều clamp: đổi giới hạn phải đối chiếu cả hai phía.
- Servo cần nguồn riêng 5 V, chung GND ESP; không cấp cả 4 servo từ board.

### Delta_EYE

- `look az tilt [twist] [ms]`: góc độ, duration mili-giây.
- IK orientation: `Rz(az) * Ry(tilt) * Rz(twist-az)`.
- Góc node = neutral + motor_sign × wrap180(theta - theta_neutral).
- Đích `look` vượt hành trình một node → từ chối toàn bộ, không clamp riêng chân.
- Movement latest-slot tối đa 15 lệnh/s; PING 200 ms, node timeout 2000 ms,
  ACK timeout 200 ms, tối đa 5 lần gửi. ACK không phải xác nhận đã tới đích.
- WDT master đang tắt. Source đặt `REHOME_MAX_TRIES=10`, PDF ghi 2.
- IK dùng hướng trục gần đúng; CAD có lệch tâm, phép check toán học không kiểm tra va chạm.

## 5. Những lệch context cần nhớ trước khi sửa

1. **Các bản `-ninhh` chưa được wiring tự động.** `pupil_spike.py` import
   `servo_link.py`; service `-ninhh` vẫn gọi `run_pupil.sh`; installer `-ninhh`
   vẫn copy `pupil.service` gốc. Có thể là file để chép/đổi tên lúc deploy,
   nhưng chưa có bằng chứng quy trình đó hoặc trạng thái Pi hiện tại.
2. `README-ninhh.md` ghi zero-config broadcast và số đo bench; launcher gốc chỉ
   chạy perception. Số đo là thông tin tài liệu, không phải xác minh của lần đọc này.
3. HTML UI cố kết nối WS :8765 nhưng runtime không mở WS. Các ô status không có
   producer; MJPEG vẫn là đường quan sát thực tế.
4. MJPEG loop gửi cả frame cũ liên tục, không có pacing khi đã có JPEG hay đợi
   frame mới; có thể tiêu tốn CPU/băng thông theo client.
5. Chuẩn hóa dọc bằng độ mở mí dễ nhiễu lúc blink/nhìn xuống. Down-gain khuếch đại
   tín hiệu, không phục hồi thông tin bị mất. Diagnostic chưa có kết quả đo kèm repo.
6. Bộ Delta local thiếu `motor_node.py`, `pc/eye_movie.py`, test và CAD được PDF
   nhắc tới. `delta_proto.py` local cũng chưa có `TX_POWER_DBM=8.5` như PDF mô tả.
7. PDF báo node reset/lỗi bộ nhớ chưa chốt nguyên nhân; không coi chẩn đoán
   NeoPixel/nguồn/WiFi hoặc số đo mô phỏng là sự thật phần cứng đã được xác minh.
8. `firmware/`, các bản `-ninhh` và diagnostic đang untracked tại lần đối chiếu.
   Giữ nguyên chúng; chưa quyết định bản canonical hay dọn archive.

## 6. Khung phát triển hợp lý nếu tiếp tục

Đây là phân tầng đề xuất, **chưa được implement**:

```text
Capture → Per-eye measurement → Signal conditioning → Intent
                                                   ├→ UDP 4-servo backend
                                                   └→ Delta serial backend
                          ↘ Overlay / telemetry / logs
```

Tách perception khỏi cơ khí/transport; không đưa IK vào phép đo iris. Chốt số mắt
Delta và quy ước trục trước khi chọn mapping. Với Delta, adapter cần đọc trạng thái,
chặn gửi lúc FAULT/offline/chưa home, limit rate và vùng làm việc; không chỉ gửi
serial một chiều. Không tự clear/home liên tục để che lỗi phần cứng.

Ưu tiên: chọn rig và file canonical → lấy đủ source Delta nếu dùng → đo tín hiệu
vertical trên rig thật → adapter + unit tests/fake transport → bench → integration.

## 7. Phạm vi xác minh lần này

Đã đọc code Python hiện hành ở root/tools/hardware/firmware, README hai bản,
script/service hai bản, tài liệu pipeline/pivot và text 16 trang PDF bàn giao;
đối chiếu diff mapper hai bản và layout archive. Không đọc dependency/cache,
credential hay toàn bộ các báo cáo nghiên cứu lịch sử như source hiện hành.

Kiểm tra không cần thiết bị: parse AST 16 file Python thành công; mapper trả các
pose trong clamp; UDP loopback nhận đúng packet; 4 pose IK có residual ràng buộc
khoảng 1e-16. Đây không phải test suite đầy đủ hay xác nhận hardware chạy ổn.
Chưa chạy camera, kết nối Pi/ESP, flash board hoặc kiểm chứng power-cycle.
