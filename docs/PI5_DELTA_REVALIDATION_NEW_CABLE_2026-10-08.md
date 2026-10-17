# Revalidation sau đổi dây và cổng USB — 2026-10-08

## Kết luận có giới hạn

**USB đã enumerate lại; master trả lời lệnh text sau khôi phục trong RAM.**
Trong 125 giây monitor, không có transport exception hoặc USB disconnect trong
kernel window kiểm tra. Đây không phải chứng minh root cause trước đó đã được
sửa, boot/reconnect an toàn hay hệ cơ khí sẵn sàng.

**Chưa cho phép chuyển động:** master FAULT, node 1 OFFLINE, node 2/3 chưa home.
Đã quan sát master báo boot `HARD_RESET` cho node 2 và node 3 trong RX transcripts;
thời điểm reset thực tế và nguyên nhân chưa được xác minh.

## Thiết lập và identity

- Người vận hành báo đổi dây và cổng; không có mã/model dây để kết luận chất lượng.
- SSH Pi5, user pi5; không đổi service/camera/calibration.
- CH340 `1a86:7523`, attach kernel lúc **16:31:54 +07**, `/dev/ttyUSB0`.
- Port đổi từ `usb 1-2` sang `usb 1-1`.
- Device dùng trong thử nghiệm:
  `/dev/serial/by-path/platform-xhci-hcd.0-usb-0:1:1.0-port0`.
- CH340 không có serial number riêng; by-path pin cổng, không chứng minh identity
  board nếu thay thiết bị ở cùng cổng.
- Cấu hình thí nghiệm lưu tại `config/delta-monitor.validation-20261008.json`:
  baud 115200 theo firmware/PDF; polling 1 Hz; IO timeout 0.5 s; line bound 2048
  bytes; snapshot window 0.5 s; freshness gate 2 s; expected nodes 1,2,3.
  Các timing/bounds là lựa chọn cho diagnostic, không phải mechanical calibration.

## Các bước thực hiện và kết quả

1. Inventory chỉ đọc: CH340/camera hiện diện, không thấy process giữ serial;
   kernel window 10 phút ghi attach, không có disconnect mới.
2. Monitor ngắn dự định 8 s dừng sau ~20 ms, **0 query gửi**: RX có byte UTF-8 lỗi
   và phần đầu `Traceback`. Không tiếp tục gửi protocol commands.
3. Nghe thụ động 4 s ở 115200 đọc được phần traceback `main.py`, không TX.
4. Gửi newline rỗng để kiểm tra prompt: nhận NameError từ input REPL dang dở
   (`NL`) và `>>>`. Không đủ traceback để khẳng định lỗi ban đầu là UnicodeError.
5. REPL inspect xác nhận globals có main/Master/LineReader, auto-rehome true,
   WDT false. Không đọc/ghi secrets hoặc firmware.
6. Khôi phục **RAM-only** bằng `AUTO_REHOME=False; ...; main()` theo phương án
   đã duyệt. Nhận master MAC `F8:B3:B7:50:DD:D0`, neutral ba giá trị 12.857;
   n2/n3 online và cfg. Không sửa file board hoặc reset board.
7. `status`, `cfg`, `ik 0 0 0` trả lời hợp lệ; không host motion command.
8. Monitor 125 s ở 1 status query/s, giữ 115200 giữa lần mở. Thu raw hex và lines.
9. Đọc final status/cfg/IK lần nữa; kernel từ 16:39 tới 16:49 không có entries;
   camera health 200, calibration hash không đổi.

AUTO_REHOME=false chỉ tồn tại trong session RAM này. Sau reset, source trên flash
vẫn đặt true. Khôi phục master chạy ping/supervision, có thể phát STOP theo logic
fault sẵn có; không được suy luận “không gửi host look/home” là không có firmware
control packet hoặc cơ khí tuyệt đối không chuyển động.

## Mẫu monitor 125 giây

| Chỉ số | Quan sát |
|---|---|
| Host status queries | 125 |
| Header `STAT fault=...` đứng riêng | 124 |
| Header + đủ 3 node lines | 124 |
| Node lines n1/n2/n3 | 125 dòng mỗi node |
| Header đầu | Bị ghép với `FAULT n2 khởi động lại`, không tính snapshot hợp lệ |
| Standalone header values | 124/124: `fault=True queue=0 inflight=-` |
| Transport exception | 0 |
| Readiness true | 0 |
| Host motor commands | 0 |

