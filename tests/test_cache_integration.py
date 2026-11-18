"""Small synthetic producer/data-layer/Streamlit tests; no LFS downloads."""
from contextlib import closing
import gzip
import importlib.util
import json
import os
from pathlib import Path
import pickle
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import cache_snapshots as cs

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

    def test_real_producer_schema_and_provenance_validate(self):
        spec = cs.descriptor(self.cache)
        cs.validate(self.cache, spec)
        with closing(sqlite3.connect(self.cache / "stats.db")) as conn:
            self.assertEqual(conn.execute("SELECT wins FROM daily_stats WHERE identifier='sig-a'").fetchone(), (2,))
            self.assertEqual(dict(conn.execute("SELECT name,sha256 FROM cache_inputs")), {
                name: spec["files"][name]["sha256"] for name in cs.FILES if name != "stats.db"})

    def test_data_layer_caches_are_isolated_even_when_mtimes_match(self):
        from src import data
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
from src.cache_snapshots import Snapshot, bind_snapshot, generation_key, cache_path
from pathlib import Path
from src.ui import _get_cached_trend_data
selected = st.selectbox("generation", ["A", "B"])
bind_snapshot(Snapshot(selected, Path(selected)))
result = _get_cached_trend_data(generation_key(), None, None, 7)
st.text(str(result.iloc[0, 0]))
st.text(cache_path("stats.db"))
'''
        import pandas as pd
        with patch("src.ui.get_daily_share_data", side_effect=lambda **kwargs: pd.DataFrame([[cs.generation_key()]])) as get:
            app = AppTest.from_string(source).run()
            self.assertFalse(app.exception)
            self.assertEqual([t.value for t in app.text], ["A", "A/stats.db"])
            app.selectbox[0].select("B").run()
            self.assertFalse(app.exception)
            self.assertEqual([t.value for t in app.text], ["B", "B/stats.db"])
            app.selectbox[0].select("A").run()
            self.assertEqual([t.value for t in app.text], ["A", "A/stats.db"])
            self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
