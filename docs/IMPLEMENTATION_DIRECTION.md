# Track Eye — Hướng triển khai Pi 5 + Logitech C270 (CPU-only)

> **Phạm vi & lập trường.** Mục tiêu là một hệ **Raspberry Pi 5 (8GB) + Logitech C270 (USB) + ESP32-S3 servo eye** chạy ổn định, latency thấp, demo được — **KHÔNG** phải SOTA gaze estimation. Code Python hiện tại trong repo được coi là **bản tham chiếu** (có thể viết lại khi lên Pi), nên tài liệu này validate **HƯỚNG ĐI**, không audit code cũ.
>
> **Kỷ luật trích dẫn.** Mọi claim kỹ thuật đều gắn nguồn ở §10. Đánh dấu độ chắc chắn:
> `✅ đã verify nguồn sơ cấp` · `🟡 nguồn thứ cấp / chưa benchmark chính thức` · `⚠️ phải tự đo, không có số a-priori`.
> Số liệu accuracy trong các paper là **trên dataset/điều kiện của họ**, KHÔNG phải dự đoán cho hệ này.

---

## 1. Constraint phần cứng đã CHỐT (không bàn lại)
- Camera = **Logitech C270 (USB UVC)** qua `cv2.VideoCapture` / V4L2. Không PiCamera/CSI. `[R-c270]`
- Compute = **Pi 5 CPU-only**. Không Hailo, không Coral, không quantize/CNN nặng. `[I-hailo][I-coral]`
- Transport = **USB UART → ESP32-S3** (`EYE,pan,tilt,gate\n`). WiFi/ESP-NOW để sau.
- OS = **Raspberry Pi OS Bookworm 64-bit + Python 3.11**. Không Trixie/Py3.13. `[D-sunfounder][I-mp6159]`

## 2. Mục tiêu & phi-mục-tiêu
**Tối ưu cho:** latency end-to-end thấp · servo motion mượt/không jitter · ổn định trong điều kiện kiosk có kiểm soát · degrade gracefully khi mắt fail · dễ deploy/maintain.
**KHÔNG tối ưu cho:** benchmark học thuật SOTA · gaze-angle chính xác theo độ · point-of-gaze cấp commercial · "cắm là chạy" cho mọi người đeo kính dưới mọi ánh sáng.

Định lượng (🟡/⚠️ — chốt sau khi đo, xem Phase 0):
- FPS perception: **mục tiêu làm việc 10–15 FPS**. ⚠️ **Chưa có benchmark Pi 5 chính thức**; nguồn thứ cấp chỉ cho ~10 FPS FaceMesh trên Pi 4 `[B-core][B-rnt]` → **bắt buộc tự đo**, không cam kết trước.
- Latency end-to-end: <200ms lý tưởng; 200–260ms vẫn dùng được cho cảm giác animatronic. ⚠️ tự đo.
- Nhiệt: tránh throttle kéo dài; giữ dưới ~75–78°C. Pi 5 soft-throttle 80–85°C → **active cooling bắt buộc**. `[D-rpi-power]`

## 3. Bằng chứng nói gì (chia 3 mảng)
Prior-art chia đúng theo 3 mảng của bài toán. Mức độ "đã có người giải trọn vẹn" giảm dần:

