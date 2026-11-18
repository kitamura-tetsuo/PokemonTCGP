from contextlib import closing
import asyncio
import contextvars
import importlib
import sys
import types
import concurrent.futures
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import pickle
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from pokemontcgp import cache_snapshots as cs
from scripts import cache_snapshots as publisher


def fixture(root, version="a"):
    root.mkdir(parents=True)
    data = {"dates": {"2026-11-18": {"decks": {version: 1}}},
            "signatures": {version: {"name": version, "cards": [], "appearances": []}}}
    with gzip.GzipFile(filename=str(root / "daily_exact_stats.pkl.gz"), mode="wb", mtime=0) as f:
        pickle.dump(data, f)
    clusters = [{"id": 1, "signatures": [version], "representative_sig": version,
                 "representative_name": version}]
    (root / "clusters.json").write_text(json.dumps(clusters))
    with closing(sqlite3.connect(root / "stats.db")) as conn:
        for table, columns in cs.TABLES.items():
            conn.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in sorted(columns))})")
        for name in cs.FILES:
            if name != "stats.db":
                conn.execute("INSERT INTO cache_inputs (name,sha256) VALUES (?,?)", (name,cs._sha(root / name)))
        conn.execute("INSERT INTO signatures (sig) VALUES (?)", (version,))
        conn.execute("INSERT INTO clusters (cluster_id) VALUES ('1')")
        conn.execute("INSERT INTO daily_stats (date,identifier) VALUES ('2026-11-18',?)", (version,))
        conn.commit()
    return cs.descriptor(root)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.old = fixture(self.base / "old", "old")
        self.new = fixture(self.base / "new", "new")
        self.manifest = self.base / "manifest.json"
        self.store = self.base / "store"
        self.write_manifest(self.new, self.old)
        self.sources = {self.old["generation"]: self.base / "old",
                        self.new["generation"]: self.base / "new"}
        cs.bind_snapshot(None)

    def tearDown(self):
        cs.bind_snapshot(None)
        self.temp.cleanup()

    def write_manifest(self, current, previous=None):
        value = {"format": 1, "current": current}
        if previous:
            value["previous"] = previous
        self.manifest.write_text(json.dumps(value))

    def fetch(self, name, destination, spec):
        shutil.copyfile(self.sources[spec["generation"]] / name, destination)

    def select(self, fetch=None):
        return cs.select_snapshot(self.manifest, self.store, fetch or self.fetch)

    def test_partial_module_eviction_shares_binding_with_captured_old_helpers(self):
        name = "pokemontcgp.cache_snapshots"
        parent = importlib.import_module("pokemontcgp")
        original = sys.modules[name]
        old_path = cs.cache_path
        try:
            del sys.modules[name]
            fresh = importlib.import_module(name)
            snapshot = fresh.Snapshot(self.new["generation"], self.base / "new")
            fresh.bind_snapshot(snapshot)
            self.assertEqual(old_path("stats.db"), fresh.cache_path("stats.db"))
            self.assertEqual(Path(old_path("stats.db")).parent, snapshot.directory)
            self.assertEqual(cs.generation_key(), fresh.generation_key())
        finally:
            sys.modules[name] = original
            parent.cache_snapshots = original

    def test_compatibility_namespace_and_canonical_helpers_share_current_thread(self):
        legacy = importlib.import_module("src.cache_snapshots")
        cs.bind_snapshot(cs.Snapshot(self.new["generation"], self.base / "new"))
        self.assertEqual(legacy.cache_path("stats.db"), cs.cache_path("stats.db"))
        self.assertEqual(legacy.generation_key(), cs.generation_key())

    def test_async_contexts_in_one_thread_keep_separate_snapshots(self):
        async def reader(spec, directory):
            cs.bind_snapshot(cs.Snapshot(spec["generation"], directory))
            await asyncio.sleep(0)
            return cs.generation_key(), Path(cs.cache_path("stats.db")).parent
        async def run():
            return await asyncio.gather(reader(self.old, self.base / "old"), reader(self.new, self.base / "new"))
        self.assertEqual(asyncio.run(run()), [
            ("snapshot-routing-v2:" + self.old["generation"], self.base / "old"),
            ("snapshot-routing-v2:" + self.new["generation"], self.base / "new")])

    def test_web_namespace_does_not_import_retained_pre_migration_src_modules(self):
        # An old Cloud process may still retain the fixed-path implementation.
        stale = types.ModuleType("src.data")
        stale.CACHE_FILE = "data/cache/daily_exact_stats.pkl.gz"
        stale.DB_FILE = "data/cache/stats.db"
        with patch.dict(sys.modules, {"src.data": stale}):
            module = importlib.import_module("pokemontcgp.cache_snapshots")
            self.assertIsNot(module, stale)
            cs.bind_snapshot(cs.Snapshot(self.new["generation"], self.base / "new"))
            self.assertNotEqual(module.cache_path("stats.db"), stale.DB_FILE)
        self.assertTrue(cs.generation_key().startswith("snapshot-routing-v2:"))

    def test_legacy_mode_does_not_download_or_rebuild(self):
        self.manifest.unlink()
        with patch.object(cs, "download", side_effect=AssertionError("network")):
            self.assertIsNone(self.select())
        self.assertEqual(cs.cache_path("stats.db"), "data/cache/stats.db")

    def test_current_generation_installed_and_reused_offline(self):
        snapshot = self.select()
        self.assertFalse(snapshot.warning)
        self.assertEqual(snapshot.generation, self.new["generation"])
        def offline(*args):
            raise OSError("offline")
        self.assertEqual(self.select(offline).directory, snapshot.directory)
        cs.bind_snapshot(snapshot)
        self.assertEqual(cs.generation_key(), "snapshot-routing-v2:" + self.new["generation"])
        self.assertEqual(Path(cs.cache_path("stats.db")).parent, snapshot.directory)

    def test_receipt_write_failure_still_serves_verified_generation(self):
        previous = self.select()
        with patch.object(cs.tempfile, "NamedTemporaryFile", side_effect=OSError("disk full")), self.assertLogs("pokemontcgp.cache_snapshots", level="WARNING"):
            self.assertEqual(self.select().directory, previous.directory)

    def test_cold_start_downloads_previous_if_current_fails(self):
        def fetch(name, destination, spec):
            if spec == self.new:
                raise OSError("unreachable")
            self.fetch(name, destination, spec)
        snapshot = self.select(fetch)
        self.assertEqual(snapshot.generation, self.old["generation"])
        self.assertTrue(snapshot.warning)
        self.assertFalse((self.store / self.new["generation"]).exists())
        self.assertFalse(list(self.store.glob(".incoming-*")))

    def test_warm_previous_survives_failed_update_and_network_outage(self):
        self.write_manifest(self.old)
        previous = self.select()
        self.write_manifest(self.new, self.old)
        def offline(*args):
            raise OSError("offline")
        self.assertEqual(self.select(offline).directory, previous.directory)

    def test_warm_last_good_survives_skipped_manifest_generation(self):
        self.write_manifest(self.old)
        previous = self.select()
        intermediate = fixture(self.base / "intermediate", "middle")
        self.write_manifest(self.new, intermediate)
        def offline(*args):
            raise OSError("offline")
        recovered = self.select(offline)
        self.assertEqual(recovered.directory, previous.directory)
        self.assertTrue(recovered.warning)

    def test_no_complete_generation_fails_closed(self):
        def partial(name, destination, spec):
            destination.write_bytes(b"incomplete")
        with self.assertRaises(cs.SnapshotError):
            self.select(partial)
        self.assertFalse(any(p.is_dir() for p in self.store.iterdir()))

    def test_all_hashes_checked_before_pickle_load(self):
        (self.base / "new" / "stats.db").write_bytes(b"corrupt")
        with patch.object(cs.pickle, "load", side_effect=AssertionError("must not unpickle")):
            with self.assertRaises(cs.SnapshotError):
                cs.validate(self.base / "new", self.new)

    def test_hash_and_size_reject_tampered_download(self):
        def tampered(name, destination, spec):
            self.fetch(name, destination, spec)
            if name == "clusters.json":
                content = destination.read_bytes()
                destination.write_bytes(b"x" + content[1:])
        with self.assertRaises(cs.SnapshotError):
            self.select(tampered)

    def test_invalid_sqlite_or_inconsistent_inputs_rejected(self):
        with closing(sqlite3.connect(self.base / "new" / "stats.db")) as conn:
            conn.execute("DELETE FROM signatures")
            conn.commit()
        spec = cs.descriptor(self.base / "new")
        with self.assertRaisesRegex(cs.SnapshotError, "signatures differ"):
            cs.validate(self.base / "new", spec)
        (self.base / "new" / "stats.db").write_bytes(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            cs.validate(self.base / "new", cs.descriptor(self.base / "new"))

    def test_same_ids_with_different_inputs_fail_provenance_check(self):
        path = self.base / "new" / "clusters.json"
        value = json.loads(path.read_text())
        value[0]["representative_name"] = "changed name, same identifiers"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(cs.SnapshotError, "different pickle/cluster inputs"):
            cs.validate(self.base / "new", cs.descriptor(self.base / "new"))

    def test_path_traversal_generation_or_partial_manifest_rejected(self):
        self.new["generation"] = "../../escape"
        self.write_manifest(self.new)
        with self.assertRaises(cs.SnapshotError):
            self.select()
        self.manifest.write_text('{"format":1}')
        with self.assertRaises(cs.SnapshotError):
            self.select()

    def test_atomic_install_and_concurrent_sessions_download_once(self):
        downloads = []
        mutex = threading.Lock()
        def fetch(name, destination, spec):
            with mutex:
                downloads.append(name)
            # Final directory must remain invisible until all files are valid.
            self.assertFalse((self.store / self.new["generation"]).exists())
            self.fetch(name, destination, spec)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            snapshots = list(pool.map(lambda _: self.select(fetch), range(8)))
        self.assertEqual(len(downloads), 3)
        self.assertEqual(len({s.directory for s in snapshots}), 1)

    def test_thread_contexts_pin_different_generations(self):
        current = self.select()
        self.write_manifest(self.old)
        previous = self.select()
        barrier = threading.Barrier(2)
        def check(snapshot):
            cs.bind_snapshot(snapshot)
            barrier.wait(timeout=5)
            return cs.generation_key(), Path(cs.cache_path("stats.db")).parent
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(check, [current, previous]))
        self.assertEqual(results, [("snapshot-routing-v2:" + s.generation, s.directory) for s in [current, previous]])

    def test_local_corruption_is_not_reused_from_process_validation_cache(self):
        snapshot = self.select()
        (snapshot.directory / "stats.db").write_bytes(b"corrupt")
        recovered = self.select()
        self.assertEqual(recovered.generation, self.old["generation"])
        self.assertTrue(recovered.warning)

    def test_retention_is_dry_run_protects_current_previous_recent_and_grace(self):
        releases = [{"tag_name": "cache-" + str(n), "draft": False,
                     "published_at": f"2026-11-{n:02d}T00:00:00Z"} for n in range(1, 19)]
        releases.append({"tag_name": "v1", "draft": False, "published_at": "2020-01-01T00:00:00Z"})
        manifest = {"current": {"generation": "cache-1"}, "previous": {"generation": "cache-2"}}
        candidates = publisher.retention_candidates(releases, manifest,
            now=datetime(2026, 11, 18, tzinfo=timezone.utc))
        self.assertEqual(candidates, ["cache-" + str(n) for n in range(14, 2, -1)])
        self.assertNotIn("v1", candidates)

    def test_publish_verifies_assets_before_publication_or_manifest_switch(self):
        original = self.manifest.read_bytes()
        calls = []
        release = {"id": 1, "tag_name": self.new["generation"], "draft": True, "assets": []}
        def api(endpoint, method="GET", payload=None, **kwargs):
            calls.append(method)
            return release
        self.write_manifest(self.old)
        original = self.manifest.read_bytes()
        with patch.object(publisher, "gh_api", side_effect=api), patch.object(publisher.subprocess, "run"):
            with self.assertRaises(cs.SnapshotError):
                publisher.publish(self.base / "new", self.manifest, "a" * 40)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assertNotIn("PATCH", calls)

    def test_draft_creation_upload_verification_and_publication_order(self):
        self.write_manifest(self.old)
        release = {"id": 8, "tag_name": self.new["generation"], "draft": True, "assets": []}
        events = []
        def api(endpoint, method="GET", payload=None, **kwargs):
            events.append(method)
            if "/tags/" in endpoint:
                return None
            if "?per_page=" in endpoint:
                return []
            if method == "POST":
                self.assertTrue(payload["draft"])
            return release
        def upload(command, **kwargs):
            self.assertEqual(cs.read_manifest(self.manifest)["current"], self.old)
            events.append("UPLOAD")
            release["assets"] = [
                {"name": name, "state": "uploaded", "size": spec["size"],
                 "digest": "sha256:" + spec["sha256"]}
                for name, spec in self.new["files"].items()]
        with patch.object(publisher, "gh_api", side_effect=api), patch.object(publisher.subprocess, "run", side_effect=upload):
            publisher.publish(self.base / "new", self.manifest, "a" * 40)
        self.assertEqual(events, ["GET", "GET", "POST", "UPLOAD", "GET", "PATCH"])
        self.assertEqual(cs.read_manifest(self.manifest)["previous"], self.old)

    def test_first_migration_seeds_complete_fallback_before_normal_update(self):
        self.manifest.unlink()
        events = []
        def command(args, **kwargs):
            events.append("lfs" if args[:2] == ["git", "lfs"] else "runner-db-generation")
        def seed(cache, manifest, source_sha):
            events.append("publish-seed")
            manifest.write_text(json.dumps({"format": 1, "current": cs.descriptor(cache)}))
        with patch.object(publisher.subprocess, "run", side_effect=command), patch.object(publisher.subprocess, "check_output", return_value="a" * 40), patch.object(publisher, "publish", side_effect=seed):
            publisher.restore(self.base / "old", self.manifest)
        self.assertEqual(events, ["lfs", "runner-db-generation", "publish-seed"])
        self.assertEqual(cs.read_manifest(self.manifest)["current"], self.old)

    def test_publish_completed_release_then_records_previous(self):
        self.write_manifest(self.old)
        release = {"id": 1, "tag_name": self.new["generation"], "draft": True,
                   "assets": [{"name": name, "state": "uploaded", "size": spec["size"],
                               "digest": "sha256:" + spec["sha256"]}
                              for name, spec in self.new["files"].items()]}
        calls = []
        def api(endpoint, method="GET", payload=None, **kwargs):
            if method == "PATCH":
                self.assertEqual(cs.read_manifest(self.manifest)["current"], self.old)
            calls.append(method)
            return release
        with patch.object(publisher, "gh_api", side_effect=api):
            publisher.publish(self.base / "new", self.manifest, "a" * 40)
        manifest = cs.read_manifest(self.manifest)
        self.assertEqual(manifest["current"], self.new)
        self.assertEqual(manifest["previous"], self.old)
        self.assertEqual(calls[-1], "PATCH")


if __name__ == "__main__":
    unittest.main()
