#!/usr/bin/env python3

# Exports the header tree of a running fork-observer instance into site/tree,
# which the dashboard embeds. Started from the database ci/fork-observer-db.py
# builds, the instance's tree holds every stale block of the dataset next to
# the main chain. site/tree gets:
#
#   index.html    ci/fork-observer/tree.html, the page drawing the tree
#   data.json     the instance's api/<network id>/data.json response
#   static/       fork-observer's css, js and img directories
#
# The scripts, styles and images are those of fork-observer's main branch,
# fetched from GitHub, so they don't go stale.
#
# fork-observer only marks blocks that a node reports as a chain tip. No node
# reports the stale blocks, so a made-up node is added to the response with
# every stale branch's tip. The frontend then draws them with a tip status:
# valid-headers where the dataset holds the full block, and headers-only where
# it holds only the header. That's what Bitcoin Core calls blocks it has,
# respectively hasn't, downloaded but never validated.

import csv
import io
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "stale-blocks.csv"
BLOCKS_DIR = REPO_ROOT / "blocks"
TREE_HTML_PATH = REPO_ROOT / "ci" / "fork-observer" / "tree.html"
OUT_DIR = REPO_ROOT / "site" / "tree"

FORK_OBSERVER_REPO = "0xB10C/fork-observer"
FORK_OBSERVER_BRANCH = "main"
USER_AGENT = "stale-blocks-ci (https://github.com/bitcoin-data/stale-blocks)"

FORK_OBSERVER_URL = os.environ.get("FORK_OBSERVER_URL", "http://127.0.0.1:2323")
# Must match ci/fork-observer/config.toml.
NETWORK_ID = 1
# The instance polls its block-dn node once per query_interval (15s) after a
# short initial delay. Loading the tree from the database takes a while too.
READY_TIMEOUT_S = 600
TIMEOUT_S = 120


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


# The header tree is only complete once the block-dn node reported its tip and
# fork-observer fetched the blocks found since the database was built. The
# node's tips show up in the response a moment before the tree is updated, so
# the tip block has to be in the tree as well.
def wait_for_data():
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            data = json.loads(fetch(f"{FORK_OBSERVER_URL}/api/{NETWORK_ID}/data.json"))
            in_tree = {h["hash"] for h in data["header_infos"]}
            tips = [tip for node in data["nodes"] for tip in node["tips"]]
            if tips and all(tip["hash"] in in_tree for tip in tips):
                return data
            print("fork-observer is up, waiting for its node's tip to be in the tree..")
        except (URLError, TimeoutError, ConnectionError):
            print("waiting for fork-observer..")
        time.sleep(5)
    sys.exit(f"fork-observer at {FORK_OBSERVER_URL} didn't become ready within {READY_TIMEOUT_S}s")


# The tips of the stale branches: stale blocks no other stale block builds on.
# Only blocks that are in the response can be marked, so the ones whose header
# couldn't be placed in the tree (see ci/fork-observer-db.py) are left out.
def stale_tips(header_infos):
    with open(CSV_PATH, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["header"]]

    in_tree = {h["hash"]: h["height"] for h in header_infos}
    built_on = {bytes.fromhex(r["header"])[4:36][::-1].hex() for r in rows}

    tips = []
    for r in rows:
        if r["hash"] not in in_tree or r["hash"] in built_on:
            continue
        has_block = (BLOCKS_DIR / f"{r['height']}-{r['hash']}.bin").exists()
        tips.append({
            "hash": r["hash"],
            "status": "valid-headers" if has_block else "headers-only",
            "height": in_tree[r["hash"]],
        })
    return tips


def dataset_node(header_infos):
    tips = stale_tips(header_infos)
    print(f"Marking {len(tips)} stale branch tips")
    return {
        "id": 1000,
        "name": "stale-blocks dataset",
        "description": "",
        "implementation": "",
        "tips": tips,
        "last_changed_timestamp": 0,
        "version": "",
        "reachable": True,
    }


# The css, js and img directories of fork-observer's main branch as
# {path: bytes}, with paths relative to www.
def fetch_frontend():
    print(f"Fetching the fork-observer frontend from the {FORK_OBSERVER_BRANCH} branch..")
    archive = fetch(f"https://github.com/{FORK_OBSERVER_REPO}/archive/refs/heads/{FORK_OBSERVER_BRANCH}.tar.gz")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            # The archive's top-level directory is named after the repository
            # and branch.
            parts = Path(member.name).parts[1:]
            if len(parts) < 3 or parts[0] != "www" or parts[1] not in ("css", "js", "img"):
                continue
            if member.isfile():
                files[str(Path(*parts[1:]))] = tar.extractfile(member).read()

    for path in ("css/bootstrap.min.css", "css/style.css", "js/d3.v7.min.js", "js/blocktree.js"):
        if path not in files:
            sys.exit(f"the fork-observer archive doesn't contain www/{path}")
    return files


def write_site(frontend, data):
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    shutil.copy(TREE_HTML_PATH, OUT_DIR / "index.html")
    (OUT_DIR / "data.json").write_text(json.dumps(data))
    for path, content in frontend.items():
        target = OUT_DIR / "static" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def main():
    frontend = fetch_frontend()

    data = wait_for_data()
    print(f"Got {len(data['header_infos'])} headers from {FORK_OBSERVER_URL}")
    data["nodes"].append(dataset_node(data["header_infos"]))

    write_site(frontend, data)
    print(f"Generated {OUT_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
