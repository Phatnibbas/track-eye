# Handoff hiện hành — checkpoint 2026-10-14

## Current native-ROI acquisition — 2026-10-17

Start with `PI5_DEPLOYED_STATE.md`. Production is pre-upgrade`b8387c0` plus
diagnostic UI and selected full-range ROI acquisition/reacquisition. One native
crop/full-frame FaceMesh call; landmarks return to original pixels before
unchanged aperture-v1 math. FACE fallback remains independent of pupil failure.
The0.6s reference is geometric association, not identity. No model/threshold,
mapping-unit/calibration, head/body gate, visitor pipeline or sender-policy change.

Web separates pre-EMA, raw-after-EMA and tuned output. Local175/Pi34 focused
tests and actual-model cold/warm/loss replay pass; controlled small-photo
acquisition improved, not measured2m or pupil-direction acceptance. Aperture-v1
vertical sensitivity remains: smaller lid aperture amplifies vertical signal.

Camera PID136647 and sender PID146887 active, saved tuning clean3.9/3/3.45/3.7,
limit1.0, two neutrals, pin2f797a4c… preserved. Initially offline nodes later
returned; obtained a new complete clean snapshot after a BOOT-merged header.
Existing sender policy issued one acknowledged bounded CLEAR after startup
FAULT rejection; completed360/360 echo session, then fresh node-position feedback.
Final resumed session307/307 echoes, no rejection/CLEAR. No HOME/reset/flash.
Temporary validation token/drop-in removed. RAM/owner-test/reboot limits remain;
read fresh state rather than restoring any historical dirty/stopped paragraph.

## Current continuous sender — overrides bounded-only restrictions below

**Newest owner output policy:** 5LOOK/s max; old2° tilt×10 capped15°;
angular direction deadband1° AFTER scale/cap, compare last wire target. Not1XY.
Explicit robot-error CLEAR enabled with5s cooldown,max3 consecutive andOK CLEAR;
no CLEAR on geometry/USB/REPL, no HOME/reset. Same owner observe-only node policy.
Sender running observed229/229 LOOK; maxwire tilt15°, minimumTX202ms.
Report `DELTA_OUTPUT_SCALE_2026-10-14.md` overrides earlier15Hz/no-clear text.

**Latest override wins over the prior final-condition paragraph below:** owner
explicitly authorized host LOOK despite node readiness errors for Pi↔master test.
Live profile `observe-only-owner-test`, node diagnostics/rejections logged only;
firmware gates untouched, no clear/home/reset. Sender PID11947 running, snapshot
632/632 echoes; raw completed transactions255/255 checked. Source/freshness and
USB/parser quarantine still enforced; no motor completion claim. Old fault latches
preserved, not lost. Autostart remains enabled; head branch remains sign-gated.

**Final condition:** `track-eye-delta.service` enabled/active but FAULT_LATCHED,
no output TX. Final corrected session251/251 LOOK then ERR n4 OFFLINE.
Manual resume approved conditionally on fresh clean gates; validation observed
n6 BOOT fw3 reset=POWER_ON + incomplete FAULT and failed before any TX.
No latch deletion/restart/resume/clear/home after that failure. Preserve evidence.

Owner approved shared output mean50/50 XY, remaining eye, head then face fallback,
15 Hz target scheduling/autostart; no separate neutral approach. Deployed new
`track-eye-delta.service` enabled/running from `/home/pi5/track-eye-delta/`.
First actual live target 3000 ms, subsequent 500 ms/slew-limited/latest-only.
Read `DELTA_CONTINUOUS_2026-10-14.md` before legacy trial evidence below.

Head branch **not active** because Pi head axis/sign still unvalidated; respect
that gate. Face and mean/single-eye branches observed live. 1215/1215 LOOK raw
echo matches in sampled session, 877 means recomputed from two live eye outputs;
active TX median69.75ms (~14.3Hz), config15Hz. No-source keeps worker alive/no TX.
Production internal fallback still shadow-only but external adapter now emits.

