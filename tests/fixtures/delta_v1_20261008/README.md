# Historical generation-1 test reference (archive tier)

Snapshot preserved from Pi audit `firmware/` on 2026-10-14; that directory holds
the board source/neutral read on 2026-10-08. Tests here cover legacy tools only.
Never deploy these files or use their gates to certify the generation-3 board.

SHA256:

- main.py: `574028a015dc73ae87946b7913db759e0aa264d36b833d87cf67af5af6190055`
- spm_ik.py: `004a201260935a6693e7523292adb47369c257e2290a88a1bf156cdc6d52166d`
- neutral.txt: `4464af2e4e63e47e968c7dba70fc14d62a3157f6cf0a5f4ba4d2f81a9baaa763`

Canonical `firmware/` was replaced by the owner's v3 source; v3 tests must use
that source and their own explicitly labeled fixtures/live board state.
