# ESP32-S3 4-Servo Mechanical Tester

Folder này để upload trực tiếp qua Thonny lên ESP32-S3 nhằm test **min/max góc quay cơ khí trên board**, trước khi nối laptop gaze app qua UART USB.

## Cơ khí hiện tại

Tổng 4 servo 180:

```text
Horizontal axis: GPIO42, GPIO39
Vertical axis:   GPIO41, GPIO38
```

Mỗi con mắt có 2 servo, nhưng test này điều khiển theo axis:

```text
h1/h2 = 2 servo ngang
v1/v2 = 2 servo dọc
```

Logic duty theo code cũ đã chạy:

```text
horizontal duty = duty(180 - angle)
vertical duty   = duty(angle)
```

## Cảnh báo nguồn

- Không cấp 4 servo trực tiếp từ 5V/3V3 của ESP32-S3.
- Dùng nguồn 5V ngoài cho servo.
- Nối chung GND: ESP32 GND ↔ nguồn servo GND.
- Nếu servo buzz mạnh, nóng, hoặc đụng end-stop: ngắt nguồn servo ngay.

## Upload bằng Thonny

1. Mở Thonny.
2. Chọn interpreter MicroPython ESP32.
3. Mở file `esp32_servo_tester/main.py`.
4. Save vào board với tên `main.py`.
5. Reset board.
6. Dùng Thonny Shell command bên dưới.

## Test min/max cơ khí trước

Chạy command này trong Thonny Shell:

```text
limits
```

Nó sẽ dừng từng bước để quan sát:

```text
neutral:          pan=90  tilt=0
hmin:             pan=50  tilt=0
hmax:             pan=130 tilt=0
vmax:             pan=90  tilt=50
diag hmin+vmax:   pan=50  tilt=50
diag hmax+vmax:   pan=130 tilt=50
neutral final:    pan=90  tilt=0
```

Nếu góc nào buzz/kẹt/end-stop, ghi lại và giảm range.

## Command nhanh theo trục

```text
hmid    # pan=90
hmin    # pan=50
hmax    # pan=130
vmid    # tilt=0
vmin    # tilt=0
vmax    # tilt=50
pose 90 0
pose 50 0
pose 130 0
pose 90 50
```

## Test từng servo riêng

```text
classify h1
classify h2
classify v1
classify v2
```

Safe quick test:

```text
test h1
test h2
test v1
test v2
```

Gửi góc cụ thể cho một servo:

```text
angle h1 90
angle h1 50
angle h1 130
angle v1 0
angle v1 50
```

Release PWM:

```text
release h1
release all
```

## Bảng ghi kết quả

Điền tay sau khi test:

| Axis/Slot | Pin | Neutral | Min OK | Max OK | Có buzz/kẹt? | Ghi chú |
|---|---:|---:|---:|---:|---|---|
| h1 | 42 | 90 | | | | |
| h2 | 39 | 90 | | | | |
| v1 | 41 | 0 | | | | |
| v2 | 38 | 0 | | | | |

Sau khi min/max cơ khí ổn, mới chạy laptop app qua UART USB.