Status `/home/pi5/track-eye-delta/state/status.json`; fault latch and rotating
raw logs beside it. Fault latch needs manual diagnosis, not delete/recover loop.
No auto-clear/home/reset/flash, no body or stale shadow HELD output. Service
stopping halts TX, not motor STOP. Current approval allows continuous daemon;
do not silently revert to single-eye routing or finite20s. Reboot after install
not verified; earlier USB reader failures remain lifecycle risk.

## Current v3 checkpoint — đọc trước baseline 08/10 phía dưới

- Actual `firmware/main.py` master3, `proto3.py`, `spm_ik.py` đã đọc đủ và khớp
  board byte-for-byte. 6 nodes/2 Delta, neutral3 hai mắt 15/15/15, eyes.txt=12.
- Owner chốt robot master↔node chạy; output mode được owner chọn riêng:
  **display-left → cả 2 Delta**, common gaze, không average hai mắt.
- Protocol hiện `look az tilt twist ms\n` và calculation-only `ik`.
  No USB OK MOVE/ACK, no independent 2-eye target command. Status header
  `fault=... eyes=1+2 verg=...`; legacy queue/inflight gates không dùng.
- Initial fresh attach/open observed UnicodeError `sys.stdin.read(1)`→REPL;
  source reader chưa sửa. Owner duyệt RAM recovery: auto-home/rehome tắt và
  restored-target resend no-op, không flash/reset/clear/home. Reset mất RAM policy.
- Established RAM-recovered session: **3000/3000 generated IK +18/18 camera IK**,
  raw replay pass. Numeric diff max 0.000531333°, comparison bound 0.001°.
- Owner duyệt neutral approach từ 1.993→15° trong 3000 ms, rồi trial camera 2°.
  **1 neutral +2 camera LOOK** gửi và matched echoes; node-reported IDLE 14.995°
  sau neutral. Owner thấy cả hai Delta có chạy, không xác nhận đúng hướng.
- Trial camera tự disarm/stop TX sau 10.60 s tổng vì camera trở thành unusable
  sau IK; không đủ 20 s budget. **Không gửi STOP**, last move hoàn tất/giữ target.
- Post-trial check 6 nodes ONLINE/IDLE/homed/error-free, positions pairs:
  (n1,n4)=15.300; (n2,n5)=14.464; (n3,n6)=15.252 degrees. Không replay current
  target/neutral hoặc suy fresh state từ checkpoint này. Không serial daemon.
- Current Pi calibration `47cfed0f...` (full hash trong PROJECT_CONTEXT),
  gain 3/3/2.5/3.75, no saved neutrals. Không restore historical calibration.
- Docs current: `DELTA_V3_USB_CONTRACT_2026-10-14.md`,
  `DELTA_V3_VALIDATION_2026-10-14.md`. Evidence:
  `/home/pi5/track-eye-integration-audit-20261008/v3-validation-20261014/204814/`;
  source/tools/config/tests workcopy isolated, production unchanged.
- New tool `tools/delta_v3_validate.py` calculation-only;
  `tools/delta_v3_camera_trial.py` explicit operator flags + config + gates;
  `config/delta-v3-neutral-approved-20261014.json` applies to approved trial only,
  not permission to execute neutral automatically next session.
- Remaining: controlled face-in-frame trial/direction, author-coordinated bounded
  byte reader + lifecycle/handshake + host watchdog before persistent deployment.

## Historical v1 handoff — 2026-10-08

The remaining content records prior evidence/authorization, not current live
6-node state or fresh permission to clear/home/move. Current findings above win.

## Quyết định owner

Tạm chốt Pi5↔ESP32 master trước; lỗi robot downstream xử lý sau. Chốt trong giới
hạn bằng chứng, không overclaim, không hardcode rig settings. Owner yêu cầu lưu
và sync context; đây là checkpoint tài liệu, không triển khai output production.

## Trạng thái có thể bàn giao