Response timing tính từ host query tới RX, gán header đứng riêng cho query gần
nhất; không có transaction ID. Snapshot đầu irregular bị loại khỏi timing.

| Metric (124 samples) | Median | p95 nearest-rank | Max |
|---|---:|---:|---:|
| Query → header đầy đủ | 11.38 ms | 15.23 ms | 18.89 ms |
| Query → header + đủ node lines | 32.43 ms | 36.32 ms | 39.85 ms |

Đây là latency quan sát ở host của text response, **không phải motor latency**,
không đo node telemetry age, ESP-NOW loss hoặc packet delivery end-to-end.

## Trạng thái hệ robot quan sát cuối

```text
master: fault=True, queue=0, inflight=-
n1: OFF, state=-, homed=0, err=NONE, pos=0, target=0
n2: ON, IDLE, homed=0, err=NONE, pos=0, target=0
n3: ON, IDLE, homed=0, err=NONE, pos=0, target=0
```

- `err=NONE` khi n1 offline không có nghĩa node khỏe; master chưa có state.
- n1 cfg chưa đọc được.
- n2 cfg: min=2, max=30, homedir=0, maxhz=2000, accel=6000,
  homefast=800, homeslow=150, led=0.
- n3 cfg: min=3, max=30, các giá trị còn lại như n2.
- Neutral IK trả 12.857 cho cả ba node; phép tính này không kiểm tra readiness
  hoặc va chạm và không xác nhận neutral phù hợp rig.
- RX monitor có n2 BOOT reset=HARD_RESET; RX final query có n3 BOOT tương tự.
  Đây là báo cáo do master nhận; có thể có RX tồn đọng giữa các session.
  Chưa chứng minh reset xảy ra trong lúc polling, do mở serial hay do nguồn.
- Dòng FAULT bị ghép với STAT ở đầu session là bất thường framing cần giữ bằng
  chứng; chưa quy nguyên nhân. Gate vẫn chặn, không tự phục hồi header bị ghép.

## Regression và thay đổi project

Source master `print_status()` phát `state='-'` khi node chưa có state. Parser
bridge trước đó từ chối dòng này như malformed. Đã thêm regression dùng đúng
transcript thật: thất bại trước sửa, pass sau sửa regex chấp nhận `-`; readiness
vẫn false cho unknown/offline/unhomed. Không nới movement gate.

- Pi: **32/32 tests pass** trong scaffold audit.
- Windows: **23 pass, 9 Linux-specific skip**.
- Parser không thay đổi firmware, camera pipeline hay shadow emission.
- Pi production service vẫn active, PID 1912 ở final check.
- Final HTTP status healthy/capture_alive true, fps ~15.61 tại một mẫu,
  face_detected false, fallback `disabled-shadow-only`.
- Calibration SHA256 giữ nguyên
  `8782caf8391b6dd3e9f8321d09b818f537293bb7d571e95ed5a75b045ebb4a2f`.

## Artifacts

Pi directory: `/home/pi5/track-eye-integration-audit-20261008/`:

- `cable-port-revalidation-short.jsonl`: byte lỗi đầu mở, zero queries.
- `cable-port-revalidation-listen.json`, `cable-port-revalidation-prompt.json`.
- `new-cable-repl-inspect.json`, `new-cable-recovery.json`.
- `new-cable-readonly-queries.json`.
- `new-cable-status-125s.jsonl`, `new-cable-status-125s-summary.json`.
- `new-cable-final-queries.json`, `tests-new-cable.txt`.
- `new-cable-validation-report.json`: derived metrics, không thay raw evidence.

## Bước tiếp theo, chưa thực hiện

1. Kiểm tra nguồn, board và liên lạc node 1 với tác giả firmware; không gộp nó
   vào lỗi USB Pi/master đã qua được mẫu diagnostic.
2. Khoanh vùng báo boot lại n2/n3 và mất newline ở đầu session; đọc node logs/
   crash/reset reason nếu có quyền và source. Không auto-clear để che dấu lỗi.
3. Khi cả ba node online và nguồn ổn, mới xin phép home có giám sát.
4. Xác minh homed, neutral, workspace/rig signs và slot trước supervised motion.
5. Boot/reconnect và idle dài hơn vẫn là gate riêng; chưa gọi serial fully stable.
