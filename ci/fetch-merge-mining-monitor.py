# Fetches recent stale blocks from merge-mining-monitor and merges them into
# stale-blocks.csv.
#
# The API endpoints used are:
#
#   /api/v1/sources          source sync state, including the active Bitcoin
#                            Core chain tip height
#   /api/v1/navigator/stale  the most recent stale blocks (height, hash)
#   /api/v1/block/<hash>     block details, including the header fields

import csv
import json
import os
import struct
import sys
import urllib.error
from urllib.request import Request, urlopen

BASE_URL = "https://mmm.deadmanoz.xyz"
SOURCE_CODE = "live-chaintip:bitcoin:core"
STALE_LIMIT = 50
CSV_FILE = "stale-blocks.csv"
TIMEOUT_S = 60
USER_AGENT = "bitcoin-data/stale-blocks CI"


def fetch(path):
    url = f"{BASE_URL.rstrip('/')}/api/v1/{path}"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"Failed fetching {url}: {e}")
        return None


# The height of the active chain tip, as seen by the instance.
def active_height():
    response = fetch("sources")
    if response is None:
        return None

    for source in response.get("sources", []):
        if source.get("code") == SOURCE_CODE:
            sync = source.get("sync", {})
            if sync.get("error_code") is not None:
                return None
            return sync.get("progress_height")
    return None


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


def header_hex(header):
    return (
        struct.pack("<i", header["version"])
        + bytes.fromhex(header["prev_hash"])[::-1]
        + bytes.fromhex(header["merkle_root"])[::-1]
        + struct.pack("<I", header["time"])
        + bytes.fromhex(header["bits"])[::-1]
        + struct.pack("<I", header["nonce"])
    ).hex()


def collect_stale_blocks(known_hashes):
    blocks = {}
    tip_height = active_height()
    if tip_height is None:
        print(f"No active chain tip known for {BASE_URL}, skipping it")
        return blocks

    response = fetch(f"navigator/stale?limit={STALE_LIMIT}")
    if response is None:
        return blocks

    print(f"Fetched from {BASE_URL} (active chain tip at {tip_height})")
    for item in response["items"]:
        height = item["position"]["max"]
        block_hash = item["primary_hash"]

        # A block that the active chain hasn't grown past yet can still end
        # up being part of it. Leave it for a later run.
        if height >= tip_height:
            print(f"Skipping {height} {block_hash}: race with the active chain")
            continue

        if block_hash in known_hashes:
            continue

        detail = fetch(f"block/{block_hash}")
        if detail is None:
            continue

        header = header_hex(detail["block"]["header"])
        blocks[block_hash] = (height, block_hash, header)
    return blocks


def main():
    existing = load_existing_rows(CSV_FILE)
    known_hashes = set(existing)
    for extra_csv in sys.argv[1:]:
        known_hashes.update(load_existing_rows(extra_csv))

    new = collect_stale_blocks(known_hashes)
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


if __name__ == "__main__":
    main()
