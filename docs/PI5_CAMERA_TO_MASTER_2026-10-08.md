# Camera Pi5 → USB → master IK; neutral bench bị chặn

## Kết luận có giới hạn

**Đã kiểm chứng bằng dữ liệu camera thật: 36/36 IK queries display-left được
master echo đúng góc và trả về bộ góc motor khớp source đã đối chiếu với board.**
Không có host motor command trong bước này. Không chứng minh pupil accuracy,
hướng cơ khí, actual motor position hoặc ESP-NOW delivery qua test tính toán này.

**Chưa đạt thử chuyển động:** người vận hành duyệt neutral bench có giám sát,
nhưng fresh gate phát hiện node 1/3 OFFLINE/chưa home. Tool dừng trước clear/look;
`clear_count=0`, `move_attempted=false`. 20 status snapshots tiếp theo giữ cùng
trạng thái không ready. Không gọi robot đã xoay theo camera.

## Những quyết định owner đã xác nhận

- Robot một cơ cấu theo **display-left**, `output_left` / `eye_33_133`, không average.
- Probe IK 2° scale, twist=0, az_offset=0, x_sign=+1, y_sign=-1.
- Duration 500 ms chỉ là dự kiến trong mapping config; IK không mang duration.
- Chủ động duyệt một lần clear (nếu gate đạt) và neutral move duration 3000 ms;
  xác nhận người vận hành ở cạnh rig, vùng chuyển động trống, có thể ngắt nguồn.
- Không duyệt bypass readiness, auto-clear lặp, sửa firmware hay home tự động.

Rig signs/offset là giả thuyết trial được duyệt, chưa quan sát directional motion.
Thang 2° là eye orientation so với neutral, không giới hạn quãng đi motor khi
đưa từ home về neutral. Neutral hiện trên source/board là 12.857° mỗi motor.

## Diễn biến đọc trạng thái, không suy diễn nguyên nhân

1. Sau owner báo reset, master vẫn FAULT, n1 OFF, n2/n3 ON nhưng homed=0.
2. Sau owner báo cấp đủ node, USB mất; kernel lúc 17:10:41:
   `disabled by hub (EMI?), re-enabling`, CH340 disconnect. “EMI?” là lead,
   không có đo điện để xác nhận nhiễu.
3. Owner cắm lại USB, attach lúc 17:18:24; camera có face/outputs thật.
4. Lần mở đầu có byte rác và đầy đủ traceback `UnicodeError` ở main.py LineReader;
   probe dừng, không gửi status/cfg/IK vào REPL.
5. Làm sạch input REPL, khôi phục `main()` trong RAM với AUTO_REHOME=false,
   không ghi flash. Master thấy đủ 3 node online và cfg; status xác nhận cả ba
   IDLE, homed=1, fault=False, positions n1/n3=2.989°, n2=1.993°.
6. Trong phiên sau master báo n1 BOOT/HARD_RESET và FAULT. IK đầu bị ghép sau
   FAULT, validator từ chối và timeout; không sửa/đoán header để báo pass.
7. Probe sửa nhỏ: trong cùng serial session, tối đa hai query status để có
   standalone complete snapshot/line boundary rồi gửi typed calculation-only IK.
   Snapshot có FAULT/not-ready được log; **không** cho phép motion chỉ vì IK chạy.
8. Sau proof tính toán và owner duyệt neutral, bench đọc lại: n1/n3 offline,
   homed=0; n2 online/homed. Abort trước clear, không thử lại neutral.

AUTO_REHOME=false chỉ RAM session. Board reset có thể nạp lại true trên flash.
Host không gửi HOME trong các thao tác này; state homed=1 là node/master report,
không khẳng định homing do tác nhân nào hoặc switch chuẩn xác.

## Proof camera → master

Pipeline thực dùng:

```text
production HTTP status (cùng camera owner hiện tại)
 → output_left đã neutral/gain/soft-limit
 → divide active soft_limit=1.5, clamp [-1,1]
 → explicit trial Mapping.polar(x,y)
 → typed 'ik az tilt twist\n' qua USB 115200
 → master echo az/tilt/twist + góc motor
 → compare echo với text gửi 3 decimals
 → compare motor outputs với spm_ik + MOTOR_SIGN + neutral được backup
```

Script `tools/delta_camera_ik_probe.py`; config
`config/delta-camera-ik.validation-20261008.json`. Capture không lưu ảnh, không
thay calibration/production source, không lấy fallback shadow làm mục tiêu.
Giới hạn 20 s, 2 Hz là thông số experiment, không phải accepted live tracking rate.

