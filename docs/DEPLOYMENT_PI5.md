# Deployment Spec — Track Eye trên Raspberry Pi 5 (CPU-only)

> Tài liệu này mô tả việc cần làm, linh kiện cần mua, và kế hoạch triển khai project
> gaze-tracking → mắt servo animatronic từ laptop (Windows) sang Raspberry Pi 5.
> Đã loại bỏ các hướng accelerator (Hailo/Coral) theo quyết định: **CPU-only**.
>
> Đọc kèm: `README.md`, `AGENT_CONTEXT.md`, `config.yaml`.
> Tham chiếu prior-art đã kiểm chứng: Will Cogley "Animatronic Eyes" — https://hackaday.com/2025/08/28/animatronic-eyes-are-watching-you/

---

## 1. Mục tiêu & phạm vi

- **Mục tiêu:** chạy toàn bộ pipeline gaze tracking trên **Raspberry Pi 5 (8GB)** thay cho laptop, giữ nguyên đường actuation hiện tại: **Pi → USB UART → ESP32-S3 → servo** (1 mắt, pan/tilt).
- **Cự ly hoạt động:** desktop/kiosk **~30–60 cm**, ánh sáng thường (visible light).
- **Ràng buộc cốt lõi:** **latency** của vòng điều khiển (mắt phải bám nhanh) > FPS trung bình.
- **Ngoài phạm vi (lần này):** Hailo/Coral accelerator, quantization/pruning model, train model gaze riêng. (Xem §8.)

## 2. Kiến trúc khi deploy (CPU-only)

```
[Camera] → OpenCV VideoCapture (V4L2, MJPG)
        → MediaPipe FaceMesh + iris (CPU/XNNPACK)
        → GazeEstimator (x_ctrl, y_ctrl, confidence)
        → SessionManager (gating kiosk)
        → Calibration (axis5/affine)
        → SingleEyeServoMapper (pan/tilt) + smoothing/deadzone
        → USB UART "EYE,pan,tilt,gate" → ESP32-S3 → 4 servo 180°
```

- ESP32-S3 trên Pi xuất hiện ở **`/dev/ttyACM0`** (hoặc `ttyUSB0`), **không phải `COM5`**.
- **Ngân sách hiệu năng thực tế (chưa đo):** FaceMesh+iris ~**10–20 FPS** CPU. Thiết kế vòng điều khiển quanh giả định **vision ~10–15 Hz + smoothing/interpolation** để servo vẫn mượt.

---

## 3. Bill of Materials — linh kiện cần mua

> Đã có sẵn: Raspberry Pi 5 (8GB), nguồn, thẻ SD (đã cài OS). Giá USD chỉ để tham khảo — kiểm tra giá tại VN.

### 3.1 Bắt buộc

| # | Linh kiện | Vì sao cần | Giá ~ | Ghi chú |
|---|---|---|---|---|
| 1 | **Tản nhiệt chủ động** (Official Active Cooler hoặc case có quạt) | MediaPipe đẩy CPU 100% liên tục → throttle ~80°C nếu chỉ tản thụ động | $5–15 | Gần như bắt buộc cho workload này |
| 2 | **Camera** (xem §3.3 để chọn) | Đầu vào chính | — | Quyết định USB vs CSI ở §7 |
| 3 | **Cáp USB nối Pi ↔ ESP32-S3** | Đường UART output | $2–5 | Đúng đầu cắm của board ESP32-S3 (thường USB-C) |

### 3.2 Khuyến nghị / dự phòng

| # | Linh kiện | Vì sao | Giá ~ |
|---|---|---|---|
| 4 | **Nguồn chính thức 27W (5.1V/5A) USB-C** | Pi 5 + webcam + ESP32 cắm cùng dễ undervoltage nếu nguồn yếu | $12–15 |
| 5 | Hub USB có nguồn (nếu cắm nhiều thiết bị) | Tránh sụt áp cổng USB | $10–20 |
| 6 | (Nếu đi CSI) **Cáp camera 22-pin "Standard–Mini" cho Pi 5** | Pi 5 dùng đầu CSI 22-pin nhỏ; Camera Module 3 bán kèm cáp 15-pin CŨ **không vừa** | $2–5 |

