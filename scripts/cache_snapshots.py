"""Actions-only snapshot publishing and restoration; retention is dry-run only."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokemontcgp.cache_snapshots import (FILES, REPOSITORY, SnapshotError, descriptor,
                                 locked, materialize, read_manifest, validate)


def gh_api(endpoint, method="GET", payload=None, allow_missing=False):
    command = ["gh", "api", endpoint, "--method", method]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        if allow_missing and "HTTP 404" in result.stderr:
            return None
        raise SnapshotError(f"GitHub {method} failed: {endpoint}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def restore(cache, manifest):
    """Seed the updater with the entire previous cumulative cache, never just 90d."""
    if not manifest.exists():
        # First migration only: obtain the existing complete LFS files. After
        # migration there are no tracked cache binaries and this branch is unused.
        subprocess.run(["git", "lfs", "pull", "--include=" + ",".join(
            "data/cache/" + name for name in FILES), "--exclude="], check=True)
        # Actions, never Streamlit: rebuild this first seed once to record the
        # exact pickle/cluster input hashes in SQLite before releasing it.
        subprocess.run([sys.executable, "scripts/update_sqlite.py"], check=True)
        validate(cache, descriptor(cache))
        source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        # Seed a published previous generation before the first update removes
        # the Git-tracked files. Cold starts can then fall back immediately.
        publish(cache, manifest, source_sha)
        return
    spec = read_manifest(manifest)["current"]
    root = Path(".cache/snapshots")
    with locked(root):
        source = materialize(spec, root)
        cache.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            shutil.copyfile(source / name, cache / name)


def publish(cache, manifest, source_sha):
    spec = descriptor(cache)
    validate(cache, spec)
    old = read_manifest(manifest) if manifest.exists() else None
    if old and old["current"] == spec:
        print("Cache content is unchanged; keeping the existing release and manifest.")
        return
    endpoint = f"repos/{REPOSITORY}/releases"
    tag = spec["generation"]
    release = gh_api(endpoint + "/tags/" + tag, allow_missing=True)
    if release is None:
        # Drafts may not be returned by the tag endpoint. Resume a partially
        # uploaded draft without deleting/replacing any existing release asset.
        release = next((r for r in gh_api(endpoint + "?per_page=100")
                        if r["tag_name"] == tag), None)
    if release is None:
        release = gh_api(endpoint, "POST", {
            "tag_name": tag, "target_commitish": source_sha, "draft": True,
            "name": "Cache snapshot " + tag.removeprefix("cache-")[:12],
            "body": "Precomputed application cache. Source commit: " + source_sha,
            "prerelease": False,
        })
    assets = {a["name"]: a for a in release["assets"]}
    missing = []
    for name in FILES:
        asset = assets.get(name)
        expected = spec["files"][name]
        if asset:
            if (asset.get("state") != "uploaded" or asset["size"] != expected["size"]
                    or asset.get("digest") != "sha256:" + expected["sha256"]):
                raise SnapshotError("Existing release asset cannot be verified: " + name)
        else:
            missing.append(name)
    if missing:
        if not release["draft"]:
            raise SnapshotError("Published release is incomplete; refusing to modify it")
        subprocess.run(["gh", "release", "upload", tag, "--repo", REPOSITORY,
                        *[str(cache / name) for name in missing]], check=True)
    # Verify server-side digests before making the generation public or referenced.
    release = gh_api(endpoint + "/" + str(release["id"]))
    assets = {a["name"]: a for a in release["assets"]}
    for name in FILES:
        asset, expected = assets.get(name, {}), spec["files"][name]
        if (asset.get("state") != "uploaded" or asset.get("size") != expected["size"]
                or asset.get("digest") != "sha256:" + expected["sha256"]):
            raise SnapshotError("Uploaded release asset failed verification: " + name)
    if release["draft"]:
        gh_api(endpoint + "/" + str(release["id"]), "PATCH", {"draft": False, "make_latest": "false"})
    value = {"format": 1, "current": spec}
    if old:
        value["previous"] = old["current"]
    manifest.parent.mkdir(parents=True, exist_ok=True)
    # The Git commit is the publication pointer, after assets are complete.
    with tempfile.NamedTemporaryFile(mode="w", dir=manifest.parent, delete=False) as f:
        json.dump(value, f, indent=2)
        f.write("\n")
        temporary = Path(f.name)
    temporary.replace(manifest)
    print("Published complete snapshot: " + tag)


def retention_candidates(releases, manifest, keep=3, grace_hours=72, now=None):
    """A proposal only. Never deletes releases, tags, assets or LFS objects."""
    now = now or datetime.now(timezone.utc)
    protected = {manifest[key]["generation"] for key in ("current", "previous") if manifest.get(key)}
    snapshots = sorted((r for r in releases if r["tag_name"].startswith("cache-")
                        and not r.get("draft") and r.get("published_at")),
                       key=lambda r: r["published_at"], reverse=True)
    protected.update(r["tag_name"] for r in snapshots[:keep])
    cutoff = now - timedelta(hours=grace_hours)
    return [r["tag_name"] for r in snapshots if r["tag_name"] not in protected
            and datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) < cutoff]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("restore", "publish", "retention-dry-run"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--manifest", type=Path, default=Path("data/cache-manifest.json"))
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    if args.action == "restore":
        restore(args.cache, args.manifest)
    elif args.action == "publish":
        if not args.source_sha:
            parser.error("--source-sha is required to publish")
        publish(args.cache, args.manifest, args.source_sha)
    else:
        # gh pagination remains read-only. No deletion mode intentionally exists.
        result = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/releases?per_page=100",
                                 "--paginate", "--slurp"], capture_output=True, text=True, check=True)
        releases = [r for page in json.loads(result.stdout) for r in page]
        print(json.dumps({"dry_run": True, "keep_at_least": 3, "grace_hours": 72,
                          "candidates_require_manual_active_deployment_check": retention_candidates(
                              releases, read_manifest(args.manifest))}, indent=2))


if __name__ == "__main__":
    main()
