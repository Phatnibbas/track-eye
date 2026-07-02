# Track Eye — Session Log + Pivot (2026-07-02) — ⏸️ CHỜ BẠN VALIDATE

> **Trạng thái:** tôi ĐÃ DỪNG, chưa build gì thêm. File này để bạn duyệt lại
> toàn bộ (việc đã làm / sai lầm / đề xuất / lý do) trước khi đi tiếp.
> Nếu OK thì bước kế là build `tools/pupil_spike.py` (mục §5).

---

## 0. TL;DR (đọc cái này trước)

1. **Sai lầm lớn nhất:** cả tôi lẫn memory/doc của các session trước hiểu mục tiêu là
   **"gaze direction"** (đoán bạn nhìn ĐIỂM nào trong không gian → lái 1 con mắt point tới đó).
   **Mục tiêu THẬT (bạn vừa chốt):** **pupil mirroring** — nhại **chuyển động 2 con ngươi**,
   2 mắt servo độc lập (pan+tilt/mắt = 4 servo), trong **hộp xem phim**, **trơ với lắc đầu**.
2. Vì hiểu sai, tôi đã đi spike một hướng **sai công cụ** (appearance-gaze ONNX). Đã đo xong, đã bỏ.
3. Phần **hạ tầng** (kết nối Pi, stream web UI, ép MJPG) **vẫn tốt & tái dùng được**.
4. **Đề xuất mới:** giữ MediaPipe, lấy **tín hiệu per-eye ngươi** đã có sẵn trong code, bỏ phần
   gaze/calibration, thêm per-eye→servo. **Không cần calibration màn hình.** IR để hardening sau.
5. **Cần bạn validate** §3 (hiểu đúng mục tiêu chưa) và §4–5 (method + bước kế) trước khi tôi code.

---

## 1. Việc đã làm trong session này

### 1.1 Code (đúng spec cũ, đã test) — GIỮ ĐƯỢC, độc lập với pivot
- **§3.1 `camera_fourcc` (opt-in MJPG)** trong `main.py::open_camera` + `tests/test_camera_fourcc.py` (4 test).
  - ✅ **Đã ver()fy chạy thật trên Pi:** `v4l2-ctl` báo camera negotiate `MJPG 1280×720` → mở 30fps cam.
- **§3.2 `tools/phase0_capture.py`** (headless benchmark runner) + `tests/test_phase0_capture.py` (9 test).
- **Test suite:** 47 → **60 PASS** (local Windows). Chưa chạy lại trên Pi sau các thay đổi.
- ⚠️ *Lưu ý pivot:* 2 file này build cho khung **"đo separability gaze 5 hướng"** (Stage 0 cũ).
  Phần **camera/MJPG** tái dùng; phần **protocol/report** hướng gaze **có thể không còn hợp** pupil-mirror.

### 1.2 Hạ tầng Pi + xem live — GIỮ ĐƯỢC
- SSH tới Pi (`pi5@pi5.local`, hiện `192.168.1.29`), venv Py3.11 + MediaPipe OK, camera UGREEN `/dev/video0`.
- **S0a free-look:** chạy `main.py --web-ui-host 0.0.0.0` → stream camera + overlay MediaPipe về browser desktop
  (`http://<pi-ip>:8080`). Xác nhận: camera + model chạy, MJPG ~ mục tiêu 14.8 FPS.
- Đây là đường **"người xem live qua web UI"** — tái dùng nguyên cho việc xem per-eye pupil sắp tới.

### 1.3 Spike appearance-gaze ONNX — ĐÃ ĐO, RỒI BỎ (sai công cụ, xem §2.1)
- Build `tools/gaze_onnx_spike.py`: uniface RetinaFace (ONNX) → crop mặt → gaze CNN (MobileOne-S0 ONNX,
  yakhyo/gaze-estimation) → yaw/pitch → mũi tên + FPS → web UI. Cài `onnxruntime`+`uniface` vào venv Pi.
- **Số đo thật Pi 5 (giá trị dữ liệu, dù bỏ hướng):**
  | Cấu hình | FPS | Ghi chú |
  |---|---|---|
  | det mỗi frame + có mặt | **~3.5** | RetinaFace **~250ms** là bottleneck |
  | det/5 frame (amortized) | ~7–8 (ước, có mặt) | gaze CNN ~80ms/frame |
  | trần gaze-only (448² CNN) | ~12 | sàn cứng |
