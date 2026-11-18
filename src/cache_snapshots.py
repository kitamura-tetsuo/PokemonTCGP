"""Verified, immutable cache generations. No aggregation runs in the web app.

The manifest is trusted repository content; pickle is loaded only after every
file's size and SHA-256 match it. URLs cannot be supplied by a visitor.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager, closing
import fcntl
import gzip
import hashlib
import json
import logging
import os
import pickle
import re
import shutil
import sqlite3
import tempfile
import threading
import urllib.request

REPOSITORY = "kitamura-tetsuo/PokemonTCGP"
FILES = ("clusters.json", "daily_exact_stats.pkl.gz", "stats.db")
TABLES = {
    "cache_inputs": {"name", "sha256"},
    "daily_stats": {"date", "identifier", "is_cluster", "wins", "losses", "ties", "players", "matches"},
    "metagame_totals": {"date", "total_players", "total_matches"},
    "signatures": {"sig", "name", "cards", "stats"},
    "clusters": {"cluster_id", "name", "representative_sig", "signatures", "cards", "stats"},
}
_selected = ContextVar("cache_snapshot", default=None)
_verified = {}
_verify_lock = threading.Lock()


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    generation: str
    directory: Path
    warning: str = ""


def cache_path(name):
    snapshot = _selected.get()
    return str((snapshot.directory if snapshot else Path("data/cache")) / name)


def generation_key():
    snapshot = _selected.get()
    return snapshot.generation if snapshot else "legacy"


def bind_snapshot(snapshot):
    """Pin this Streamlit script run, independently of other sessions/threads."""
    _selected.set(snapshot)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def descriptor(directory):
    directory = Path(directory)
    specs = {name: {"size": (directory / name).stat().st_size,
                    "sha256": _sha(directory / name)} for name in FILES}
    return {"generation": "cache-" + hashlib.sha256(_canonical(specs)).hexdigest(), "files": specs}


def check_descriptor(value):
    if not isinstance(value, dict) or set(value) != {"generation", "files"}:
        raise SnapshotError("Invalid snapshot descriptor")
    specs = value["files"]
    if not isinstance(specs, dict) or set(specs) != set(FILES):
        raise SnapshotError("Snapshot must contain all three cache files")
    for spec in specs.values():
        if (not isinstance(spec, dict) or set(spec) != {"size", "sha256"}
                or type(spec["size"]) is not int or not 0 < spec["size"] < 2**31
                or not isinstance(spec["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])):
            raise SnapshotError("Invalid snapshot size/hash")
    expected = "cache-" + hashlib.sha256(_canonical(specs)).hexdigest()
    if value["generation"] != expected:
        raise SnapshotError("Generation does not match file hashes")
    return value


def read_manifest(path):
    value = json.loads(Path(path).read_text())
    if (not isinstance(value, dict) or value.get("format") != 1
            or set(value) - {"format", "current", "previous"}):
        raise SnapshotError("Unsupported cache manifest")
    check_descriptor(value.get("current"))
    if value.get("previous") is not None:
        check_descriptor(value["previous"])
    return value


def validate(directory, spec):
    """Hash every file before deserializing trusted pickle; check DB schema/data."""
    check_descriptor(spec)
    directory = Path(directory)
    for name in FILES:
        path, expected = directory / name, spec["files"][name]
        if path.stat().st_size != expected["size"] or _sha(path) != expected["sha256"]:
            raise SnapshotError(f"Cache size/hash mismatch: {name}")
    with gzip.open(directory / "daily_exact_stats.pkl.gz", "rb") as f:
        data = pickle.load(f)
    clusters = json.loads((directory / "clusters.json").read_text())
    if (not isinstance(data, dict) or not isinstance(data.get("dates"), dict)
            or not isinstance(data.get("signatures"), dict) or not data["dates"]
            or not data["signatures"] or not isinstance(clusters, list) or not clusters):
        raise SnapshotError("Empty or invalid cache structures")
    sigs = set(data["signatures"])
    cluster_ids = set()
    for cluster in clusters:
        if (not isinstance(cluster, dict) or "id" not in cluster
                or not isinstance(cluster.get("signatures"), list)
                or not cluster["signatures"] or not set(cluster["signatures"]) <= sigs
                or cluster.get("representative_sig") not in cluster["signatures"]):
            raise SnapshotError("Inconsistent clusters and signatures")
        cluster_ids.add(str(cluster["id"]))
    if len(cluster_ids) != len(clusters):
        raise SnapshotError("Duplicate cluster identifiers")
    uri = (directory / "stats.db").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise SnapshotError("SQLite integrity check failed")
        for table, required in TABLES.items():
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if not required <= columns:
                raise SnapshotError(f"SQLite schema mismatch: {table}")
        inputs = dict(conn.execute("SELECT name, sha256 FROM cache_inputs"))
        expected_inputs = {name: spec["files"][name]["sha256"] for name in FILES if name != "stats.db"}
        if inputs != expected_inputs:
            raise SnapshotError("SQLite was generated from different pickle/cluster inputs")
        if {r[0] for r in conn.execute("SELECT sig FROM signatures")} != sigs:
            raise SnapshotError("SQLite and pickle signatures differ")
        if {r[0] for r in conn.execute("SELECT cluster_id FROM clusters")} != cluster_ids:
            raise SnapshotError("SQLite and JSON clusters differ")
        if not conn.execute("SELECT 1 FROM daily_stats LIMIT 1").fetchone():
            raise SnapshotError("SQLite daily statistics are empty")
    return spec


def _fingerprint(directory):
    return tuple((name, (directory / name).stat().st_size,
                  (directory / name).stat().st_mtime_ns) for name in FILES)


def verify_local(directory, spec):
    # Rehash once per process/generation and after any local file change.
    key = (str(directory.resolve()), spec["generation"], _fingerprint(directory))
    with _verify_lock:
        if key not in _verified:
            validate(directory, spec)
            _verified[key] = True
    return directory


def download(name, destination, spec):
    url = (f"https://github.com/{REPOSITORY}/releases/download/"
           f"{spec['generation']}/{name}")
    expected = spec["files"][name]["size"]
    request = urllib.request.Request(url, headers={"User-Agent": "PokemonTCGP-cache/1"})
    with urllib.request.urlopen(request, timeout=30) as response, open(destination, "xb") as out:
        count = 0
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > expected:
                raise SnapshotError("Download exceeds manifest size")
            out.write(chunk)
        if count != expected:
            raise SnapshotError("Incomplete cache download")


@contextmanager
def locked(root):
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def materialize(spec, root, fetch=download):
    """Caller holds the cross-process lock. Never expose a partial generation."""
    check_descriptor(spec)
    final = root / spec["generation"]
    if final.exists():
        return verify_local(final, spec)
    stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=root))
    try:
        for name in FILES:
            fetch(name, stage / name, spec)
        validate(stage, spec)
        os.rename(stage, final)
        with _verify_lock:
            _verified[(str(final.resolve()), spec["generation"], _fingerprint(final))] = True
        return final
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def select_snapshot(manifest_path="data/cache-manifest.json", root=".cache/snapshots", fetch=download):
    """Return a complete current/previous generation, or fail closed on cold start.

    With no manifest the pre-migration local paths remain unchanged. A warm
    fallback also preserves a locally verified last-good generation if this
    instance missed intermediate manifest updates. It is never fetched remotely.
    """
    path = Path(manifest_path)
    if not path.exists():
        return None
    manifest = read_manifest(path)  # malformed metadata never silently downgrades
    root = Path(root)
    candidates = [manifest["current"]]
    if manifest.get("previous") and manifest["previous"] != candidates[0]:
        candidates.append(manifest["previous"])
    errors = []
    with locked(root):
        receipt = root / "last-good.json"
        try:
            last_good = check_descriptor(json.loads(receipt.read_text()))
        except (OSError, ValueError, SnapshotError):
            last_good = None
        local_only = None
        if last_good and last_good not in candidates:
            candidates.append(last_good)
            local_only = last_good
        for i, spec in enumerate(candidates):
            try:
                if spec == local_only:
                    directory = verify_local(root / spec["generation"], spec)
                else:
                    directory = materialize(spec, root, fetch)
                # Receipt is written only after full verification and an atomic
                # generation install. It survives skipped manifest updates.
                try:
                    with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False) as f:
                        json.dump(spec, f)
                        temporary = Path(f.name)
                    temporary.replace(receipt)
                except OSError:
                    # A full cache disk must not prevent reading an already
                    # installed, verified generation. Receipt is best effort.
                    logging.getLogger(__name__).warning("Unable to save last-good cache receipt")
                warning = "" if i == 0 else "Latest cache unavailable; showing an older verified snapshot."
                return Snapshot(spec["generation"], directory, warning)
            except (OSError, ValueError, EOFError, pickle.UnpicklingError, sqlite3.Error, SnapshotError) as exc:
                errors.append(f"{spec['generation']}: {type(exc).__name__}")
    raise SnapshotError("No verified cache snapshot available (" + "; ".join(errors) + ")")