| Phần | Phán quyết |
|---|---|
| Format/field/unit compatibility | Đã đối chiếu PDF, actual source/board backup và live echo |
| Camera display-left→master IK | 36/36 verified, trial mapping; chưa label physical direction |
| Established-session serial/parse | 3000/3000 IK ở ~10 Hz/~301 s, raw replay pass |
| FD reopen cùng thiết bị/baud | 5 sessions ×10 queries, 50/50 pass |
| Physical unplug/boot/reset/24-7 | Chưa chốt; từng có disconnect/UnicodeError/merged reply |
| Live LOOK/MOVE/ACK/robot motion | Chưa pass; approved neutral blocked trước clear/look |
| Production camera/fallback | Giữ nguyên; fallback shadow-only, không serial emission |

Raw-line response latency final soak: median 37.08 ms, p95 42.72 ms, max 49.19 ms.
Đó là response parser/IK nhìn từ host, không motor latency. Max same-source
reference discrepancy 0.000536836°, dùng numerical audit tolerance 0.001°.

## Các đường dẫn cần biết

- Source thay đổi tiếp: repo local hiện tại, `delta_bridge/`, `tools/delta_*.py`, tests/config.
- Pi deployed production: `/home/pi5/track-eye`, package `track_eye/`, không Git.
- Pi prototype/evidence: `/home/pi5/track-eye-integration-audit-20261008/`.
- SSH: `pi5@pi5.local`; không lưu mật khẩu trong repo/context.
- Camera by-id: UGREEN `usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0`.
- Serial last observed by-path:
  `/dev/serial/by-path/platform-xhci-hcd.0-usb-0:1:1.0-port0`.
  Re-enumerate mỗi lần; CH340 không unique serial ID, path chỉ pin cổng.
- Canonical docs: `PROJECT_CONTEXT.md`, `PI5_MASTER_DATA_CONTRACT.md`,
  `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`, `PI5_MASTER_ACCEPTANCE_CHECKLIST.md`.
- Proposal/handoff: `PI5_DELTA_INTEGRATION_PLAN.md`, `DELTA_FIRMWARE_INTERFACE_HANDOFF.md`.

## Những gì không được quên

1. Pi runtime mới hơn tree local legacy. Không deploy legacy pupil_spike/UDP lên Pi.
2. Master hiện parse text `look az tilt twist ms\n`, degrees/integer ms. Typed `ik`
   cùng angle parser nhưng không motor dispatch; `IK` không có nghĩa `OK MOVE`.
3. JSON/raw XY/EYES/20-byte tracking codec không có matching USB decoder hiện tại.
4. Display-left owner chọn; trial 2° signs/offset chưa rig calibration.
5. Last robot sample sau bench: FAULT, n1/n3 OFF/unhomed, n2 ON/homed.
   Không re-query/clear/move khi chỉ save context; đọc mới trước hardware work.
6. RAM recovery từng đặt AUTO_REHOME=false; flash vẫn true. Không suy trạng thái
   RAM hiện tại hoặc an toàn sau reset từ log cũ.
7. Preserve output-calibration SHA256
   `8782caf8391b6dd3e9f8321d09b818f537293bb7d571e95ed5a75b045ebb4a2f`;
   production fallback config SHA256
   `76345b7d2b9318a736d58e530583c7f1a45601900c1c6503c605a9025dce8144`.
8. Main/IK/neutral board backup hashes và failed experiment logs nằm trong audit.
   Preserve evidence; không promote raw log/session transcript thành instructions.

## Bước kế sau checkpoint

Đọc contract/audit; xác minh live identity/state; chọn công việc tách biệt:
**host session lifecycle** hoặc **node/mechanics readiness**. Thỏa thuận với tác
giả firmware về byte-reader bounded, newline/version/request ID/freshness watchdog
trước unattended deployment. Không tự đổi protocol, flash, auto-clear hoặc enable
continuous motion chỉ vì owner đã tạm chốt parser proof.

## Save/sync scope

Context ở local docs và cả Pi canonical docs/audit docs; thêm pointer vào Pi
instruction/historical framework mà giữ nội dung cũ với backup. Sync tài liệu
không import new runtime hoặc thay calibration/service/firmware. Không có commit
hoặc push tự động được yêu cầu trong checkpoint này.
