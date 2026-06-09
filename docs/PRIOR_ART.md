# Prior Art & Verified Facts — Gaze Tracking → Animatronic Servo Eye on Raspberry Pi

> **Nguồn gốc:** Tổng hợp từ ~6 lần chạy "deep research" (lưu local tại
> `archive/deep_research_2026-06-09/`, đã gitignore). Các báo cáo đó **trộn lẫn thật và bịa**
> (số sao loạn, repo ảo, arXiv giả). File này **chỉ giữ phần đã kiểm chứng bằng nguồn sơ cấp**
> (logitech.com, raspberrypi.com, PyPI, GitHub API trực tiếp, MediaPipe docs) tính đến **2026-06-09**,
> và liệt kê rõ các claim đã loại bỏ ở §4.
>
> Quy ước: ✅ verified · ⚠️ đúng nhưng nguồn thứ cấp / cần tự đo · ❌ sai/bịa.

---

## 1. Sự thật phần cứng & phần mềm (đã verify nguồn sơ cấp)

### Camera
| Hạng mục | Verdict | Sự thật | Nguồn |
|---|---|---|---|
| Logitech **C270** | ✅ | 720p/30, FOV **55° chéo** | logitech.com |
| C270 fixed-focus, nét ở **>30cm** | ⚠️ | Đúng nhưng là kiến thức phổ biến — **không có trên trang spec Logitech**. Hệ quả: ở **~30cm có thể hơi mềm**, **~45–60cm tốt** | thứ cấp |
| Logitech **C920** | ✅ | 1080p/30, **autofocus**, FOV **78° chéo** | logitech.com |
| **Camera Module 3** | ✅ | Sony **IMX708 12MP**, **PDAF autofocus**, HDR, có bản **NoIR** | raspberrypi.com |
| Camera Module 3 FOV | ✅ | Standard **66°H**/41°V · Wide **102°H**/67°V (docs ghi H×V, không phải chéo) | raspberrypi.com |

### Raspberry Pi 5
| Hạng mục | Verdict | Sự thật |
|---|---|---|
| Đầu CSI | ✅ | Pi 5 dùng **22-pin mini** (Pi 4 = 15-pin). Camera Module 3 bán kèm cáp 15-pin cũ → **cần cáp "Standard–Mini" riêng cho Pi 5** |
| Nguồn | ✅ | Board cần **5V/5A (25W)**; PSU khuyến nghị = bộ **27W chính hãng** (5.1V/5A) |
| Nhiệt | ✅ | Throttle **80–85°C** → cần **active cooling** cho tải CV liên tục |

