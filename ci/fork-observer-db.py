#!/usr/bin/env python3

# Builds the SQLite database that a fork-observer instance renders the stale
# block header tree from. The main chain headers come from block-dn.org, the
# stale headers from stale-blocks.csv. The result is the `headers` table
# fork-observer itself would have written, so it can start from it directly:
#
#   https://github.com/0xB10C/fork-observer/blob/main/src/db.rs
#
# Both have to be in the database before fork-observer starts. It links a
# header to its parent only when the parent is already known, so stale headers
# loaded before the main chain would stay disconnected and be drawn in the
# wrong place.
#
# Usage: fork-observer-db.py <output.sqlite> [--cache-dir DIR]
#
# --cache-dir keeps the downloaded block-dn header files around for repeated
# local runs. The CI doesn't need it.

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "stale-blocks.csv"

BLOCK_DN_URL = "https://block-dn.org"
# block-dn serves its headers in files of 100'000 headers, 80 bytes each. The
# public instances all use this size (see /status: entries_per_header_file).
HEADERS_PER_FILE = 100_000
HEADER_SIZE = 80
TIMEOUT_S = 120
USER_AGENT = "stale-blocks-ci (https://github.com/bitcoin-data/stale-blocks)"

GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"

# The id fork-observer's config gives the network. Must match
# ci/fork-observer/config.toml.
NETWORK_ID = 1

# Identical to fork-observer's CREATE_STMT_TABLE_HEADERS. The hash and header
# columns hold hex strings, as fork-observer writes them.
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS headers (
    height     INT,
    network    INT,
    hash       BLOB,
    header     BLOB,
    miner      TEXT,
    PRIMARY KEY (network, hash, header)
)
"""


def block_hash(header):
    return hashlib.sha256(hashlib.sha256(header).digest()).digest()[::-1].hex()


def prev_hash(header):
    return header[4:36][::-1].hex()


def fetch(path):
    # block-dn is behind Cloudflare, which rejects the default Python user agent.
    request = Request(f"{BLOCK_DN_URL}{path}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


def fetch_header_file(start, cache_dir, sealed):
    # Only sealed files (100'000 headers) are cached: the last file still grows
    # with every block.
    cached = cache_dir / f"headers-{start}.bin" if cache_dir and sealed else None
    if cached and cached.exists():
        return cached.read_bytes()

    print(f"Fetching {BLOCK_DN_URL}/headers/{start}..")
    data = fetch(f"/headers/{start}")
    if len(data) % HEADER_SIZE != 0:
        sys.exit(f"headers file {start} has {len(data)} bytes, not a multiple of {HEADER_SIZE}")
    if sealed and len(data) != HEADERS_PER_FILE * HEADER_SIZE:
        sys.exit(f"headers file {start} holds {len(data) // HEADER_SIZE} headers, expected {HEADERS_PER_FILE}")

    if cached:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data


# Downloads the main chain headers from block-dn and checks that they link up
# to the genesis block. block-dn is an untrusted source, so a download that
# doesn't form a chain from genesis to the tip it reports is refused.
def main_chain_headers(cache_dir):
    status = json.loads(fetch("/status"))
    tip_height = status["best_block_height"]
    tip_hash = status["best_block_hash"]
    if status.get("entries_per_header_file", HEADERS_PER_FILE) != HEADERS_PER_FILE:
        sys.exit(f"block-dn uses {status['entries_per_header_file']} headers per file, expected {HEADERS_PER_FILE}")
    print(f"block-dn tip: {tip_height} {tip_hash}")

    headers = []  # (height, hash, header hex)
    expected_prev = "00" * 32
    last_file_start = tip_height - tip_height % HEADERS_PER_FILE
    for start in range(0, last_file_start + 1, HEADERS_PER_FILE):
        data = fetch_header_file(start, cache_dir, sealed=start < last_file_start)
        for i in range(0, len(data), HEADER_SIZE):
            header = data[i:i + HEADER_SIZE]
            if prev_hash(header) != expected_prev:
                sys.exit(f"header at height {start + i // HEADER_SIZE} doesn't build on the previous one")
            expected_prev = block_hash(header)
            headers.append((start + i // HEADER_SIZE, expected_prev, header.hex()))

    if headers[0][1] != GENESIS_HASH:
        sys.exit(f"first header is {headers[0][1]}, not the genesis block")
    # The tip can move between the /status request and the file downloads, so
    # the chain may end a few blocks past the reported tip. It must not end
    # before it, and the reported tip must be in it.
    if headers[-1][0] < tip_height or headers[tip_height][1] != tip_hash:
        sys.exit(f"downloaded chain ends at {headers[-1][0]}, doesn't contain the reported tip {tip_height} {tip_hash}")

    print(f"Got {len(headers)} main chain headers up to height {headers[-1][0]}")
    return headers


# The stale headers from the CSV that can be placed in the tree: their hash has
# to match the header, the parent has to be known (main chain or another stale
# header) and the height has to be the parent's plus one. Rows without a header
# can't be placed at all.
def stale_headers(known):
    with open(CSV_PATH, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["header"]]

    headers = []
    pending = []
    for row in rows:
        header = bytes.fromhex(row["header"])
        if block_hash(header) != row["hash"]:
            print(f"Skipping {row['height']} {row['hash']}: header doesn't hash to the block hash")
            continue
        if row["hash"] in known:
            print(f"Skipping {row['height']} {row['hash']}: is on the main chain")
            continue
        pending.append((int(row["height"]), row["hash"], header))

    # A stale header's parent can be another stale header further down the
    # CSV, so keep going until nothing new can be placed.
    placed = True
    while placed and pending:
        placed = False
        remaining = []
        for height, hash, header in pending:
            parent_height = known.get(prev_hash(header))
            if parent_height is None:
                remaining.append((height, hash, header))
                continue
            if parent_height + 1 != height:
                print(f"Skipping {height} {hash}: parent is at height {parent_height}")
                continue
            known[hash] = height
            headers.append((height, hash, header.hex()))
            placed = True
        pending = remaining

    for height, hash, header in pending:
        print(f"Skipping {height} {hash}: parent {prev_hash(header)} is unknown")

    print(f"Got {len(headers)} stale headers from {CSV_PATH.name} ({len(rows) - len(headers)} skipped)")
    return headers


def write_db(path, headers):
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.execute(CREATE_TABLE)
    db.executemany(
        "INSERT OR IGNORE INTO headers (height, network, hash, header, miner) VALUES (?, ?, ?, ?, ?)",
        ((height, NETWORK_ID, hash, header, "") for height, hash, header in headers),
    )
    db.commit()
    db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()

    main_chain = main_chain_headers(args.cache_dir)
    known = {hash: height for height, hash, _ in main_chain}
    stale = stale_headers(known)

    write_db(args.output, main_chain + stale)
    print(f"Wrote {len(main_chain) + len(stale)} headers to {args.output}")


if __name__ == "__main__":
    main()
