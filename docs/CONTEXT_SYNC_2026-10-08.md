# Context checkpoint đã lưu/sync — 2026-10-08

Tier **project**; chỉ context/tài liệu/instruction pointer, không rollout runtime.
Sync chính lúc **2026-10-08 18:20:19 +07** (`20261008T112019Z`).

## Điểm đọc cho phiên sau

- Local `AGENTS.md` → `docs/PROJECT_CONTEXT.md` → `docs/HANDOFF_CURRENT.md`.
- Contract/audit: `PI5_MASTER_DATA_CONTRACT.md`,
  `PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`.
- Kết luận owner tạm chốt: matching semantics + bounded transmission evidence
  (3000/3000 IK, 5 fd-reopen sessions 50/50). Không lifecycle/24-7/motor approval.
- Local legacy context được giữ ở `LOCAL_LEGACY_CONTEXT_2026-10-08.md`.

## Các nơi lưu

1. Repo local: root `AGENTS.md` và curated `docs/`.
2. Pi canonical docs: `/home/pi5/track-eye/docs/`, để agent/operator tìm được.
3. Pi audit docs: `/home/pi5/track-eye-integration-audit-20261008/docs/`.
4. Pi `AGENTS.md` hiện hữu được thêm October checkpoint pointer, **không overwrite**
   bằng root local AGENTS. Audit `AGENTS.md` giữ bản local phù hợp prototype.
5. Pi các docs `HANDOFF_STATE`, `PROJECT_FRAMEWORK`, `PI5_DEPLOYED_STATE`,
   `OPEN_RESEARCH_PROTOCOL_FALLBACK` chỉ thêm notice mới, nội dung cũ giữ nguyên.

## Xác minh

- Bundle chính: 13 local files (AGENTS + 12 context docs), mọi bản context doc
  local/canonical-Pi/audit-Pi khớp SHA256; Pi AGENTS giữ riêng nội dung baseline.
- 30 affected Pi paths được backup/verify trong sync chính.
- Backup:
  `/home/pi5/track-eye-integration-audit-20261008/context-sync/20261008T112019Z/backup/`.
- Report/manifest:
  `/home/pi5/track-eye-integration-audit-20261008/context-sync-latest.json`.
- Report copy local ở approved temp OpenCode:
  `track-eye-context-sync-report-20261008.json`.
- Package SHA256:
  `3ce87b9f6adb0e4edab272425547ba6f1fcee518d00e6e368d9382276b9c1d95`.
- Historical-content preservation: 5 checked documents giữ nguyên phần cũ.
- **17 runtime/state/model/unit files** hash before/after giữ nguyên.
- Post-sync: service active, PID 1912, restart counter không đổi (11), health 200,
  fallback `disabled-shadow-only`, body selection false, không serial process owner.
- Không restart service, không hardware/serial commands, không flash, không
  thay calibration/config/production source. Không commit/push hoặc bật emission.

File receipt này được lưu local và sync thêm vào cả hai Pi docs directories sau
bundle chính; không tự đưa receipts/logs vào instruction hoặc acceptance evidence.

Git changes vẫn là working-tree chưa commit; đây là filesystem/SSH checkpoint,
không phải Git release hay backup remote repository.