### MediaPipe / runtime
| Claim | Verdict | Sự thật |
|---|---|---|
| `mediapipe==0.10.14` có wheel **aarch64** (cp39–312) | ✅ | `pip install` chạy thẳng trên Pi 5 / Bookworm 64-bit / Python 3.11 (PyPI) |
| Model face mesh của project (**legacy `mp.solutions.face_mesh`**) là **float32**, không có bản quantized | ✅ | Google không phát hành bản int8/float16 cho model legacy này (issue #5773) |
| **Iris (`refine_landmarks`) KHÔNG tự cho hướng nhìn** | ✅ | Chỉ refine landmark iris/mắt; phải tự map ra gaze |
| **FPS trên Pi** | ⚠️ | **Không có benchmark chính thức.** Nguồn thứ cấp gợi ý ~10 FPS face mesh trên Pi 4; **Pi 5 chưa đo** → **PHẢI tự profile**, đừng cam kết con số |
| CSI trên **Bookworm** | ⚠️ | Đường tin cậy là **Picamera2 → OpenCV shim**, không phải `cv2.VideoCapture(0)` thẳng |
| **Hailo-8L** chạy MediaPipe face mesh/iris | ❌ | Không. `hailo-rpi5-examples` chỉ có detection/pose/segmentation/depth |
| **Coral Edge-TPU** chạy MediaPipe face/iris | ❌ | Không (Model Zoo không có; FaceLandmarker float16 ≠ int8 Edge-TPU) |

---

## 2. Người ta đã làm gì — chia theo 3 mảng

Prior-art chia đúng theo 3 mảng của bài toán:
- **(A) Perception** (mắt/gaze từ webcam) → **project này đang đi trước** (MediaPipe iris); prior-art đa số yếu hơn (dlib/OpenCV cổ điển) → chỉ tham khảo ý tưởng.
- **(B) Control mapping** (gaze/offset → góc servo, deadzone, smoothing) → prior-art **áp dụng trực tiếp**.
- **(C) Actuation** (ESP32 + servo + cơ cấu mắt) → có sẵn nhiều build, kể cả port ESP32 của cơ cấu nổi tiếng.

### Bảng project (số liệu lấy trực tiếp GitHub/Hackaday, 2026-06-09)
| Project | Số liệu | Họ làm gì | Áp dụng vào | Mảng |
|---|---|---|---|---|
| **Will Cogley — Animatronic Eyes** ([Hackaday 2025-08-28](https://hackaday.com/2025/08/28/animatronic-eyes-are-watching-you/)) | — | MediaPipe → offset X/Y → **6 servo**; **deadzone + smoothing**; **mắt liếc trước, đầu theo sau**; laptop→Pi dự định | Pattern L9 (đích của bạn) | B+C |
| **GerNavBet — EYEMECH 3.2 / ESP32** ([repo](https://github.com/GerNavBet/Will-cogley-s-EYEMECH-3.2-control-code-adapted-for-ESP32-with-PCA9685-servo-controller)) | 22★, GPLv3, 2025-04 | Port điều khiển **cơ cấu mắt EYEMECH** sang **ESP32 + PCA9685** (MicroPython, 6 servo). ⚠️ auto/manual joystick — **KHÔNG face-tracking** | Firmware servo + cơ khí mắt | C |
| **antoinelame/GazeTracking** ([repo](https://github.com/antoinelame/GazeTracking)) | **2,587★**, MIT, 2026-04 | dlib webcam → pupil + **gaze ratio** + **blink**, no calibration | Ý tưởng gaze-ratio + blink (tham khảo) | A |
| **JEOresearch/EyeTracker** ([repo](https://github.com/JEOresearch/EyeTracker)) | **878★**, MIT, 2026-06 | Pupil bằng **ellipse-fit**, có file **Raspberry Pi**, IR-friendly + hướng dẫn DIY camera IR | Pupil cổ điển / đường IR (Phase 6) | A/IR |
| **ankurrajw/Pi-Pupil-Detection** ([repo](https://github.com/ankurrajw/Pi-Pupil-Detection)) | 14★, 2023-03 | Pupil **real-time Pi 4B**, **head-mounted IR**, paper Univ. Siegen 2023 | Tham khảo kỹ thuật IR (xa form kiosk) | A/IR |
| **PyImageSearch — Pan/Tilt** ([bài](https://pyimagesearch.com/2019/04/01/pan-tilt-face-tracking-with-a-raspberry-pi-and-opencv/)) | — | Haar + **PID** lái servo. ⚠️ **KHÔNG có deadzone** | Tham khảo **PID** | B |
| **AbhiAlderman/Animatronic-Eyes** ([repo](https://github.com/AbhiAlderman/Animatronic-Eyes)) | 0★, 2022 | ESP32-CAM, face-detect on-board, mắt follow mặt | Cấu trúc firmware ESP32-CAM (toy) | C |
| **Zappo-II/animatronic-eyes** ([repo](https://github.com/Zappo-II/animatronic-eyes)) | 1★, 2026-01 | ESP32 + web UI, **điều khiển tay (KHÔNG face-tracking)**, OTA, calibration | Tham khảo firmware + web UI + OTA | C |

---

## 3. Những thứ nên áp dụng (map vào kiến trúc L1–L9 của project)
1. **L9 — deadzone + smoothing (Will Cogley), PID (PyImageSearch):** lấy deadzone/làm mượt từ Will Cogley (KHÔNG phải PyImageSearch — bài đó không có deadzone); lấy ý tưởng PID từ PyImageSearch nếu EMA+rate-limit hiện tại bị lag/overshoot.
2. **L9 — "eye-leads-head" (Will Cogley):** ghi nhận cho roadmap nếu thêm trục đầu.
3. **Firmware/C — EYEMECH-ESP32 + PCA9685 (GerNavBet):** blueprint cho cơ cấu mắt + firmware nhiều servo; khớp hướng ESP-NOW/2-ESP32.
4. **L3 — blink gating (GazeTracking):** dùng openness/clearance sẵn có làm tín hiệu nhắm mắt để gate servo.
5. **Phase 6 — IR path (JEOresearch + Pi-Pupil-Detection):** tham chiếu khi kính/ánh sáng phá tracking.

**Không adopt:** thay MediaPipe bằng dlib/OpenCV cổ điển cho ánh sáng thường (đang dùng cái tốt hơn); kiến trúc head-mounted IR (lệch form kiosk).

---

## 4. ❌ Các claim đã LOẠI BỎ (bịa / sai / không kiểm chứng được)
- **arXiv 2503.12345 = "Coral gaze 16/25 FPS"** → **BỊA** (ID đó là bài *table QA*, không liên quan).
- **"Coral có model gaze sẵn trong Model Zoo, 25 FPS, $80 cắm-là-chạy"** → sai.
- **"Hailo chính thức hỗ trợ facial landmarking / face_landmarks_lite 431 FPS / tin đồn palm-hand là lỗi thời"** → thổi phồng/không nguồn; thực tế Hailo không chạy MediaPipe face mesh+iris.
- **"6–8 giây latency (Cornell ECE5725)"**, **"Optimium 33% nhanh hơn, không đổi 1 dòng code"** → nguồn mơ hồ, không kiểm chứng.
- **"EyeLoop >1000 FPS"** → đúng nhưng là **PC + camera tốc độ cao**, KHÔNG phải Pi/webcam → vô nghĩa cho bài toán này.
- **Mọi số sao GitHub / ngày "last activity" trong các báo cáo gốc** → loạn và mâu thuẫn; chỉ tin số ở §2 (lấy trực tiếp).

---

## 5. Kết luận cho project
- Mảng **perception (A) bạn đang đi trước**; giá trị prior-art lớn nhất ở **control (B)** và **actuation (C)**.
- Blueprint sát nhất cho phần còn phải làm = **Will Cogley + bản port EYEMECH-ESP32/PCA9685**.
- **FPS phải tự đo trên Pi** (không có số chính thức) — đừng cam kết trước khi profiling.
- C270 ổn nếu giữ **~45–60cm + ánh sáng đủ**; nâng cấp (C920 / IR) chỉ khi đo thấy iris kém.

**Nguồn chính:** logitech.com · raspberrypi.com · pypi.org/project/mediapipe/0.10.14 · github.com/google-ai-edge/mediapipe (issue #5773) · github.com/hailo-ai/hailo-rpi5-examples · các repo & Hackaday đã dẫn ở §2.
