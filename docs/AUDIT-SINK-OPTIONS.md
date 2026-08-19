# The audit sink: options for the one gate that is ours and unstarted

**A decision note, not an implementation.** 2026-08-19, AI/infrastructure track.

## Where it stands

The internal audit log is a hash chain inside the application database
(`internal/support.py` and its models): every entry carries the hash of its
predecessor, so an edit or a deletion in the middle breaks the chain visibly.
That makes it **tamper-evident, not tamper-proof** — an attacker with
database-owner access deletes the whole table and the chain with it, and the
absence of a log is not a broken chain. For exactly this reason the
"customer-verifiable audit log" claim is embargoed (md/16 Step 28), and the
`audit-sink` release gate has blocked since it was written.

The fix is structural, not clever: a copy of the chain must live somewhere the
people who operate this database cannot write, and preferably cannot delete.

## The options

### 1. A second PostgreSQL instance with INSERT-only grants — recommended

A `cairn_audit` database (locally: one more service in `docker-compose.yml`;
later: the host's second managed instance) holding one table, with the
application role granted `INSERT` and nothing else — no `UPDATE`, no `DELETE`,
no `TRUNCATE`, no DDL. A worker maintenance pass replicates new chain entries;
verification is a `SELECT` comparing chains.

- **Effort:** small. The compose service is a copy of the existing one, the
  migration is one table, the replication pass is the maintenance-loop idiom
  used four times already, and the grant test is the same shape as the
  existing grant allow-list test.
- **Trust gained:** an application-role compromise cannot rewrite history at
  all, and a primary-database-owner compromise can no longer erase it — the
  attacker needs both instances' owners. Honest limit: whoever owns the second
  instance can still delete; this is a second lock, not a vault.
- **Survives the host move:** it is just Postgres. On Render it becomes a
  second managed instance; nothing in the code changes but a URL.

### 2. Append-only file sink with periodic hash anchoring

Chain entries appended to a local file; the head hash periodically "anchored"
somewhere outside the operator's control — a git commit, a timestamping
service, even a scheduled email. Rejected as primary: file permissions on the
same machine as the database are not a trust boundary, and anchoring proves
the past existed without preserving its contents — an attacker deletes the
file and the anchor proves only that something is missing.

### 3. Cloud object-lock bucket (S3/GCS retention lock)

The strongest version — WORM storage where even the account owner cannot
delete inside the retention window — and the eventual production answer.
Rejected _now_ for one reason: it requires the cloud account the local-first
decision deliberately does not have yet. It composes with option 1 rather than
competing: the second-instance replicator later gains a bucket target.

## Recommendation

**Option 1 now**, sized at roughly a session: compose service, migration with
the INSERT-only grant and a test proving `DELETE` fails, the replication pass
on the maintenance loop, and a verification command. Re-evaluate option 3 the
week hosting arrives. The embargo on "customer-verifiable" stays until a
customer can actually run the verification against a store we cannot write.
