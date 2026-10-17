# Audit protocol Pi5 ↔ master — 2026-10-08

Tier: project. Scope chỉ framing/parse/representation, không chuyển động, không
clear/home/reset/flash. Chủ ý tách lỗi robot downstream khỏi lỗi serial/parser.
Contract chi tiết: `PI5_MASTER_DATA_CONTRACT.md`.

## Phán quyết trước các phép đo bổ sung

> **Phán quyết cuối audit:** format/field/unit compatibility đã được đối chiếu;
> live steady-state corpus **3000/3000** pass và fd-reopen **5 sessions, 50/50**
> pass. Có thể chốt milestone "Pi/master hiểu đúng protocol và pass mẫu đo
> trong established raw-115200 session". **Không chốt production lifecycle/
> unplug-reset reliability, motor forwarding hoặc physical motion.**

- **Hiểu cùng format/ý nghĩa góc: có bằng chứng** từ source/PDF và 36 camera IK.
- **Ổn định vô điều kiện: chưa đủ bằng chứng**, đã thấy USB disconnect,
  UnicodeError/open-reconnect và merged diagnostic/reply.
- `look` payload timing/dispatch đọc từ source và test parser actual AST; chưa
  gửi live look thành công. Không gọi motor delivery hoàn thành.

## Baseline và stop rule

Baseline: 36/36 camera commands tại 2 Hz, ~20 s; prior status 124 clean snapshots
trong 125 s, một merged header bị loại. Host giữ raw 115200 khi đóng/mở, không
chủ động toggle DTR/RTS. Firmware không thay đổi; calibrated Pi state giữ nguyên.

Validation tool: `tools/delta_protocol_audit.py` với explicit JSON campaigns.
Budget: một soak 3000 unique-ish generated vectors ở 10 Hz, sau đó 5 reopen
sessions ×10 queries nếu soak pass. Dừng ngay on byte/protocol/timeout error;
không lặp reconnect để che lỗi. Không physically unplug/reset master khi chưa
được operator đồng ý; reopen chỉ fd close/open ở cùng device.

Các vector az gồm 0/90/180/270/360 và random decimals deterministic seed;
tilt 0..2°, twist=0 là trial đã duyệt ở bước trước. Không đại diện toàn workspace.
IK cùng parser góc với look nhưng không phát MOVE/ACK, không validate ms realtime.

## Lần 1 — strict host-double reference

Campaign `config/delta-protocol-audit.soak-20261008.json`:

- Planned 3000 queries/10 Hz; actual 27 queries, 26 verified, stop ~3.69 s.
- Query 27: `ik 154.142 0.054 0.000`.
- Master echo đúng polar; trả `(12.818, 12.854, 12.898)`.
- Host reference double `(12.818348830, 12.854511732, 12.898156997)`.
- n2 difference **0.000511732°**, vượt ngưỡng cũ 0.000501°.
- Không byte mismatch/disconnect trong artifact; đây là reference numerical
  comparison failure, không đủ bằng chứng lỗi wire decode.
- Trước failure 26 replies host-observed median ~37.27 ms, p95 ~42.89 ms,
  max ~43.14 ms. Không extrapolate thành 3000 pass.

## Khoanh vùng numerical failure

Tool local `tools/delta_float32_reference_probe.py` biến đổi AST IK source và round
operation/transcendental results về float32. Với query thất bại, kết quả model:

```text
float32 inputs: az=154.141998291, tilt=0.0540000014
model targets: 12.818365097, 12.854497910, 12.898138046
model .3f text: 12.818, 12.854, 12.898
```

Tái tạo đúng master text. Upstream ESP32 port source khai báo float implementation,
nhưng chỉ inspect upstream không xác minh build exact trên board. Vì vậy kết luận
là **phù hợp giả thuyết số học float32**, không “đã chứng minh nguyên nhân”.

## Lần 2 — tách echo accuracy khỏi IK numeric compatibility

Campaign `config/delta-protocol-audit.soak-numeric-20261008.json` giữ cùng seed,
rate/vector count; chỉ tolerance chẩn đoán reference đổi **0.001°**, một đơn vị
cuối master in `.3f`. Exact polar echo vẫn bắt buộc; duplicate/malformed/merged
reply không được repair; không nới readiness/bench tolerance.

Đây là numerical compatibility bound của phép đo, không motor accuracy, không
CRC/byte-loss guarantee. Nếu pass 3000 cũng chỉ chứng minh workload trong session
đó. Nếu fail, ghi failure và dừng; không tiếp tục nới bound.

Kết quả soak/reopen sẽ bổ sung sau khi tool trả về. Không được viện suite green
hoặc campaign planned để thay kết quả live chưa có.

## Lần 2 — kết quả và lỗi ở validator, không lẫn với wire corruption

- Actual **2482 sent / 2482 verified**, runtime ~249.25 s, không đủ 3000.
- Góc echo và node set khớp cho cả 2482; max IK-reference difference
  **0.000536836°** trong bound 0.001° chẩn đoán.