### 3.3 Lựa chọn camera (cự ly 30–60 cm, ánh sáng thường)

**A. USB Webcam (UVC) — ít sửa code nhất, khuyến nghị cho bản chạy đầu**

| Model | Res | Lấy nét | Hợp 30–60cm | Giá ~ | Đánh giá |
|---|---|---|---|---|---|
| **Logitech C920 / C920x** ⭐ | 1080p30 | Autofocus | ✅ Rất tốt | $60–70 | Lựa chọn USB tốt nhất, cắm `cv2.VideoCapture(0)` là chạy |
| Logitech C922 | 1080p30 | Autofocus | ✅ | $70 | Tương đương C920 |
| Logitech C270 | 720p30 | Fixed | ⚠️ Khá | $25 | Rẻ, plug-and-play; nét cố định hơi mềm ở 30cm |

**B. Pi Camera CSI — quang học/autofocus tốt, gọn, nhưng phải viết shim Picamera2**

| Model | Cảm biến | Lấy nét | Hợp 30–60cm | Giá ~ | Đánh giá |
|---|---|---|---|---|---|
| **Camera Module 3 (standard)** ⭐ | IMX708 12MP | Autofocus | ✅ Rất tốt | $25–35 | Cần cáp 22-pin Pi 5 + shim Picamera2 → OpenCV |
| Camera Module 3 Wide | IMX708 | Autofocus | ❌ quá rộng | $35 | Góc rộng → mặt nhỏ, iris ít pixel. Không khuyến nghị |

### 3.4 Tùy chọn robustness (chỉ khi visible-light fail vì kính/ánh sáng) — §8

| Linh kiện | Vì sao | Giá ~ |
|---|---|---|
| Pi Camera **NoIR** + **IR LED 850nm** + (tùy) filter | Robust với ánh sáng biến đổi & kính | $30–50 |

---

## 4. Phần mềm cần chỉnh (port Windows → Pi Linux)

| Hạng mục | Hiện tại (Windows) | Đổi trên Pi |
|---|---|---|
| OS | — | **Pi OS 12 Bookworm 64-bit** (wheel `mediapipe==0.10.14` aarch64 hợp Python 3.11) |
| Camera backend | `camera_backends: [dshow, msmf]` (`config.yaml`) | **`[default]`** (V4L2). dshow/msmf là Windows-only → lỗi trên Pi |
| Cổng servo | `--servo-port COM5` | `--servo-port /dev/ttyACM0` |
| Cài đặt | `requirements.txt` | `python3 -m venv .venv && pip install -r requirements.txt` (mediapipe aarch64 cài thẳng) |
| Quyền serial | — | thêm user vào group `dialout` (`sudo usermod -aG dialout $USER`) |

**Đề xuất:** tạo profile config riêng `config.pi.yaml` (không đụng config Windows đã tune):
- `frame_width/height: 640/480` (hoặc 848/480)
- `camera_backends: [default]`
- `debug: false`
- `benchmark_autosave: false`

---

## 5. Kế hoạch tối ưu (đo trước — vặn sau)

| Tier | Việc | Loại | Kỳ vọng |
|---|---|---|---|
| **0** | Profile bằng FPS counter + benchmark sẵn có; `vcgencmd measure_temp`/`get_throttled` | Đo | Biết bottleneck nằm ở capture / inference / draw / serial |
| **1** | `config.pi.yaml`: hạ res, `debug:false`, `benchmark_autosave:false`, headless (`--no-display`), V4L2 | Config | FPS↑, gần như free |
| **2** | MJPG fourcc (`CAP_PROP_FOURCC`), threaded capture (lấy frame mới nhất, bỏ frame cũ) | Code nhỏ | Latency↓, FPS↑ |
| **3** | Đo "giá" iris (`refine_landmarks` on/off); giữ tracking liên tục | Model | Quyết có giữ iris |
| **4** | CPU governor `performance`, active cooling, headless không GUI desktop | OS | Tránh throttle/ramp latency |
| **5** | Tách thread gửi servo UART (non-blocking); vision ~10–15Hz + smoothing/deadzone | Pipeline | Mắt mượt dù FPS thấp |