- 36 samples/query/reply hợp lệ, 0 probe error ở lần chạy đã sync.
- Max absolute motor-target difference: **0.0004922543°**.
- Tolerance khai báo **0.000501°**, vì master in `.3f`; không phải motor accuracy.
- Normalized x quan sát: **-0.403064 … +0.379313**.
- Normalized y quan sát: **-0.075847 … +0.379237**.
- Không có labeled timeline/ground truth từng hướng; chỉ chứng minh số thay đổi.
- Reference tính lại bằng cùng thuật toán firmware, không phải independent IK
  model hay measurement vật lý.

Ví dụ từ artifact:

| Normalized display-left | Lệnh đã gửi | Motor targets master trả (độ) |
|---|---|---|
| (-0.224501, +0.077236) | `ik 198.985 0.475 0.000` | (12.461, 13.127, 12.985) |
| (+0.239026, +0.030921) | `ik 352.629 0.482 0.000` | (13.256, 12.747, 12.569) |
| (-0.080396, +0.039940) | `ik 206.418 0.180 0.000` | (12.712, 12.973, 12.886) |

## Neutral bench và negative gate

One-shot tool `tools/delta_neutral_bench.py`:

- operator approval flag bắt buộc, duration/timeout/tolerance/attempts explicit;
- fresh full status: đủ expected nodes online, homed, IDLE, err=NONE, queue empty;
- clear budget <=1 nếu snapshot đủ gate và master fault;
- phải OK CLEAR + snapshot fault=False trước motion;
- live cfg min/max cho mọi node, neutral IK + reference match;
- kiểm tra đích trong mọi giới hạn, không clamp riêng chân;
- cuối cùng đọc readiness lại trước typed neutral look;
- khi abort sau attempted move thì cố STOP nếu serial còn dùng được;
- reported completion dựa trên node position/target và IDLE, không phải sensor
  góc cơ khí hay operator confirmation.

Run được duyệt: duration=3000 ms, completion timeout=12 s, position tolerance=0.02°
(hơn một microstep ~0.016° theo protocol), IK tolerance=0.000501°, status attempts=2.
Các số bench được truyền CLI, không cài mặc định vào production.

**Observed blocked run:** chỉ hai `status` queries; không clear/look/stop.
Fresh snapshot đủ 3 node: master fault=True, n1/n3 OFF + homed=0, n2 ON/IDLE/homed=1.
Subsequent 20 s monitor: 20/20 standalone statuses có cùng trạng thái. USB còn
giao tiếp, không kernel USB entries mới trong cửa sổ kiểm tra cuối.

## Files và bằng chứng

Project mechanisms thêm: `delta_bridge/ik_validation.py`, `delta_bridge/bench.py`,
typed `ReadOnlySerial.send_ik()` và `Mapping.polar()`.

Pi audit `/home/pi5/track-eye-integration-audit-20261008/`:

- `robot-all-nodes-readonly.json`: snapshot tạm ready/homed.
- `camera-left-ik-20s.jsonl`: failed attempt, merged fault/IK, không bỏ bằng chứng.
- `camera-left-ik-synced-20s.jsonl`: 36 verified replies.
- `neutral-approved-3000ms.jsonl`: abort before clear/move.
- `after-neutral-block-status-20s.jsonl`: latest offline/readiness gate.
- `tests-neutral-bench.txt`, và post-bench regression test run.

Trước neutral attempt Pi **42/42 pass**. Regression thêm exact offline bench
snapshot chứng minh chỉ `status` được gửi, không clear/look. Cuối phiên Pi
**43/43 pass**, Windows **34 pass + 9 Linux-specific skip**. Không lấy suite
green làm thay đổi trạng thái rig. Pi production service vẫn active và calibration
hash giữ nguyên tại 17:36:28 +07.

## Bước tiếp theo

Đường camera→USB→master calculation đã có bằng chứng; trở ngại trước motor motion
là node 1/3 không giữ online/home. Cần kiểm tra hai node và nguồn/link với tác giả
firmware, xác nhận fresh status ổn định trong **cùng** session, rồi thử neutral
có giám sát. Không clear để ép chạy thiếu node, không auto-home che lỗi.
Chỉ sau neutral thực được operator xác nhận mới thử camera-linked look ở 2°,
ghi motion/FAULT/position và label direction; chưa có production continuous sender.