- Host response median **37.45 ms**, p95 **43.21 ms**, max **47.81 ms**.
- Tool dừng khi pre-TX drain thấy `ERR STOP...`, `FAULT...` và partial
  `WARN STOP tất c...` đang nằm trong byte buffer. Không có new IK outstanding.
- Inspect raw cho thấy pending UTF-8 diagnostic, không phải malformed IK echo,
  UnicodeError hay USB disconnect. Kernel cửa sổ kiểm tra không có entries mới.
- Validator đã giả định sai rằng chunk partial ngay trước TX là failure. Đã
  sửa project tool để chờ terminator trong deadline, không repair merged line.
  Regression chặn timeout/stale IK và chấp nhận fragmented UTF-8 diagnostic.

Không gọi attempt 2 hoàn thành hoặc lấy 2482 verified để che lỗi đo. Attempt 3
giữ corpus/tolerance, chỉ thay drain; budget một rerun rồi báo kết quả, không
thay firmware. Nếu attempt 3 pass mới chạy 5 reopen sessions; nếu fail dừng.

## Nhận xét kỹ thuật từ PDF so với source

PDF trang 8/14 khớp wire `look az tilt twist ms`, text lines, degrees, milliseconds,
115200, max 15 move commands/s. Trang 5 là ESP-NOW binary chỉ master↔nodes.
PC host sample 10 Hz ở trang 10 là cách chạy khác, không limit serial parser IK.

Source master có parser và shared look/ik path. Không nhận raw XY/JSON/EYES/20-byte
tracking codec. Invalid host format sẽ error chứ không magically map ra mắt.

Các điểm chưa đủ để gọi robust interface:

- UnicodeError không catch, reader buffer không bounded;
- no USB request ID/version/handshake/CRC và host-loss watchdog;
- extra tokens được bỏ qua, no strict finite numbers gate;
- IK print trước send_move/readiness; echo không phải node ACK;
- asynchronous UTF8 diagnostics có thể ghép control reply thực quan sát;
- native USB CDC assumption sai với hardware hiện là CH340 USB-UART;
- source/PDF setting drift (rehome tries, TX power) khiến cần version/checksum
  handshake chứ không chỉ tin tên file.

Các negative probes reader/argc lấy đúng AST source chạy local/Pi, không gửi
malformed bytes/oversized commands vào rig thật để gây crash.

## Authority của từng loại bằng chứng

| Evidence | Xác nhận được | Không xác nhận được |
|---|---|---|
| PDF trang 8/14 | Intended host text protocol, đơn vị, nhịp gửi khuyến nghị | Exact deployed revision hoặc transport stability |
| 4 file board backup khớp local | Source snapshot của master/IK/protocol/neutral tại thời điểm đọc | Firmware node hiện tại hoặc board không thay sau đó |
| Actual `handle_line` AST test | `look`/`ik` cùng angle parse, `ms` field, raw XY/JSON/EYES không phải lệnh | Board runtime trong every session |
| Actual `send_move` AST test | Payload `<Hiii`: ms + 3 signed millidegree targets, readiness gate chặn | RF bytes đã giao node, step/physical angle |
| Live typed IK echo | Master thực nhận và hiểu số góc gửi trong matched query | Duration của look, forwarding/ACK/motion |
| Double IK reference | Numerical compatibility với same source algorithm | Independent IK truth hoặc actual mechanical accuracy |
| Bounded session/reopen samples | Thực nghiệm dưới đúng conditions/config/corpus | Unplug/power-cycle unattended hoặc SLA dài ngày |

Không gộp các loại này thành một chữ “PASS end-to-end”.

## Host operational checks trong audit

Trong snapshot khoảng 17:55, serial-getty@ttyUSB0 inactive; ModemManager không
installed; không thấy brltty/getty giữ cổng. Chỉ audit worker đang chạy serial.
Đây là snapshot, không loại trừ transient process/driver effect ở lần reconnect cũ.
Host tty được đọc raw 115200 8N1, -hupcl, -crtscts; no hardware modem-line
waveform measurement. Không dùng các quan sát đó để tuyên bố DTR/RTS không đổi.

## Lần 3 — corpus hoàn thành sau validator drain fix

Campaign vẫn 3000 vectors deterministic, 10 Hz, twist=0, tilt 0..2°,
reference comparison 0.001°. Không đổi firmware hoặc Pi output calibration.

- Duration **300.99 s**, actual **3000 sent / 3000 verified replies**.
- Exact polar echo + expected node set **3000/3000**.
- No protocol failures/timeouts/invalid UTF-8/merged IK trong corpus.
- Max host-double target discrepancy **0.000536836°**; đây là numerical
  compatibility, không actual motor accuracy.
- Host audit timing (gồm validation overhead): median **37.35 ms**, p95
  **43.04 ms**, max **51.73 ms**.