> Lưu ý đã đính chính: hạ resolution **không** giảm thời gian inference của landmark+iris (input cố định sau crop ROI) — nó giúp capture/detector/băng thông. Sàn FPS vẫn do landmark+iris quyết → **phải đo (Tier 0)**.

---

## 6. Roadmap theo phase (kèm tiêu chí nghiệm thu)

**Phase 0 — Môi trường (½ ngày)**
- Cài Bookworm 64-bit, tạo venv, `pip install -r requirements.txt`.
- ✅ Nghiệm thu: `python -m unittest discover -s tests` **PASS trên Pi**; import được mediapipe/opencv.

**Phase 1 — Camera trên Pi (½ ngày)**
- Cắm camera đã chọn; nếu USB → V4L2 `VideoCapture(0)`; nếu CSI → viết shim Picamera2.
- ✅ Nghiệm thu: đọc được frame, đo FPS thô của riêng capture (chưa inference).

**Phase 2 — Baseline + profile (1 ngày)**
- Chạy `main.py --no-display` với `config.pi.yaml`. Ghi FPS, latency từng tầng, nhiệt.
- ✅ Nghiệm thu: có **số liệu bottleneck** + nhiệt độ ổn định dưới throttle.

**Phase 3 — Tối ưu Tier 1–2 (1–2 ngày)**
- Áp config profile + MJPG + threaded capture.
- ✅ Nghiệm thu: FPS/latency cải thiện **đo được** so với baseline Phase 2.

**Phase 4 — Servo loop (1–2 ngày)**
- Kết nối ESP32 `/dev/ttyACM0`, chạy `--servo-port`, tách thread serial, smoothing + deadzone.
- ✅ Nghiệm thu: mắt servo **bám gaze, không giật**, không flood serial. (Mốc giống Will Cogley.)

**Phase 5 — Ổn định hoá (½–1 ngày)**
- CPU governor `performance`, active cooling, đóng `systemd` service auto-start + restart-on-failure, headless.
- ✅ Nghiệm thu: boot là tự chạy; chạy liên tục ≥30 phút **không throttle/crash**.

**Phase 6 (tùy chọn) — Robustness IR (nếu cần) (2–3 ngày)**
- Chỉ làm nếu Phase 4–5 cho thấy kính/ánh sáng gây lỗi. NoIR + IR LED 850nm.
- ✅ Nghiệm thu: tracking ổn định với kính / ánh sáng yếu.

---

## 7. Quyết định cần chốt

1. **Camera:** USB **C920** (ít sửa code, khuyến nghị) **vs** **Camera Module 3** (gọn, autofocus tốt, nhưng cần cáp 22-pin + shim Picamera2).
2. **Hình thức build:** prototype để bàn (USB tiện) hay nhúng kín vào thân robot (CSI gọn hơn).

## 8. Đã loại trừ (ghi rõ để không đi nhầm)

- **Hailo-8L / Coral:** không dùng (quyết định CPU-only). Lưu ý: kể cả dùng, **Hailo không chạy MediaPipe face mesh + iris** của project (chỉ face *detection*); Coral **không** chạy MediaPipe — nhiều claim ngược trong bộ deep-research là **bịa/thổi phồng** (vd arXiv 2503.12345 không tồn tại đúng nội dung).
- **Quantization/pruning:** không khả thi vì MediaPipe là model black-box float32 sau API cấp cao; lợi ích CPU không chắc + rủi ro giảm chính xác iris.
- **Deep gaze models (L2CS-Net, MPIIGaze...):** quá nặng cho Pi CPU real-time.

## 9. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| FPS thấp hơn kỳ vọng (~10) | Thiết kế loop quanh 10–15Hz + smoothing; cân nhắc tắt iris nếu không cần trục dọc |
| Throttle nhiệt | Active cooling + governor performance + theo dõi `vcgencmd` |
| Undervoltage khi cắm nhiều USB | Nguồn 27W chính thức + hub có nguồn |
| CSI không cắm vừa Pi 5 | Mua đúng cáp 22-pin "Standard–Mini" |
| Glasses/ánh sáng làm mất track | Phase 6 IR (chỉ khi cần) |
