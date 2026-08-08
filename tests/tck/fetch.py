"""Fetch official openCypher TCK into /tmp (not vendored in-repo)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_URL = "https://github.com/opencypher/openCypher"
DEFAULT_ROOT = Path("/tmp/opencypher")
FEATURES_REL = Path("tck/features")
GRAPHS_REL = Path("tck/graphs")


def official_tck_root(root: Path | None = None) -> Path:
    return root or DEFAULT_ROOT


def official_features_path(root: Path | None = None) -> Path:
    return official_tck_root(root) / FEATURES_REL


def official_graphs_path(root: Path | None = None) -> Path:
    return official_tck_root(root) / GRAPHS_REL


def ensure_official_tck(root: Path | None = None) -> Path:
    """Clone or refresh sparse official TCK checkout; return features directory."""
    base = official_tck_root(root)
    features = official_features_path(base)
    if features.exists() and any(features.rglob("*.feature")):
        return features

    base.parent.mkdir(parents=True, exist_ok=True)
    if base.exists():
        subprocess.run(["git", "-C", str(base), "fetch", "--depth", "1", "origin"], check=True)
        subprocess.run(["git", "-C", str(base), "checkout", "origin/master"], check=True)
    else:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                REPO_URL,
                str(base),
            ],
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(base), "sparse-checkout", "set", str(FEATURES_REL), str(GRAPHS_REL)],
        check=True,
    )
    if not features.exists() or not any(features.rglob("*.feature")):
        raise RuntimeError(f"official TCK features not found under {features}")
    return features
