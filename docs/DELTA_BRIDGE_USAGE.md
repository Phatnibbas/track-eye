# Dùng khung Delta bridge hiện tại

> Generation3 update 2026-10-14: use `delta_v3_validate.py` (status/IK only) and
> explicit operator-approved `delta_v3_camera_trial.py` for the current six-node
> board. Read `DELTA_V3_USB_CONTRACT_2026-10-14.md` and
> `DELTA_V3_VALIDATION_2026-10-14.md` first. Legacy tools/ACK gates below are v1.
> No persistent sender has been enabled; do not rerun neutral by implication.

Khung cấp project, độc lập production runtime. Không có continuous motion sender.
Có one-shot `delta_neutral_bench.py` riêng, yêu cầu operator approval và readiness;
run đã duyệt bị chặn trước clear/look do offline nodes. Các protocol audit/IK
tools không phát chuyển động. Không sửa `firmware/main.py` hoặc calibration Pi.

## Cấu hình

Hai template không runnable cho tới khi điền đủ giá trị:

- `config/delta-monitor.template.json`: chỉ diagnostics/read-only, không cần chọn slot.
- `config/delta-bridge.template.json`: HTTP dry-run + explicit rig mapping.

Sao chép thành file audit riêng. Không tự điền dấu trục/gain/slot từ ví dụ test.
`baud` phải đúng UART firmware; USB identity và node IDs lấy từ board/protocol được
xác minh. Các timeout/poll-rate/line bound là tham số thí nghiệm phải ghi lại.
Mapping góc phải đối chiếu workspace/va chạm; loader chỉ kiểm tra cấu trúc số,
**không chứng nhận cơ khí an toàn**.

## Chạy trên Linux/Pi khi USB đã enumerate ổn định

```bash
python3 tools/delta_master_monitor.py \
  --config /path/to/verified-monitor.json \
  --seconds 60 --out /path/to/new-readonly-log.jsonl
```

Tool nghe trước, gửi chỉ `status`, log raw hex và lines; gặp REPL, traceback,
UTF-8 lỗi hoặc disconnect thì dừng/quarantine. Không auto-clear/home/reset/reconnect.
`status_ready` là full fresh snapshot của các node đã khai báo, không phải rig approval.

HTTP dry-run không mở serial:

```bash
python3 tools/delta_bridge_dry_run.py \
  --config /path/to/explicit-dry-run.json \
  --seconds 10 --out /path/to/new-target-proposals.jsonl
```

`ProposalPlanner` là thư viện chưa nối vào CLI này: CLI quan sát production output,
planner test cơ chế phối hợp target/master/freshness trước emitter. Không nhầm
command string trong log với command đã gửi board.

## Tests

```bash
python3 -m unittest discover -s tests -p 'test_delta*.py' -v
```

PTY tests chạy Linux, không chạm device thật. Các con số trong fixture là dữ liệu
giả có chủ đích; không được deploy làm config. Windows skip tests phụ thuộc termios.

## Non-motion protocol audit

Contract: `docs/PI5_MASTER_DATA_CONTRACT.md`; evidence/campaign decisions:
`docs/PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`.

```bash
python3 tools/delta_protocol_audit.py \
  --config /path/to/read-only-monitor-config.json \
  --campaign /path/to/explicit-audit-campaign.json \
  --reference-dir /path/to/inspected-firmware-backup \
  --out /path/to/new-raw-log.jsonl --summary /path/to/new-summary.json
```

Chỉ status + typed ik. Faulted nodes không cấm computation-only test, nhưng không
được chuyển kết quả đó thành motion permission. Script dừng session khi echo sai,
reply merged, timeout, invalid bytes/REPL; bounded diagnostic drain không repair
frame. Reference cùng source IK chỉ numerical compatibility, không independent
physical verification. Đóng/mở fd không tương đương power-cycle hay rút cáp thật.

## Board diagnostics và recovery

Các tool `delta_serial_probe.py`, `delta_repl_inspect.py`, `delta_reader_experiment.py`
là thao tác audit chuyên biệt; phải đọc help/source trước dùng. REPL tools chỉ dùng
sau xác nhận master không chạy. Recovery gọi `main()` trong RAM với auto-rehome tắt
trong RAM, không persist và không phải quy trình restart production. Sau disconnect,
trạng thái board phải xác minh lại; không replay command recovery hoặc motion.
