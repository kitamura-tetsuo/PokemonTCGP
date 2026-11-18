# Cache distribution and rollout

The application must use precomputed cumulative cache data. It never rebuilds
SQLite at Streamlit startup. Release distribution moves all three generated
files together: `stats.db`, `daily_exact_stats.pkl.gz`, and `clusters.json`.
Moving only SQLite would leave input generations and historical LFS growth to
manage separately. A Git manifest references exact content-addressed release
assets; no web user can supply download URLs. Existing card and tournament JSON
remain in Git and are still needed by the application (including match history).

## Inactive until explicit rollout

This PR does not change main, create a release, download LFS binaries, or change
repository variables. No manifest is checked in. The current three tracked LFS
files remain tracked and usable. The enabled updater excludes these three paths from staging, freezing their
existing Git versions. Removal is a separate operational follow-up after verifying
that live requests have moved to manifest-based snapshots.

After code review/merge, separately authorize and validate rollout:

1. Confirm the deployed Streamlit repository, branch, entrypoint and Python
   version, plus outbound access to GitHub Release download redirects. Community
   Cloud is assumed; its actual app settings have not been inspected. Check tag
   rules/release policy. The updater already has `contents: write`; it uses the
   run's `GITHUB_TOKEN`, not a new personal token. Public release assets are public
   downloads; do not use them for confidential data.
2. Set repo variable `RELEASE_CACHE_ENABLED=true` only when ready for operational
   cutover. Do not dispatch the workflow merely to test code. The main-only,
   serialized updater will obtain the complete initial LFS cache once, rebuild
   SQLite **on the Actions runner** to bind exact input hashes, and publish that
   complete seed. It then performs the normal update and publishes the new
   generation. The seed is the cold-start fallback for the first cutover. The old three Git files remain
   frozen to protect requests that started before the manifest appeared.
3. Both releases are verified before a Git commit can point at them. The
   generated binaries are excluded from staging, so no further LFS revisions
   are added even though the original files remain tracked. Subsequent updates restore the complete current snapshot before
   refreshing the recent 90 days, preserving accumulated older data. Only the
   tiny manifest and normal raw data are committed. Concurrent updater runs are
   serialized; an unrelated main update that rejects the push leaves the deployed
   manifest unchanged (possibly an unreferenced release to inspect later).
4. Verify actual Streamlit cold start download latency/memory, every trends and
   comparison view, detail/match history, reruns and multi-session access, and a
   simulated release download outage before declaring the cutover healthy.
   Tests use synthetic fixtures, not production LFS data or live Release writes.
5. Do not simply turn the variable off after migration: the workflow fails closed
   if a manifest already exists. Keep distribution enabled while arranging an
   explicit rollback. Reverting only application code to the old local paths
   would be unsafe once the frozen binaries are removed. Before that removal,
   legacy code would read stale frozen data, not the newest snapshot.

6. After verifying the actual deployed manifest generation and allowing in-flight
   legacy requests to finish (or doing a separately approved maintenance restart),
   remove the three frozen files from the current Git tree in a separate reviewed
   commit. This is ordinary reversible Git tracking removal, not history rewriting
   or LFS purge. Until then, Community Cloud may still download the frozen LFS
   files at checkout in addition to the Release files. The first stage stops
   storage growth; this follow-up also avoids that redundant checkout transfer.

## Integrity, switching and availability

The producer records SHA-256 of the exact pickle and cluster inputs in SQLite's
`cache_inputs` table. Before using any pickle, the consumer checks **all three**
file sizes/hashes against the trusted Git manifest. It then checks structures,
SQLite `quick_check`, required columns, identifiers and recorded input hashes.
Pickle can execute code: hashes prove correspondence to repository-approved
content, not safety of arbitrary pickle. Only the trusted updater may publish
inputs/manifests; never load an arbitrary visitor-provided pickle or URL.

Downloads go to a private staging directory. A cross-process file lock prevents
partial concurrent installs; a directory rename exposes only a fully verified
generation. Context-local selection pins all reads in each Streamlit script run
without switching other sessions' globals. Data-layer caches use file path plus
nanosecond mtime; the Streamlit trend cache includes generation in its key.
No existing generation is overwritten. Files are verified once per process and
again after detected local modification, rather than hashing the large DB on
every Streamlit rerun.

If the current release cannot be obtained/verified, cold instances try the
manifest's previous complete generation. Warm instances can additionally use a
locally verified last-good receipt even after missing intervening manifest
updates. Receipt-only generations are never downloaded remotely. A visible
warning and generation label identify fallback data. If no complete generation
is available, the app displays data-unavailable and stops instead of showing
empty or mixed results. Malformed Git manifests fail closed.

Local storage is a disposable cache, not a persistence guarantee. A reboot may
require downloading again. Size/hash and database checks cost startup I/O and
memory and must be measured on the real host. A corrupt installed generation
fails verification and falls back; inspect/clear its local directory only while
all app sessions are stopped, then restart to retry the download. Local snapshot
folders are not automatically garbage-collected, so long-lived instances need
monitoring and an explicitly scheduled stopped-app cleanup/restart if storage
accumulates. Keeping them avoids invalidating in-flight sessions' pinned paths.

## Release retention: proposals only

`uv run python scripts/cache_snapshots.py retention-dry-run` lists proposed
candidates. There is intentionally **no deletion mode and no automatic deletion
workflow**. The proposal protects current and previous manifest references, at
least the latest three published snapshots and a 72-hour grace period. It ignores
non-cache releases and drafts. Before any deletion, also check the actually
running app/rollback references and in-flight deployments; those cannot be
inferred from the GitHub release list. Keep the live generation and a known-good
rollback generation. Drafts/orphan releases from failed jobs need manual review.

This can support a finite set of snapshots after separately approved cleanup;
with dry-run alone, Release assets will continue accumulating. Deleting old assets
removes the ability to redeploy historical Git manifests referencing them unless
a matching backup is restored. Do not repeatedly replace/delete assets at a
single `latest` URL: upload to a new draft, verify server digests, publish, then
commit the new pointer. Retries resume missing draft assets and never clobber.

## Existing LFS capacity is a separate recovery project

Stopping new LFS revisions does not purge existing remote objects. At the audit
SHA `fed58ad09b2ed533bbc89c7dc55224dc3ae0ae6b`, reachable history referenced 1,617
unique LFS OIDs / 19,195,761,178 declared bytes, of which 1,614 OIDs /
19,162,134,348 bytes were not in the then-current three files. This is pointer
history, **not verified remote/billed storage**; later commits add more versions.
The 9.02/10 GB account display and GB-hour billing remain distinct measurements.
Once release distribution is enabled, the expected new LFS bytes from these three paths are zero;
Release assets and ordinary raw-data Git history are separate storage.

Before any history rewrite/force push/remote purge, refresh the OID inventory,
identify retained live/rollback snapshots, and obtain execution-time approval
for concrete targets. Consult GitHub Support about purging obsolete LFS objects;
normal file deletion or rewriting pointers alone does not reclaim remote LFS
storage. No such destructive operation is included here. Deleting/recreating the
repository would also lose issues/stars/forks and disrupt deployment links and
is not an automatic fallback. Pointer-only clones cannot restore purged binary
objects. No complete offline backup of historical LFS data was established by
this audit; deterministic reconstruction of the exact historical bytes is not
guaranteed. Secure any required binary backups before irreversible reclamation.
