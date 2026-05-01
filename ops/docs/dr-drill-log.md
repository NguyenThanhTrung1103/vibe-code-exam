# DR Drill Log

Each row records one executed disaster-recovery drill. Internal-beta
gate (Gate A) requires at least one entry. Public soft-launch gate
(Gate B) requires the most recent entry to be ≤ 30 days old.

| Date (UTC) | Operator | Snapshot | Target DB | RTO | Outcome | Notes |
|------------|----------|----------|-----------|-----|---------|-------|
| 2026-04-30T12:48Z | claude (P10 unattended) | local dump (no off-site repo configured) | `exam_platform_db_drill` | < 5 min | ✅ pass | local-only drill on LXC; dump → restore → table counts → drop. See `plans/reports/phase-10-260430-1300-completion.md` §5. |

## How to add an entry

After running the drill (`ops/backup/restic-restore.sh`), append a row
with:

- **Date** in UTC (`date -u --iso-8601=minutes`).
- **Operator** = whoever ran the drill.
- **Snapshot** = restic snapshot id, or `local dump <filename>`.
- **Target DB** = drill database used.
- **RTO** = wall-clock time from `restic-restore.sh` start to "drill OK".
- **Outcome** = ✅ pass / ⚠️ partial / ❌ fail.
- **Notes** = anything that surprised you, including disk usage,
  warning messages from `pg_restore`, or schema drift discovered.

## Quarterly cross-network drill (Gate B prep)

Before public soft-launch, run **at least one** drill from a host that
is NOT the production LXC. Confirms:

1. The restic password is retrievable from the secondary vault.
2. The off-site repo can be read from a different network egress.
3. The dump restores cleanly into a fresh PG 14 cluster.