- Kết luận: **bottleneck = face detector, không phải gaze model.** Nhưng bỏ vì **sai mục tiêu**, không phải vì FPS.

---

## 2. Sai lầm / điều chỉnh (thành thật)

### 2.1 ⭐ Hiểu sai mục tiêu — gaze-direction vs pupil-mirroring (sai lầm gốc)
- **Tôi tưởng:** servo point tới **điểm bạn nhìn** (gộp mắt+đầu → 1 hướng). Nguồn: memory
  `gaze-perception-options-researched` ghi *"mắt servo sao chép HƯỚNG NHÌN"* + toàn bộ prior-art xoay quanh gaze.
- **Thật ra:** nhại **chuyển động từng con ngươi** (2 mắt độc lập, trơ với lắc đầu), trong hộp.
- **Hệ quả:** appearance-gaze CNN (Gaze360) ra **1 vector gộp mắt+đầu** → **không** cho per-eye, **không** tách đầu → **sai công cụ**.
- **Đã sửa:** cập nhật memory `project-goal-pupil-mirror` (đánh dấu ⭐, và gắn cờ ⚠️ 2 memory gaze cũ là lệch mục tiêu).

### 2.2 "Model detect rất tệ" bị NHIỄU bởi calibration sai rig (chưa phải trần thật)
- Log Pi khi chạy: `[WARN] Partial calibration loaded (x=ok, y=raw)`.
- `calibration.json` commit trong repo **thu trên rig khác** (camera/khoảng cách khác) đang được autoload;
  **trục dọc (y) rớt hẳn về raw**. → cái "tệ" bạn thấy một phần do calib sai + y không có calib, **không phải** trần của method.
- *(Với pivot, điều này bớt quan trọng: pupil-mirror **không dùng** calibration gaze này.)*

### 2.3 Nhỏ: IP Pi trong memory cũ (`192.168.1.211`) đã hết hạn DHCP → thật là `192.168.1.29`
- Đã sửa memory: dùng mDNS `pi5.local` để lấy IP hiện tại.

### 2.4 Nhỏ (đã fix): `pkill -f "...main.py..."` tự match chính command của nó → tự kill shell trước khi restart.
- Bài học: kill theo PID, hoặc dùng bracket-trick `[m]ain.py`.

---

## 3. Hiểu ĐÚNG mục tiêu (bạn xác nhận — validate lại giúp tôi)

> **Installation hộp xem phim:** người **thò đầu vào hộp**, xem **phim trên màn hình bên trong**.
> **Camera trong hộp** bắt **chuyển động 2 con ngươi**. **Servo bên ngoài nhại lại —
> 2 mắt ĐỘC LẬP, mỗi mắt pan+tilt (4 servo)**. Phải bắt đúng chuyển động ngươi
> **dù người lắc/dịch đầu** (eye-in-head, không phải gaze-in-space).**

Các thông số bạn đã chốt:
- Camera thấy **cả khuôn mặt** (trán→cằm).
- Ánh sáng: **chưa chốt** → tôi tư vấn (§4.2).
- **2 trục/mắt** (ngang+dọc) → cần cả X,Y của con ngươi.

❓ **Validate:** mô tả trên đúng chưa? Có gì thiếu (số servo thật hiện có, khoảng cách đầu–camera, kích thước hộp, loại màn hình)?

---

## 4. Đề xuất method + lý do

### 4.1 Pipeline (thu hẹp "đập đi xây lại")
- **GIỮ:** MediaPipe FaceMesh iris front-end. `gaze_estimator.EyeMeasurement` **đã có sẵn** per-eye:
  `eyes[0]`/`eyes[1]` với `.horizontal`, `.vertical` (chuẩn hoá theo khoé mắt = **head-robust sẵn**) + `.iris_center`.
- **BỎ:** gaze-fusion (gộp 2 mắt thành 1), `CalibrationManager` map-màn-hình, servo gaze-map.
- **THÊM:** per-eye `(horizontal, vertical)` → `(pan, tilt)` mỗi mắt, ×scale + **One-Euro smoothing** → 4 servo.
- **KHÔNG cần calibration màn hình.** Chỉ "nhìn thẳng = 0" 1 lần + hệ số scale + giới hạn (clamp).
- **Lý do:** đúng cái bạn cần (per-eye ngươi, tách đầu); tái dùng phần MediaPipe đã chạy 14.8 FPS; nhỏ & ít rủi ro hơn viết lại.

