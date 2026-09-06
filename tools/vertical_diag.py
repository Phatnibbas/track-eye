"""Đo xem cách chuẩn hoá nào tách được LIẾC LÊN / LIẾC XUỐNG.

Vì sao cần: trục ngang chuẩn hoá bằng `width` (khoảng cách 2 khoé mắt — cứng),
trục dọc chuẩn hoá bằng `eye_h` (độ mở mi — co giãn theo chính hướng nhìn và theo
chớp mắt). Script này đo 4 ứng viên trên cùng một dữ liệu và chấm điểm khách quan.

Chạy trên Pi (phải dừng pupil.service trước, camera không mở 2 lần được):
    sudo systemctl stop pupil
    ~/track-eye/.venv/bin/python ~/track-eye/tools/vertical_diag.py
    sudo systemctl start pupil

Làm theo lời nhắc trong terminal. QUAN TRỌNG: **giữ yên đầu**, chỉ đảo con ngươi
(trừ pha cuối cố tình cúi đầu để đo nhiễu do đầu).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import mediapipe as mp  # noqa: E402

from constants import EYE_DEFINITIONS, IRIS_GROUPS  # noqa: E402

PHASES = [
    ("CENTER", "Nhin THANG vao camera", 6),
    ("UP", "Liec LEN (dau yen, chi dao con nguoi)", 6),
    ("CENTER2", "Nhin THANG vao camera", 6),
    ("DOWN", "Liec XUONG (dau yen, chi dao con nguoi)", 6),
    ("HEADDOWN", "Nhin THANG vao camera nhung CUI DAU xuong", 6),
]

# các cách chuẩn hoá trục dọc đem ra so
METRICS = ["v_lid", "v_wid", "v_iris", "ear", "h_wid"]


def measure(px: np.ndarray, eyedef: dict, iris_group: tuple) -> dict:
    c0 = px[eyedef["corners"][0]]
    c1 = px[eyedef["corners"][1]]
    top = np.mean([px[i] for i in eyedef["top"]], axis=0)
    bottom = np.mean([px[i] for i in eyedef["bottom"]], axis=0)
    ring = [px[i] for i in iris_group]
    iris_c = np.mean(ring, axis=0)
    iris_r = float(np.mean([np.linalg.norm(p - iris_c) for p in ring]))

    eye_center = (c0 + c1) * 0.5
    u = c1 - c0
    width = float(np.linalg.norm(u))
    u = u / max(width, 1e-6)
    v_axis = np.array([-u[1], u[0]])
    eye_h = float(np.linalg.norm(top - bottom))

    disp = iris_c - eye_center
    dv = float(np.dot(disp, v_axis))
    dh = float(np.dot(disp, u))
    # dấu: chuẩn hoá để "+" luôn là XUỐNG, bất kể khoé nào là index 0
    sgn = 1.0 if u[0] >= 0 else -1.0
    return {
        "v_lid": sgn * dv / max(eye_h * 0.5, 1e-6),    # công thức HIỆN TẠI
        "v_wid": sgn * dv / max(width * 0.5, 1e-6),    # chuẩn hoá bằng khoé mắt
        "v_iris": sgn * dv / max(iris_r, 1e-6),        # chuẩn hoá bằng bán kính mống
        "ear": eye_h / max(width, 1e-6),               # độ mở mi (để soi nhiễu)
        "h_wid": dh / max(width * 0.5, 1e-6),          # trục ngang (đối chứng đã chạy tốt)
    }


def stats(values: list[float]) -> tuple[float, float]:
    a = np.asarray(values, dtype=np.float64)
    return float(a.mean()), float(a.std())


def main() -> int:
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        print("KHONG MO DUOC CAMERA (pupil.service con dang chay?)")
        return 1

    face_mesh = mp.solutions.face_mesh.FaceMesh(
        max_num_faces=1, refine_landmarks=True,
        min_detection_confidence=0.5, min_tracking_confidence=0.5)

    # data[phase][eye_idx][metric] = list of samples
    data = {p[0]: [{m: [] for m in METRICS} for _ in EYE_DEFINITIONS] for p in PHASES}
    nofacce = {p[0]: 0 for p in PHASES}

    print("\n=== DO TRUC DOC — giu YEN DAU, chi dao con nguoi ===\n", flush=True)
    for name, prompt, secs in PHASES:
        for c in (3, 2, 1):
            print(f"  {prompt} ... bat dau sau {c}", flush=True)
            time.sleep(1)
        print(f"  >>> {name}: DANG DO {secs}s — GIU NGUYEN", flush=True)
        t0 = time.time()
        while time.time() - t0 < secs:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            h_img, w_img = frame.shape[:2]
            res = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if not res.multi_face_landmarks:
                nofacce[name] += 1
                continue
            lm = res.multi_face_landmarks[0].landmark
            px = np.array([[p.x * w_img, p.y * h_img] for p in lm], dtype=np.float64)
            for i, (eyedef, iris) in enumerate(zip(EYE_DEFINITIONS, IRIS_GROUPS)):
                m = measure(px, eyedef, iris)
                for k in METRICS:
                    data[name][i][k].append(m[k])
        n = len(data[name][0]["v_lid"])
        print(f"  >>> xong, {n} mau\n", flush=True)

    cap.release()
    face_mesh.close()

    lines = []
    lines.append("=" * 78)
    lines.append("KET QUA — trung binh +/- do lech chuan moi pha")
    lines.append("=" * 78)
    for i, eyedef in enumerate(EYE_DEFINITIONS):
        lines.append(f"\n--- MAT {eyedef['name']} ---")
        lines.append(f"{'pha':<10}" + "".join(f"{m:>16}" for m in METRICS))
        for name, _, _ in PHASES:
            row = f"{name:<10}"
            for m in METRICS:
                vals = data[name][i][m]
                if not vals:
                    row += f"{'--':>16}"
                    continue
                mu, sd = stats(vals)
                row += f"{mu:>9.3f}+-{sd:<5.3f}"
            lines.append(row)

        lines.append("")
        lines.append("  KHA NANG PHAN BIET  D = |mean(UP) - mean(DOWN)| / (std(UP)+std(DOWN))")
        lines.append("  D < 1 = khong tach duoc | 1-3 = yeu | > 3 = tach ro")
        for m in METRICS:
            up, dn = data["UP"][i][m], data["DOWN"][i][m]
            if not up or not dn:
                continue
            mu_u, sd_u = stats(up)
            mu_d, sd_d = stats(dn)
            d = abs(mu_u - mu_d) / max(sd_u + sd_d, 1e-6)
            verdict = "TACH RO" if d > 3 else ("yeu" if d > 1 else "KHONG TACH DUOC")
            lines.append(f"    {m:<8} D = {d:7.2f}   {verdict}")

        lines.append("")
        lines.append("  NHIEU DO CUI DAU (gaze khong doi):  |mean(HEADDOWN) - mean(CENTER2)|")
        lines.append("  so voi bien do that |mean(UP) - mean(DOWN)|. Ti le cang nho cang tot.")
        for m in METRICS:
            c2, hd = data["CENTER2"][i][m], data["HEADDOWN"][i][m]
            up, dn = data["UP"][i][m], data["DOWN"][i][m]
            if not (c2 and hd and up and dn):
                continue
            drift = abs(stats(hd)[0] - stats(c2)[0])
            span = abs(stats(up)[0] - stats(dn)[0])
            lines.append(f"    {m:<8} nhieu/bien do = {drift / max(span, 1e-6):6.2f}")

    lines.append("")
    lines.append(f"frame mat mat (khong thay face): {nofacce}")
    out = "\n".join(lines)
    print("\n" + out, flush=True)
    Path("/tmp/vertical_diag.txt").write_text(out, encoding="utf-8")
    print("\n(da luu /tmp/vertical_diag.txt)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
