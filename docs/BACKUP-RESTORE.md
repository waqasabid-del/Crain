# Backup and restore

**Status: the restore has been rehearsed locally and nowhere else.** That is a
smaller claim than it sounds and a larger one than what came before it, which
was nothing. A backup nobody has restored from is a hypothesis; this document
records the one restore that has actually been performed, exactly how to repeat
it, and — at the end, at length — what production still has to arrange.

---

## The one command

```bash
./scripts/restore-rehearsal.sh
```

It dumps the local development database, restores it into a **separate**
database called `cairn_restore_rehearsal`, and then verifies the copy. It exits
non-zero if the copy cannot be believed.

Verbatim, on a developer machine (Windows 11, Docker Desktop, PostgreSQL 16 in
the `cairn-postgres` container, a seeded development database):

```
2026-08-17 02:10:13 [info     ] backup.dumped     bytes=155106 database=cairn seconds=1.26
2026-08-17 02:10:19 [info     ] backup.restored   database=cairn_restore_rehearsal seconds=4.17
source        cairn
restored into cairn_restore_rehearsal
dump          C:\Users\raiwa\AppData\Local\Temp\cairn-backups\cairn-1786914611.sql (155,106 bytes)
dump took     1.3s
restore took  4.2s

  [ok] alembic revision: b1e6c4a92f37 (source b1e6c4a92f37)
  [ok] rows in tenants: 11 (source 11)
  [ok] rows in users: 5 (source 5)
  [ok] rows in memberships: 5 (source 5)
  [ok] rows in webhook_deliveries: 3 (source 3)
  [ok] rows in facts: 9 (source 9)
  [ok] rows in briefs: 41 (source 41)
  [ok] rows in internal_audit_log: 0 (source 0)
  [ok] sample workspace: round-tripped intact

VERIFIED: the restore holds the source's schema and data.

real    0m10.055s
```

**Ten seconds end to end on 155 KB.** That number is useful only as a shape: it
says the mechanism works, not how long production will take. Restore time on a
logical dump scales with row count and index rebuilds, not with file size, and
the development database has four figures of rows where production would have
seven. Do not quote ten seconds to anybody.

Other entry points:

```bash
make backup                # a dump, no restore
make restore-rehearsal     # the same as the script above
pnpm ops:restore-rehearsal # the same, from the repository root

./scripts/restore-rehearsal.sh --target cairn_restore_2026_08   # a named copy
./scripts/backup.sh --dump /tmp/cairn.sql                       # a chosen path
```

Exit codes are meant for a scheduler:

| Code | Meaning                                                               |
| ---- | --------------------------------------------------------------------- |
| 0    | The backup restored and verified.                                     |
| 1    | The restore completed and did **not** verify. Do not rely on it.      |
| 2    | Refused — a production-looking name, or the source as its own target. |

---

## What "verified" means

`psql` exits zero on an empty file. It will restore nothing, print nothing, and
report success. Every "restore completed" message is true and the database has
no tables in it. So the exit code is not evidence, and the verifier asks three
independent questions instead:

1. **Is it the same schema?** `alembic_version.version_num` in the copy must
   equal the source's. A restore one migration behind accepts writes and then
   fails on the first column it does not have.
2. **Is the data there?** Row counts on `tenants`, `users`, `memberships`,
   `webhook_deliveries`, `facts`, `briefs` and `internal_audit_log`, compared
   against the source. Not every table — a check that fails on any schema change
   is one that gets deleted — but a spread across tenancy, identity, ingestion,
   the understanding layer, and the audit log whose loss would be the most
   serious.
3. **Does a real query return the expected answer?** One workspace is chosen
   from the source and looked up in the copy by primary key, then compared field
   by field. Counts can be right while the rows are wrong: a schema restored
   over yesterday's data has the right shape and the wrong contents.

**All three must pass.** `Verification.ok` is false for an empty check list as
well, because `all([])` is `True` and a verifier that ran nothing would
otherwise report success — which is the exact shape of the failure this whole
exercise is about.

The verifier is tested in the direction that can fail
(`apps/api/tests/test_backup_restore.py`): one test restores an **empty dump**
and asserts the verification fails; another **truncates a dump at the first
`COPY`**, so the schema restores and the data does not, and asserts the row
counts catch it. A verifier that only passes on the happy path is worthless.

---

## The two refusals

Both are checked before anything is created or dropped.

**It will not touch a database whose name suggests production** — anything
matching `prod`, `live` or `customer`, case-insensitively, as either the source
or the target. Dumping production is a legitimate operation and is not this
tool's: managed backups take a snapshot without a client connection and without
a developer's laptop in the path. This rehearses the _restore_, which is the
half nobody tests.

**It will not restore over its own source.** One transposed argument would
otherwise overwrite the database being rehearsed for with a copy of that
database as it was an hour ago.

There is also a positive requirement: the target's name must contain `restore`
or `rehearsal`. An operator who finds `cairn_restore_rehearsal` on a server
knows what it is and that it can be dropped. One who finds `cairn2` does not,
and leaves it there for a year.

---

## What this is not

**This is a logical dump, not point-in-time recovery.** It restores the database
as it was when `pg_dump` started. Everything between that moment and the
incident is gone. For a nightly dump, the worst case is twenty-four hours of
lost work — for CAIRN that means facts, briefs, corrections and consent
decisions a customer made and would have to make again.

**It does not cover anything outside PostgreSQL.** Not the Pub/Sub backlog, not
in-flight jobs, not the model provider's state, not secrets. A restored database
plus an empty queue is a system that has forgotten every job that was waiting.

**It is not encrypted, and the dump file is not managed.** The file lands in the
operating system's temporary directory — deliberately outside the repository, so
a complete copy of every row cannot end up in a commit — and nothing rotates,
expires or encrypts it. Delete it when you are done.

**It has not been run against production, or staging, or any database holding
customer data.** Nothing in CAIRN has. Everything above was measured on a
development machine against seeded data.

---

## What production still has to arrange

In rough order of what would hurt most by its absence. None of this is done.

**Managed backups with point-in-time recovery.** Cloud SQL automated backups
plus WAL archiving, so recovery is to a chosen second rather than to the last
dump. This script does not replace that and should not be scheduled as if it
did; its job in production is to _rehearse_, on a copy, that what the provider
stored can actually be read back.

**A retention schedule somebody agreed to.** How many daily backups, how many
weekly, how long the WAL is kept — and therefore how far back recovery can
reach. An unwritten retention policy is whatever the provider's default happens
to be, discovered during the incident.

**Offsite and cross-region copies.** A backup in the same project as the
database it protects survives a table drop and not an account compromise or a
region failure.

**Encryption at rest, with a key that is not in the same blast radius.**
Customer-managed keys, and a documented answer to who can decrypt a backup and
who can authorise it.

**Restore rehearsals on a schedule, against a production-sized copy.** Monthly,
into a scratch instance, with the verification above and the elapsed time
recorded. The number that matters is not "does it restore" but "how long does it
take on real data" — because that is the recovery time objective, and until it
has been measured once, there is no RTO, only a hope.

**An RPO and an RTO written down**, and the alerting to notice when a backup did
not run at all. A backup job that has been failing silently for three weeks is
the most common way this whole area fails.

**Access control on the restore path.** Who may run a restore, into what, and
what is recorded when they do. A restore is a bulk read of every customer's
data; md/15 §5.2 governs staff reading one workspace's facts, and it would be
strange for the path that reads all of them to be governed by less.