### 4.2 Ánh sáng: **visible trước, IR sau** (tư vấn)
- **Đe doạ:** màn hình phim đổi sáng liên tục → pupil detection visible chập chờn.
- **IR = chuẩn vàng** (Tobii/pupil-labs/VR đều IR): đèn IR + cam NoIR → ngươi thành đốm rõ, ỔN ĐỊNH, **vô hình** với người xem.
  - Cần: **cam NoIR** (UGREEN hiện có IR-cut filter → không thấy IR, phải đổi cam) + **đèn IR 940nm**.
  - Rủi ro: MediaPipe train mặt visible → trên IR có thể kém → có thể phải đổi sang **detect ngươi kiểu CV (threshold/blob)** trên IR (IR làm việc này *dễ hơn*).
- **Khuyến nghị:** prototype **visible + MediaPipe NGAY** (0 HW mới, cam hiện tại, thấy cả mặt) để validate pipeline +
  đo **độ trơ lắc đầu** + **trục dọc có đủ range**. → nâng **IR** khi visible chập vì ánh sáng phim (bản cuối trong hộp tối gần như chắc cần IR + đổi cam NoIR).

### 4.3 Trục dọc — rủi ro đã biết
- Ngươi lên/xuống bị mí che, biên độ nhỏ, dễ nhiễu (#1786). Đây là trục khó nhất → cần đo sớm xem có đủ tách để lái tilt không.

---

## 5. Bước kế đề xuất (CHỜ BẠN DUYỆT)

**`tools/pupil_spike.py`** (visible, tái dùng `GazeEstimator`, KHÔNG đụng code cũ):
- Vẽ **2 chấm `iris_center`** + **giá trị (h,v) từng mắt** + vector lệch, stream web UI (như free-look).
- Bạn thò đầu vào hộp / ngồi trước cam, test live 3 câu hỏi:
  1. Liếc → **2 chấm bám từng con ngươi độc lập** không?
  2. **Lắc/dịch đầu** giữ mắt nhìn 1 điểm → (h,v) có **đứng yên** không (head-robust)?
  3. **Trục dọc** có tách đủ để lái tilt không?
- Đây là thứ ĐÚNG để nhìn (khác mũi tên ONNX). Chưa đụng servo (theo yêu cầu bỏ servo tới khi được bảo).

Sau spike này (nếu tín hiệu OK): mới bàn tới mapping→servo, One-Euro, rồi IR.

---

## 6. Trạng thái file & Pi (để bạn nắm)

**Local (Windows, chưa commit):**
- Sửa: `main.py` (camera_fourcc). Mới: `tools/phase0_capture.py`, `tools/gaze_onnx_spike.py`,
  `tests/test_camera_fourcc.py`, `tests/test_phase0_capture.py`, `docs/` (file này).
- `tools/phase0_report.py`, `profiles/`, `deploy/` vẫn untracked (từ session trước).

**Trên Pi (`~/track-eye`, working tree đã lệch git do scp — vô hại, reset được):**
- Đã copy: `main.py`, `tools/phase0_capture.py`, `tools/phase0_report.py`, `tools/gaze_onnx_spike.py`, `profiles/`.
- Đã cài vào venv: `onnxruntime 1.27`, `uniface 3.7.1` (+ deps). Clone `~/gaze-estimation` + weights ONNX (~50MB).
- **Đang chạy:** không có gì (đã kill free-look + spike). Camera trống.

**Chưa làm (theo yêu cầu):** không commit/push; không đụng servo/ESP32.

---

## 7. Câu hỏi mở cho bạn (giúp chốt method)
1. Mô tả hộp ở §3 đúng/đủ chưa? Servo thật hiện có mấy con, loại gì? Khoảng cách đầu–camera ~?
2. OK đi hướng **visible trước → IR sau**, hay bạn muốn tính IR (đổi cam NoIR) ngay từ đầu?
3. Cho tôi build `pupil_spike.py` (§5) để xem tín hiệu per-eye live chứ?
4. Mấy file hướng-gaze cũ (`phase0_*`, `gaze_onnx_spike`, prior-art docs) — **giữ để tham khảo** hay **dọn/archive** cho đỡ rối?
