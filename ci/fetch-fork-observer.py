# Fetches recent stale blocks from one or more fork-observer instances and
# merges them into stale-blocks.csv. Where an instance still has the full block,
# it's stored in the blocks directory.
#
# The API endpoints used are:
#
#   /api/<network>/stale.json        the most recent stale blocks an instance
#                                    knows about (height, hash, header)
#   /api/<network>/block/<hash>/bin  the full stale block, if the instance
#                                    could get it from one of its nodes

import csv
import json
import os
import urllib.error
from urllib.request import urlopen

# The instances to fetch from, each with the id of the network to fetch the
# stale blocks for. The ids are instance specific, see /api/networks.json.
INSTANCES = [
    ("https://fork.observer", 1),
    ("https://public.peer.observer/forks/", 1),
    ("https://demo.peer.observer/forks/", 1),
]

CSV_FILE = "stale-blocks.csv"
BLOCKS_DIR = "blocks"
TIMEOUT_S = 60


def fetch(base_url, network, path):
    url = f"{base_url.rstrip('/')}/api/{network}/{path}"
    try:
        with urlopen(url, timeout=TIMEOUT_S) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Failed fetching {url}: {e}")
        return None


# The height of the active chain tip, as seen by the instance.
def active_height(base_url, network):
    response = fetch(base_url, network, "data.json")
    if response is None:
        return None

    heights = [
        tip["height"]
        for node in json.loads(response)["nodes"]
        for tip in node["tips"]
        if tip["status"] == "active"
    ]
    return max(heights, default=None)


def load_existing_rows(filename):
    rows = {}
    if not os.path.exists(filename):
        return rows

    with open(filename, "r", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header row
        for row in reader:
            rows[row[1]] = (int(row[0]), row[1], row[2])
    return rows


def collect_stale_blocks():
    blocks = {}
    for base_url, network in INSTANCES:
        tip_height = active_height(base_url, network)
        if tip_height is None:
            print(f"No active chain tip known for {base_url}, skipping it")
            continue

        response = fetch(base_url, network, "stale.json")
        if response is None:
            continue

        print(f"Fetched from {base_url} (active chain tip at {tip_height})")
        for block in json.loads(response)["stale_blocks"]:
            # A block that the active chain hasn't grown past yet can still end
            # up being part of it. Leave it for a later run.
            if block["height"] >= tip_height:
                print(f"Skipping {block['height']} {block['hash']}: race with the active chain")
                continue

            blocks[block["hash"]] = (block["height"], block["hash"], block["header"])
    return blocks


def fetch_raw_block(block_hash):
    print(f"Trying to fetch raw block {block_hash}..")
    for base_url, network in INSTANCES:
        raw_block = fetch(base_url, network, f"block/{block_hash}/bin")
        if raw_block is not None:
            return raw_block

    print(f"Failed fetching raw block {block_hash}")
    return None


def main():
    existing = load_existing_rows(CSV_FILE)
    new = {h: b for h, b in collect_stale_blocks().items() if h not in existing}

    if not new:
        print("No new stale blocks.")
        return

    # Sorted by height, then hash, both descending. The hash tie-break keeps the
    # order stable no matter in which run a block at a known height shows up.
    sorted_rows = sorted({**existing, **new}.values(), key=lambda x: (x[0], x[1]), reverse=True)
    with open(CSV_FILE, "w") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["height", "hash", "header"])
        writer.writerows(sorted_rows)
    print(f"Wrote {len(new)} new stale block(s).")

    for height, block_hash, _ in new.values():
        block_path = os.path.join(BLOCKS_DIR, f"{height}-{block_hash}.bin")
        if os.path.exists(block_path):
            continue  # skip existing

        raw_block = fetch_raw_block(block_hash)
        if raw_block:
            with open(block_path, "wb") as f:
                f.write(raw_block)
            print(f"Saved raw block {block_hash} ({len(raw_block)} bytes)")


if __name__ == "__main__":
    main()
