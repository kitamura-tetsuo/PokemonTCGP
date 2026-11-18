"""Small synthetic producer/data-layer/Streamlit tests; no LFS downloads."""
from contextlib import closing
import gzip
import importlib
import importlib.util
import types
import json
import os
from pathlib import Path
import pickle
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

from pokemontcgp import cache_snapshots as cs

HAS_APP_DEPS = importlib.util.find_spec("pandas") is not None and importlib.util.find_spec("streamlit") is not None
REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_APP_DEPS, "requires project dependencies")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.original = Path.cwd()
        os.chdir(self.base)
        self.cache = self.base / "data/cache"
        self.cache.mkdir(parents=True)
        self.make_inputs("sig-a", "Deck A")

    def tearDown(self):
        cs.bind_snapshot(None)
        os.chdir(self.original)
        self.temp.cleanup()

    def make_inputs(self, signature, name):
        info = {"name": name, "cards": [], "stats": {"wins": 2, "losses": 1, "ties": 0, "players": 1},
                "appearances": [{"date": "2026-11-18", "t_id": "test-event", "player_id": "player",
                                 "record": {"wins": 2, "losses": 1, "ties": 0}}]}
        payload = {"dates": {"2026-11-18": {"decks": {signature: 1}}},
                   "signatures": {signature: info}}
        with gzip.GzipFile(filename=str(self.cache / "daily_exact_stats.pkl.gz"), mode="wb", mtime=0) as f:
            pickle.dump(payload, f)
        clusters = [{"id": 1, "representative_sig": signature, "representative_name": name,
                     "signatures": [signature]}]
        (self.cache / "clusters.json").write_text(json.dumps(clusters))
        subprocess.run([sys.executable, str(REPO / "scripts/update_sqlite.py")], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return cs.descriptor(self.cache)

    def test_real_reader_survives_snapshot_module_eviction(self):
        from pokemontcgp import data
        parent = importlib.import_module("pokemontcgp")
        name = "pokemontcgp.cache_snapshots"
        original = sys.modules[name]
        legacy = self.base / "legacy"
        shutil.copytree(self.cache, legacy)
        self.make_inputs("new-only", "New snapshot only")
        snapshot_dir = self.base / "new-snapshot"
        shutil.copytree(self.cache, snapshot_dir)
        try:
            del sys.modules[name]
            fresh = importlib.import_module(name)
            selected = fresh.Snapshot("current", snapshot_dir)
            fresh.bind_snapshot(selected)
            data.verify_snapshot_binding(selected)
            with closing(data._get_db_conn()) as conn:
                self.assertEqual(conn.execute("SELECT sig FROM signatures").fetchone(), ("new-only",))
            self.assertEqual(set(data._get_all_signatures()), {"new-only"})
            self.assertEqual(set(data.get_cluster_mapping()[0]), {"new-only"})
        finally:
            sys.modules[name] = original
            parent.cache_snapshots = original

    def test_reader_gate_rejects_actual_legacy_connection_before_caption(self):
        from pokemontcgp import data
        selected = cs.Snapshot("current", self.cache)
        cs.bind_snapshot(selected)
        old = self.base / "old"
        shutil.copytree(self.cache, old)
        wrong = sqlite3.connect(old / "stats.db")
        with patch.object(data, "_get_db_conn", return_value=wrong):
            with self.assertRaisesRegex(cs.SnapshotError, "different snapshot database"):
                data.verify_snapshot_binding(selected)
        with self.assertRaises(sqlite3.ProgrammingError):
            wrong.execute("SELECT 1")  # gate must close a rejected connection

    def test_app_does_not_label_a_mismatched_reader_as_current(self):
        from streamlit.testing.v1 import AppTest
        selected = cs.Snapshot("current", self.cache)
        with patch("pokemontcgp.cache_snapshots.select_snapshot", return_value=selected), patch(
                "pokemontcgp.data.verify_snapshot_binding", side_effect=cs.SnapshotError("reader mismatch")):
            app = AppTest.from_file(str(REPO / "app.py")).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertFalse(app.caption)

    def test_app_handles_a_snapshot_error_from_an_evicted_module_copy(self):
        from streamlit.testing.v1 import AppTest
        legacy_error = type("SnapshotError", (RuntimeError,), {})
        selected = cs.Snapshot("current", self.cache)
        with patch("pokemontcgp.cache_snapshots.select_snapshot", return_value=selected), patch(
                "pokemontcgp.data.verify_snapshot_binding", side_effect=legacy_error("stale reader copy")):
            app = AppTest.from_file(str(REPO / "app.py")).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertFalse(app.caption)

    def test_canonical_app_bypasses_retained_fixed_path_src_data(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        from pokemontcgp import data
        stale = types.ModuleType("src.data")
        stale.DB_FILE = "data/cache/stats.db"
        stale._get_all_signatures = lambda: {"stale": {}}
        selected = cs.Snapshot("current", self.cache)
        def render():
            st.text(",".join(data._get_all_signatures()))
        with patch.dict(sys.modules, {"src.data": stale}), patch(
                "pokemontcgp.cache_snapshots.select_snapshot", return_value=selected), patch(
                "pokemontcgp.ui.render_meta_trend_page", side_effect=render):
            app = AppTest.from_file(str(REPO / "app.py")).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual([t.value for t in app.text], ["sig-a"])
        self.assertEqual([c.value for c in app.caption], ["Data snapshot: current"])

    def test_routing_epoch_does_not_reuse_old_results_under_same_generation(self):
        import pandas as pd
        from pokemontcgp.ui import _get_cached_trend_data
        cs.bind_snapshot(cs.Snapshot("same-generation", self.cache))
        with patch("pokemontcgp.ui.get_daily_share_data", return_value=pd.DataFrame([["old-result"]])):
            old = _get_cached_trend_data("same-generation", None, None, 7)
        with patch("pokemontcgp.ui.get_daily_share_data", return_value=pd.DataFrame([["current-result"]])):
            current = _get_cached_trend_data(cs.generation_key(), None, None, 7)
        self.assertEqual(old.iloc[0, 0], "old-result")
        self.assertEqual(current.iloc[0, 0], "current-result")

    def test_real_producer_schema_and_provenance_validate(self):
        spec = cs.descriptor(self.cache)
        cs.validate(self.cache, spec)
        with closing(sqlite3.connect(self.cache / "stats.db")) as conn:
            self.assertEqual(conn.execute("SELECT wins FROM daily_stats WHERE identifier='sig-a'").fetchone(), (2,))
            self.assertEqual(dict(conn.execute("SELECT name,sha256 FROM cache_inputs")), {
                name: spec["files"][name]["sha256"] for name in cs.FILES if name != "stats.db"})

    def test_real_http_transport_is_complete_before_install_and_rejects_truncation(self):
        spec = cs.descriptor(self.cache)
        source = self.cache
        truncate = False
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                name = handler.path.removeprefix("/")
                payload = (source / name).read_bytes()
                handler.send_response(200)
                handler.send_header("Content-Length", str(len(payload)))
                handler.end_headers()
                handler.wfile.write(payload[:10] if truncate and name == "stats.db" else payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        real_open = urllib.request.urlopen
        def route(request, **kwargs):
            prefix = f"https://github.com/{cs.REPOSITORY}/releases/download/{spec['generation']}/"
            self.assertTrue(request.full_url.startswith(prefix))
            name = request.full_url.removeprefix(prefix)
            return real_open(f"http://127.0.0.1:{server.server_port}/{name}", **kwargs)
        manifest = self.base / "manifest.json"
        manifest.write_text(json.dumps({"format": 1, "current": spec}))
        try:
            with patch.object(cs.urllib.request, "urlopen", side_effect=route):
                snapshot = cs.select_snapshot(manifest, self.base / "downloaded")
                cs.validate(snapshot.directory, spec)
                truncate = True
                with self.assertRaises(cs.SnapshotError):
                    cs.select_snapshot(manifest, self.base / "truncated")
            self.assertFalse((self.base / "truncated" / spec["generation"]).exists())
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_release_mode_staging_freezes_legacy_files_and_stages_manifest(self):
        repo = self.base / "staging-test"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True)
        git("init", "-q")
        for name in cs.FILES:
            path = repo / "data/cache" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original legacy bytes")
        git("add", "data")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "legacy baseline")
        original = {name: git("rev-parse", f"HEAD:data/cache/{name}").strip() for name in cs.FILES}
        for name in cs.FILES:
            (repo / "data/cache" / name).write_bytes(b"new generated bytes, release only")
        (repo / "data/cache-manifest.json").write_text('{"format":1}')
        (repo / "data/raw.json").write_text('{}')
        git("add", "--", "data/", *[f":!data/cache/{name}" for name in cs.FILES])
        self.assertEqual(set(git("diff", "--cached", "--name-only").splitlines()),
                         {"data/cache-manifest.json", "data/raw.json"})
        for name in cs.FILES:
            self.assertEqual(git("rev-parse", f":data/cache/{name}").strip(), original[name])
        # Only excluded legacy worktree changes remain: execute the real
        # workflow commit guard and require a successful no-op, not empty commit.
        git("reset", "-q", "HEAD", "--", "data/cache-manifest.json", "data/raw.json")
        workflow = (REPO / ".github/workflows/update_data.yml").read_text()
        guard = "          if ! git diff --staged --quiet; then"
        body = guard + workflow.split(guard, 1)[1]
        script = "\n".join(line[10:] for line in body.splitlines())
        before = git("rev-parse", "HEAD")
        subprocess.run(["bash", "-e", "-c", script], cwd=repo, check=True)
        self.assertEqual(git("rev-parse", "HEAD"), before)

    def test_data_layer_caches_are_isolated_even_when_mtimes_match(self):
        from pokemontcgp import data
        old = self.base / "old"
        shutil.copytree(self.cache, old)
        old_snapshot = cs.Snapshot("old", old)
        self.make_inputs("sig-b", "Deck B")
        # Defeat mtime-only global caches by deliberately equalizing timestamps.
        for name in cs.FILES:
            os.utime(self.cache / name, ns=(123456789, 123456789))
            os.utime(old / name, ns=(123456789, 123456789))
        cs.bind_snapshot(old_snapshot)
        self.assertEqual(set(data._get_all_signatures()), {"sig-a"})
        self.assertEqual(set(data.get_cluster_mapping()[0]), {"sig-a"})
        cs.bind_snapshot(cs.Snapshot("new", self.cache))
        self.assertEqual(set(data._get_all_signatures()), {"sig-b"})
        self.assertEqual(set(data.get_cluster_mapping()[0]), {"sig-b"})
        with closing(data._get_db_conn()) as conn:
            self.assertEqual(conn.execute("SELECT sig FROM signatures").fetchone(), ("sig-b",))
        cs.bind_snapshot(old_snapshot)
        self.assertEqual(set(data._get_all_signatures()), {"sig-a"})

    def test_streamlit_reruns_keep_generation_in_cache_key_and_pin_paths(self):
        from streamlit.testing.v1 import AppTest
        # Exercise the actual cached trend wrapper without needing raw tournament
        # datasets or creating a production app. Underlying aggregation is mocked.
        source = '''
import streamlit as st
from pokemontcgp.cache_snapshots import Snapshot, bind_snapshot, generation_key, cache_path
from pathlib import Path
from pokemontcgp.ui import _get_cached_trend_data
selected = st.selectbox("generation", ["A", "B"])
bind_snapshot(Snapshot(selected, Path(selected)))
result = _get_cached_trend_data(generation_key(), None, None, 7)
st.text(str(result.iloc[0, 0]))
st.text(cache_path("stats.db"))
'''
        import pandas as pd
        with patch("pokemontcgp.ui.get_daily_share_data", side_effect=lambda **kwargs: pd.DataFrame([[cs.generation_key()]])) as get:
            app = AppTest.from_string(source).run()
            self.assertFalse(app.exception)
            self.assertEqual([t.value for t in app.text], ["snapshot-routing-v2:A", "A/stats.db"])
            app.selectbox[0].select("B").run()
            self.assertFalse(app.exception)
            self.assertEqual([t.value for t in app.text], ["snapshot-routing-v2:B", "B/stats.db"])
            app.selectbox[0].select("A").run()
            self.assertEqual([t.value for t in app.text], ["snapshot-routing-v2:A", "A/stats.db"])
            self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