- Robot diagnostics trong corpus có n2 BOOT/HARD_RESET, FAULT, n2 OFFLINE.
  Được ghi riêng; master vẫn parse/tính IK và không host motion command.
- Cần 2 status sync queries: header đầu ghép FAULT nên bị loại; header độc lập
  tiếp theo đầy đủ. Không repair merged frame và không gọi initial framing sạch.

## Reopen fd — 5 session, không reset/rút cáp

Campaign `config/delta-protocol-audit.reopen-numeric-20261008.json`:

- **5/5 sessions**, mỗi session **10/10 replies**, tổng **50/50**.
- Giữa session đóng fd, chờ 1 s, mở cùng by-path; baud raw 115200 được giữ.
- Không restore baud cũ, không chủ động toggle reset lines, không physically
  unplug hay board reset. Không gọi đây là boot/reconnect acceptance.
- No protocol failures; max reference discrepancy **0.000496830°**.
- Host audit timing median **36.90 ms**, p95 **42.80 ms**, max **43.10 ms**.
- Robot status vẫn fault=True; đây là proof calculation-only khi downstream fault.

## Replay raw bytes (không tin trực tiếp `match=true`)

Đã ghép mọi `rx_hex`/`unsolicited_rx_hex` theo session, split newline rồi decode
UTF-8 strict. Gán từng standalone IK cho outstanding query duy nhất, so lại
polar, expected node IDs và source reference. Không dùng field `match` của tool
để tính pass. Reference math vẫn cùng source, không phải independent IK truth.

| Item | Steady-state | Reopen |
|---|---:|---:|
| Query/reply được raw replay match | 3000/3000 | 50/50 |
| Pending query ở cuối | 0 | 0 |
| Dang dở RX ở cuối | 0 | 0 |
| Mismatched echo/node/numeric | 0 | 0 |
| RX-line latency median | 37.08 ms | 36.61 ms |
| RX-line latency p95 | 42.72 ms | 42.61 ms |
| RX-line latency max | 49.19 ms | 42.87 ms |
| TX period median | ~100.00 ms | ~100.01 ms |

Observed soak mean rate **10.0000004 Hz**. Individual host TX intervals
**95.47..104.66 ms** do scheduler/timing jitter; không khẳng định đúng 100 ms mọi
lần hoặc latency vật lý. Reply không có transaction ID, nên measurement chỉ có
ý nghĩa do audit giữ một query outstanding và explicit angle echo.

Raw SHA256:

- `protocol-soak-framed-3000.jsonl`:
  `ceba67431e041da14e5468b770ba5b62b7f23e2a0899965e34bf882452de251c`.
- `protocol-reopen-5x10.jsonl`:
  `e053529d67d99080f85b19c811fd64c82def3de16465ca0ceed01b222613c2d5`.

Pi audit dir giữ original artifacts/campaigns/source. Derived raw replay report:
`protocol-independent-raw-audit.json`. Local copies ở approved temp OpenCode.
Lần cuối kernel since 17:38 không có new entries; tty CH340 vẫn enumerate.
Camera health HTTP 200, calibration checksum `8782caf...` như trước. Không thay
systemd runtime, không flash firmware hay clear/home/look trong audit này.

Final reproducibility check: **36 scaffold/campaign/reference files** matched
local/Pi SHA256. Raw artifact hashes matched both copies. Scaffold **59/59 tests
pass on Pi**, Windows **50 pass + 9 Linux-specific skip**; production Pi suite
**47/47 pass**. Changed source paths covered by actual parser/reader/forwarding
AST tests and negative protocol/drain tests, not chỉ happy-path green suite.

## Đề xuất chốt và phần còn thiếu

1. **Chốt format đúng:** adapter dùng text ASCII `look az tilt twist ms\n`, degrees,
   integer milliseconds, USB-UART 115200. Master có parser matching; không gửi
   raw XY/JSON/EYES/20-byte codec nếu chưa thay firmware.
2. **Chốt bounded session evidence:** 3000/3000 steady-state + 50/50 fd-reopen pass,
   có raw logs/replay. Không chốt blanket stability hoặc long-run SLA.
3. **Chưa chốt lifecycle robust:** fresh attach/reset/rút cáp từng có UnicodeError
   và USB losses, chưa có safe automatic session recovery. Nên phối hợp tác giả
   minimal reader/framing/handshake patch và bench-test riêng.
4. **Tạm tách downstream:** node readiness/ESP-NOW/motor cần gate khác. Protocol
   calculation-only pass không chứng minh live look duration/packet/ACK chain.
5. Giữ một serial owner/worker lâu dài thay việc probe mở/đóng liên tục; disarm
   khi reconnect, parse typed/bounded replies, log states; không auto-clear robot.

Proposal firmware change chưa được triển khai. Handoff template:
`DELTA_FIRMWARE_INTERFACE_HANDOFF.md`. Checklist: `PI5_MASTER_ACCEPTANCE_CHECKLIST.md`.