**(A) Perception — landmark/iris geometry nhẹ.** Đây là regime được literature ủng hộ cho hệ *deployable* (không phải SOTA): EMC-Gaze nêu rõ nhắm tới "deployment-oriented operating point rather than the image large-backbone regime", dùng **landmark + ridge calibrator + lightweight ONNX 944KB** `[P-emc]`; survey Cheng et al. xác nhận hướng tương lai là "robust gaze features + fast/simple calibration" `[P-survey]`; Gudi et al. (ECCV OpenEyes best paper) nhấn **efficiency + ease-of-calibration** cho webcam real-time `[P-eff]`.
> **Giới hạn phải chấp nhận (✅ verified):** MediaPipe Iris/FaceMesh **không tự cho gaze location**, chỉ landmark `[D-mp-iris]`; và **iris-motion leak vào landmark/face-pose** (MediaPipe issue #1786) `[I-mp1786]` → raw landmark ratio **không** đáng tin tuyệt đối, **bắt buộc** calibration + filtering + confidence gating.

**(B) Control mapping — đã có pattern chuẩn, áp dụng trực tiếp.** Will Cogley animatronic eyes: MediaPipe → offset X/Y → servo, **dead zone + smoothing + "mắt liếc trước, đầu theo sau"** `[R-cogley]`. PyImageSearch pan/tilt: Haar + **PID** (lưu ý: bài đó **không** có deadzone) `[B-pyimg]`. Calibration anchors: differential approach `[P-diff]` và offset-calibration-by-decomposition (1 điểm cũng giảm bias) `[P-offset]`; WEBEYETRACK few-shot ~9 mẫu `[P-wet]`.

**(C) Actuation — kiến trúc Pi/PC → MCU → servo phổ biến.** Bản port **EYEMECH (Will Cogley) sang ESP32 + PCA9685** (MicroPython, 6 servo) là blueprint cơ cấu + firmware `[R-eyemech]`; SaraKIT face-tracking + gimbal note "native camera capture nhanh hơn OpenCV path" `[R-sarakit]`; AbhiAlderman ESP32-CAM eye-follow `[R-abhi]`.
> **Khoảng trống (trung thực):** **Không** project open-source nào giải trọn "Pi 5 + visible-light webcam + gaze thật → animatronic eye" **có benchmark end-to-end**. Phải tự ghép + tự đo.

## 4. Hướng đã validate (build trên Pi)
| Layer | Hướng | Cơ sở |
|---|---|---|
| Perception | MediaPipe FaceMesh + `refine_landmarks=True`, eye/iris geometry → `x_ctrl,y_ctrl,confidence` | `[P-emc][P-survey][D-mp-iris]` |
| Calibration | per-session + **temporal averaging** mỗi điểm + **ridge/polynomial map** (không chỉ affine) + confidence-aware | `[P-emc][P-diff][P-offset][P-wet]` |
| Session/gating | lost-face timeout, min-confidence gate, drift detection, recenter/reset | đặc thù deploy; ít project demo làm `[P-eff]` |
| Servo | Pi làm vision+mapping; **ESP32 làm timing/clamp** (deadzone, EMA, rate-limit, max-step) | `[R-cogley][B-pyimg][R-eyemech]` |
| Transport | UART `EYE,pan,tilt,gate` → ESP32-S3 | kiến trúc (C) |
| UI | headless/no-window cho production; web preview chỉ khi debug | tránh drop FPS `[R-sarakit]` |

## 5. ⭐ Phase 0 — CỔNG KHẢ THI (làm TRƯỚC mọi hardening)
> Đây là phần chống "phí công" quan trọng nhất, và là cái doc cũ thiếu. **Không hardening servo/calibration trước khi tín hiệu gaze được chứng minh dùng được.** Lý do: nếu iris signal quá nhiễu/leak (#1786) ở điều kiện C270 thật, mọi công downstream đổ sông `[I-mp1786][R-c270]`.

**Cách làm:** chạy trên Pi 5 + C270 ở **45–60cm**, ánh sáng kiosk thật, người dùng nhìn lần lượt 5 điểm (center/trái/phải/trên/dưới), thu `x_ctrl,y_ctrl,confidence` (dùng `--no-window` + benchmark JSONL sẵn có làm công cụ thu).

**Metric & cách đặt ngưỡng (⚠️ KHÔNG bịa số a-priori — đo baseline rồi đặt ngưỡng theo nhu cầu servo):**
1. **Separability** giữa các hướng: khoảng cách giữa *mean* của mỗi hướng so với *std* trong-hướng (kiểu SNR/d-prime). Yêu cầu: mean các hướng tách rõ khỏi noise → biên độ tín hiệu phải **lớn hơn deadzone servo** dự kiến, nếu không thì vô dụng.
2. **Jitter khi fixate**: std của `x_ctrl,y_ctrl` lúc nhìn cố định 1 điểm. Ngưỡng = đặt sau khi đo, phải nhỏ hơn deadzone để mắt không rung.
3. **Confidence dropout**: % frame dưới `min_confidence` ở điều kiện đích (thấp = tốt).
4. **Head-motion robustness**: drift của tín hiệu khi lắc đầu nhẹ lúc fixate (kiểm tra trực tiếp ảnh hưởng #1786).
5. **Runtime**: FPS, latency end-to-end, nhiệt sau 30 phút.
6. **Kính**: lặp lại với người đeo kính → quan sát degrade.

**Go / No-Go:**
- **GO** → sang Phase 1 nếu separability > deadzone, jitter < deadzone, dropout chấp nhận được, FPS/latency/nhiệt trong mục tiêu §2.
- **NO-GO** (tín hiệu không tách được dù đã tune khoảng cách/ánh sáng) → **dừng visible-light**, cân nhắc IR/camera khác **TRƯỚC** khi tốn công, không phải sau.

## 6. Các phase build (chỉ sau khi Phase 0 = GO)
- **Phase 1 — Baseline + benchmark matrix:** C270 @ {640×480, 960×540, 1280×720} × {refine on/off} × {web preview on/off}; log FPS p50/p95, confidence dropout, nhiệt, throttle (`vcgencmd measure_temp/get_throttled`). Kiểm MJPG vs YUYV. **Khởi đầu 960×540** (cân bằng iris-pixel vs tốc độ; 720p có thể quá nặng khi bật refine). `[B-rnt][B-toptech]`
- **Phase 2 — Hardening control loop:** deadzone + EMA + UART rate-limit + max-step-per-update + **ESP32-side clamp/smoothing**. Tiêu chí: không micro-jitter ở center, không buzz vô ích, motion "sống". `[R-cogley][B-pyimg]`
- **Phase 3 — Calibration & robustness:** temporal averaging mỗi điểm (0.3–0.5s) · ridge/polynomial nếu affine yếu ở biên · confidence-aware hold · **fallback khi iris unreliable** (hold → coarse face-center; LƯU Ý #1786: head-pose cũng bị iris làm nhiễu, fallback face-center chỉ là coarse) · recenter UX + log drift. `[P-emc][P-diff][P-offset]`
- **Phase 4 — IR (Plan B), CHỈ nếu Phase 0/3 cho thấy visible-light fail vì kính/ánh sáng:** đổi sang NoIR + IR LED 850nm; chấp nhận đổi optics/cơ khí, có thể cần global shutter. Tham chiếu pupil-IR: JEOresearch EyeTracker (ellipse-fit, IR-friendly, có file Pi) `[R-jeo]`, Pi-Pupil-Detection (Pi 4B head-mounted IR, paper) `[R-pipupil]`.

## 7. ĐÃ LOẠI BỎ (kèm lý do + bằng chứng — để không ai đi nhầm)
- **Coral Edge-TPU** ❌ — **ngõ cụt đã verify**: Coral Model Zoo **không có** model face/iris landmark; MediaPipe FaceLandmarker là **float16**, không hợp Edge-TPU (cần int8). Theo đuổi = phí công + đã bị loại. `[I-coral]`
- **Hailo-8L** ❌ — `hailo-rpi5-examples` chỉ có object detection/pose/segmentation/depth; **không** face mesh/iris. `[I-hailo]`
- **PiCamera/CSI + Picamera2 backend** ❌ — dùng C270 USB nên không cần. (Lưu ý: OpenCV issue #25072 — `cv2.VideoCapture` fail trên Pi5 — **chỉ xảy ra với CSI Module 3**, KHÔNG ảnh hưởng USB. `[I-cv25072]`. `--system-site-packages` chỉ cần cho Picamera2 `[D-picam-venv]` → C270 không cần.)
- **Rewrite sang threshold/contour/Haar/dlib-only** ❌ — fragile với ánh sáng thường + kính; chỉ mượn blink/ellipse-fit/fallback ideas. `[R-gazetracking][R-jeo]`
- **Deep gaze model nặng ngay (L2CS-Net/ResNet50/iTracker train mới)** ❌ — tốn dataset/license/train pipeline, chưa chắc tăng chất lượng demo trên Pi 5 CPU; survey xác nhận hướng nhẹ + calibration tốt hơn cho deploy. `[P-survey][P-emc]`

## 8. Rủi ro & xử lý
| Rủi ro | Xử lý |
|---|---|
| **C270 fixed-focus** (mềm khi <30cm) `[R-c270]` | vận hành **45–60cm** + ánh sáng frontal mềm; benchmark 640×480/960×540 trước 720p |
| **Kính** (reflection/occlusion) | confidence threshold → fallback face-center → recalib; cải thiện ánh sáng |
| **Lighting** (backlight/auto-exposure) | ánh sáng frontal mềm; cân nhắc exposure lock sau khi face ổn định |
| **Thermal throttle** | active cooler bắt buộc; benchmark dài; giảm res/preview/skip-frame nếu cần `[D-rpi-power]` |
| **Mechanical backlash** | check linkage, clamp range, center alignment; tránh ép servo vùng biên |
| **iris→pose leak (#1786)** | không tin raw ratio; calibration + filtering + gating; cẩn thận khi dùng head-pose làm fallback `[I-mp1786]` |

## 9. Verification (không claim "ổn" bằng config syntax)
- **Phase 0:** thu signal 5 hướng + tính separability/jitter/dropout + head-motion + kính → quyết GO/No-Go bằng SỐ.
- **Phase 1:** runtime replay + USB webcam thật; log FPS+temp+throttle qua benchmark JSONL.
- **Phase 2:** đo command UART/giây; quan sát jitter ở center; test step-response 4 hướng.
- **Phase 3:** đo ổn định giữa điểm calib; drift sau vài phút; test có/không kính.
- **Phase 4 (nếu IR):** đo lại full pipeline + latency end-to-end.

## 10. Tài liệu tham khảo (đã verify trừ chỗ ghi rõ)

### Papers (✅ tất cả ID dưới đã verify tồn tại + đúng tiêu đề/tác giả)
- `[P-emc]` Zhang, C. *Deployment-Oriented Session-wise Meta-Calibration for Landmark-Based Webcam Gaze Tracking* (EMC-Gaze). arXiv **2603.12388**. — landmark-graph + ridge meta-calibration, 5.79° RMSE, 944KB ONNX. **Sát project nhất.**
- `[P-survey]` Cheng, Wang, Bao, Lu. *Appearance-based Gaze Estimation with Deep Learning: A Review and Benchmark*. arXiv **2104.12668**.
- `[P-eff]` Gudi, Li, van Gemert. *Efficiency in Real-time Webcam Gaze Tracking*. arXiv **2009.01270** (ECCV OpenEyes 2020 Best Paper).
- `[P-diff]` *A Differential Approach for Gaze Estimation*. arXiv **1904.09459** (TPAMI). 🟡 cổ điển, well-known — chưa re-fetch lượt này.
- `[P-offset]` *Offset Calibration for Appearance-Based Gaze Estimation via Gaze Decomposition*. arXiv **1905.04451** (WACV 2020). 🟡 như trên.
- `[P-wet]` Davalos et al. *WEBEYETRACK: Scalable Eye-Tracking for the Browser via On-Device Few-Shot Personalization*. arXiv **2508.19544** (2025-08-27).
- `[P-eyetheia]` Pather et al. *EyeTheia: A Lightweight and Accessible Eye-Tracking Toolbox*. arXiv **2601.06279** (2026-01-09).
- Nền tảng (🟡 cổ điển, well-known): MPIIGaze arXiv **1711.09017**; Full-Face Gaze arXiv **1611.08860** (CVPRW 2017); WebGazer (Papoutsaki et al., IJCAI 2016, https://www.ijcai.org/Proceedings/16/Papers/540.pdf).
- Dataset đúng nếu train sau: **MPIIFaceGaze/MPIIGaze** (laptop webcam), KHÔNG phải GazeCapture (mobile-only) `[P-survey]`.

### Repos (✅ tồn tại; sao/license/ngày lấy trực tiếp GitHub 2026-06-09)
- `[R-cogley]` Will Cogley — *Animatronic Eyes* (Hackaday 2025-08-28): https://hackaday.com/2025/08/28/animatronic-eyes-are-watching-you/ — MediaPipe→offset→6 servo, deadzone+smoothing, eye-leads-head, laptop→Pi dự định.
- `[R-eyemech]` GerNavBet — EYEMECH 3.2 / ESP32+PCA9685 (22★, GPLv3, MicroPython): https://github.com/GerNavBet/Will-cogley-s-EYEMECH-3.2-control-code-adapted-for-ESP32-with-PCA9685-servo-controller — ⚠️ điều khiển cơ cấu (auto/manual), KHÔNG face-tracking.
- `[R-gazetracking]` antoinelame/GazeTracking (2,587★, MIT): https://github.com/antoinelame/GazeTracking — dlib, gaze ratio + blink, no calibration.
- `[R-jeo]` JEOresearch/EyeTracker (878★, MIT): https://github.com/JEOresearch/EyeTracker — ellipse-fit pupil, có file Pi, IR-friendly.
- `[R-pipupil]` ankurrajw/Pi-Pupil-Detection (14★): https://github.com/ankurrajw/Pi-Pupil-Detection — Pi 4B head-mounted IR, paper Univ. Siegen 2023.
- `[R-sarakit]` SaraEye/SaraKIT-Face-Tracking-MediaPipe-Raspberry-Pi-64bit (14★): https://github.com/SaraEye/SaraKIT-Face-Tracking-MediaPipe-Raspberry-Pi-64bit — face mesh + BLDC gimbal.
- `[R-abhi]` AbhiAlderman/Animatronic-Eyes (ESP32-CAM, face-follow): https://github.com/AbhiAlderman/Animatronic-Eyes.
- Demo refs (yếu hơn, chỉ học UX/ROI): AnimeshBanerjee02/Eye-Tracking-System-using-OpenCV-and-MediaPipe (3★); Asadullah-Dal17/Eyes-Position-Estimator-Mediapipe (178★, MIT); CR1502/PiGaze (2★, PyTorch — future direction).

### Docs / issues (✅ verified)
- `[D-rpi-power]` Raspberry Pi 5 power/throttle/cooling: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html (board 5V/5A; soft-throttle 80–85°C; active cooling khuyến nghị).
- `[D-mp-iris]` MediaPipe Iris (không cho gaze direction) — MediaPipe docs.
- `[I-mp1786]` MediaPipe issue #1786 "Face Landmarks affected by eyes/irises motion": https://github.com/google-ai-edge/mediapipe/issues/1786.
- `[I-mp6159]` MediaPipe issue #6159 (no Python 3.13 wheel): https://github.com/google-ai-edge/mediapipe/issues/6159.
- `[I-cv25072]` OpenCV issue #25072 (Pi5 **CSI** Module 3 `read()` fail; KHÔNG ảnh hưởng USB): https://github.com/opencv/opencv/issues/25072.
- `[I-hailo]` Hailo rpi5-examples (không có face mesh/iris): https://github.com/hailo-ai/hailo-rpi5-examples.
- `[I-coral]` Coral models (không có face/iris landmark; float16≠int8): https://coral.ai/models/.
- mediapipe 0.10.14 aarch64 wheel: https://pypi.org/project/mediapipe/0.10.14/ (cp39–312).
- `[D-sunfounder]` SunFounder AI Lab Kit — Bookworm 64-bit recommended, Trixie/Py3.13 không: https://docs.sunfounder.com/projects/ai-lab-kit/en/latest/mediapipe/mp_0_setup.html.
- `[D-picam-venv]` Picamera2 trong venv cần `--system-site-packages` (chỉ liên quan nếu dùng CSI — ta không dùng): Raspberry Pi forums / Picamera2 manual.
- `[R-c270]` Logitech C270 specs (720p, fixed-focus, 55° chéo): https://www.logitech.com/products/webcams/c270-hd-webcam.html (fixed-focus là kiến thức phổ biến, không ghi rõ trên trang spec).

### Blogs / Videos (🟡 tutorial-level / page snippets, KHÔNG xem nội dung video)
- `[B-core]` Core Electronics — MediaPipe face/pose trên Pi: https://core-electronics.com.au/guides/face-tracking-raspberry-pi/
- `[B-rnt]` Random Nerd Tutorials — Install MediaPipe on Pi: https://randomnerdtutorials.com/install-mediapipe-raspberry-pi
- `[B-toptech]` TopTechBoy — Picamera2 trong OpenCV (resolution/FPS): https://toptechboy.com/ai-on-the-edge-lesson-15-use-the-raspberry-pi-camera-in-opencv-to-create-live-video
- `[B-pyimg]` PyImageSearch — Pan/Tilt face tracking + PID (không deadzone): https://pyimagesearch.com/2019/04/01/pan-tilt-face-tracking-with-a-raspberry-pi-and-opencv/
- Video build logs (🟡 chỉ thấy page/description, không verify nội dung): Eye tracking on Pi https://www.youtube.com/watch?v=apTlen7mkTg · Servo controlled eyeball for Pi Camera 2 https://www.youtube.com/watch?v=K9PUCmdXlQc · Raspberry Eye Remote Servo Cam https://www.youtube.com/watch?v=tSJ-sWEJ5EU

## 11. Một câu chốt định hướng
**Đừng biến project thành "research gaze estimator mới". Hãy biến nó thành hệ "servo-ready, low-latency, calibration-aware eye control" chạy ổn trên Pi 5 + C270 — và CHỨNG MINH tín hiệu gaze dùng được (Phase 0) TRƯỚC khi tốn công hardening.**
