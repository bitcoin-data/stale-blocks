#!/usr/bin/env python3
# Checks stale-blocks.csv and the block files against the consensus rules that
# sanity-check.py cannot reach on its own, by handing them to a Bitcoin Core
# node.
#
# sanity-check.py can only check what a row carries on its own: a header in
# isolation, and the first 80 bytes of a block file. The rest needs either the
# chain around a block or the whole block, and a node knows how to do both.
#
# The node never joins the P2P network. Start it with
#
#   bitcoind -daemonwait -connect=0 -blocksonly -prune=550
#
# and this script gives it the mainnet header chain over HTTP, then the file's
# own headers and blocks. Nothing polls, and no block is ever downloaded.
#
# submitheader covers the rules that need the chain around a block:
# - nBits is the difficulty the chain required at that point
# - the timestamp beats the median-time-past of the block's ancestors
# - the version meets the BIP34/BIP66/BIP65 minimum for its height
# Core derives a block's height from its parent, so an accepted header also
# says whether the height recorded in the CSV is the block's real one.
#
# submitblock covers the rules that need the whole block, but not the chain's
# unspent outputs:
# - every transaction hashes into the merkle root committed in the header,
#   which is what makes the rest of the block file trustworthy at all
# - no duplicate transactions, coinbase first and only once
# - block size, weight and signature operation limits
# - CheckTransaction on each transaction: no empty inputs or outputs, no value
#   above MAX_MONEY or summing past it, no null non-coinbase inputs
# - the witness commitment matches the witness merkle root
# - the coinbase scriptSig carries the height BIP34 requires
# - no transaction is still non-final at this height and median-time-past
#
# What neither reaches is anything needing the unspent output set as it stood
# at that height: script validation, whether the inputs existed, double spends,
# and whether the coinbase claimed the right subsidy and fees. That wants a
# fully synced chain rather than a header chain. Nor can either say anything
# about the rows that carry no header.
#
# Usage: ci/check-with-bitcoind.py [header-chain-file]
# The header chain is downloaded unless a local copy is given.

import base64
import csv
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

CSV_FILE = "stale-blocks.csv"
BLOCKS_DIR = "blocks"

RPC_URL = os.environ.get("BITCOIN_RPC_URL", "http://127.0.0.1:8332")
RPC_TIMEOUT_S = 600
BATCH = 500

# Every header from genesis onwards, 80 bytes each, behind a 10-byte prefix.
HEADER_CHAIN_URL = "https://block-dn.org/headers/import/latest"
PREFIX_LEN = 10
HEADER_LEN = 80
IMPORT_BATCH = 2000
DOWNLOAD_RETRIES = 3

# block-dn.org refuses urllib's default user agent with a 403, and saying who
# is calling is the polite thing to do when leaning on someone else's bandwidth.
USER_AGENT = "bitcoin-data/stale-blocks CI"

# Core's answer when it doesn't know a header's parent. Not a verdict on the
# header: the block it builds on is neither on the main chain nor in this file,
# so there is nothing to check it against.
UNKNOWN_PARENT = "Must submit previous header"

# submitblock's answers for a block it did not reject. A block that reaches the
# end of the checks without being connected to the chain gets no verdict, and
# Core says so; one it already has, it calls a duplicate. Neither is a
# rejection, and a rejection is always a reason string instead.
BLOCK_NOT_REJECTED = ("inconclusive", "duplicate")


def credentials():
    if "BITCOIN_RPC_AUTH" in os.environ:
        return os.environ["BITCOIN_RPC_AUTH"]
    datadir = os.environ.get("BITCOIN_DATADIR", os.path.expanduser("~/.bitcoin"))
    with open(os.path.join(datadir, ".cookie")) as f:
        return f.read().strip()


def rpc_batch(auth, calls):
    # calls is a sequence of (method, params). Core works through a batch in
    # order, which matters when a call depends on an earlier one, so the answers
    # are put back in the order they were asked rather than the order they came.
    body = json.dumps([
        {"jsonrpc": "2.0", "id": i, "method": method, "params": params}
        for i, (method, params) in enumerate(calls)
    ]).encode()
    request = urllib.request.Request(RPC_URL, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(request, timeout=RPC_TIMEOUT_S) as response:
        return sorted(json.loads(response.read()), key=lambda answer: answer["id"])


def rpc_call(auth, method, *params):
    return rpc_batch(auth, [(method, list(params))])[0]


def error_message(answer):
    # The reason a call failed, or None if it didn't.
    return answer["error"]["message"] if answer.get("error") else None


def fetch_header_chain(path):
    if path:
        with open(path, "rb") as f:
            return f.read()

    request = urllib.request.Request(HEADER_CHAIN_URL, headers={"User-Agent": USER_AGENT})
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=RPC_TIMEOUT_S) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == DOWNLOAD_RETRIES - 1:
                sys.exit(f"could not fetch {HEADER_CHAIN_URL}: {e}")
            print(f"  fetching the header chain failed ({e}), retrying")
            time.sleep(2 ** attempt)


def import_headers(auth, blob):
    # Serving this chain is not a position of trust. Core checks each header's
    # proof of work, that its difficulty is the one the chain required, and that
    # it builds on the header before it, so a bad chain cannot put headers into
    # the node that Core would not otherwise accept. It could stop early, which
    # is what require_chain_reaches is for.
    blob = blob[PREFIX_LEN:]
    if len(blob) % HEADER_LEN != 0:
        sys.exit(f"header chain: {len(blob)} bytes after the prefix is not a whole number of headers")

    # The node starts life with the genesis block, and a header whose parent it
    # doesn't know is refused, so genesis is skipped rather than submitted.
    headers = [blob[i:i + HEADER_LEN].hex() for i in range(HEADER_LEN, len(blob), HEADER_LEN)]
    for i in range(0, len(headers), IMPORT_BATCH):
        for answer in rpc_batch(auth, [("submitheader", [h]) for h in headers[i:i + IMPORT_BATCH]]):
            error = error_message(answer)
            if error:
                sys.exit(f"header chain: header {i + answer['id']}: {error}")

    print(f"  imported {len(headers)} headers")


def require_chain_reaches(auth, height):
    # Every check here is made against a block's parent, so the node's chain has
    # to reach the highest block in the file. A chain that ends too soon would
    # otherwise report the newest rows as having an unknown parent, which this
    # script forgives rather than fails on.
    chain = rpc_call(auth, "getblockchaininfo")["result"]
    if chain["headers"] < height:
        sys.exit(f"node has {chain['headers']} headers, but {CSV_FILE} goes up to {height}")


def read_rows():
    with open(CSV_FILE, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return [(int(row[0]), row[1], row[2]) for row in reader]


def check_headers(auth, rows):
    # Submit parents before children: some of these blocks build on another
    # block in this file, and Core rejects a header whose parent it hasn't seen.
    # Ascending height does that.
    headers = sorted(row for row in rows if row[2])
    print(f"checking {len(headers)} headers, {len(rows) - len(headers)} rows carry no header")

    problems, unchecked, accepted = [], [], []
    for i in range(0, len(headers), BATCH):
        chunk = headers[i:i + BATCH]
        answers = rpc_batch(auth, [("submitheader", [header]) for _, _, header in chunk])
        for (height, block_hash, _), answer in zip(chunk, answers):
            error = error_message(answer)
            if error is None:
                accepted.append((height, block_hash))
            elif UNKNOWN_PARENT in error:
                parent = error.split("(")[1].split(")")[0]
                unchecked.append(f"{height} {block_hash}: builds on {parent}, which is unknown")
            else:
                problems.append(f"{height} {block_hash}: {error}")

    # Core placed each accepted header at a height of its own working, taken
    # from its parent. It should be the one the file claims.
    for i in range(0, len(accepted), BATCH):
        chunk = accepted[i:i + BATCH]
        answers = rpc_batch(auth, [("getblockheader", [h]) for _, h in chunk])
        for (height, block_hash), answer in zip(chunk, answers):
            error = error_message(answer)
            if error:
                problems.append(f"{height} {block_hash}: getblockheader failed: {error}")
            elif answer["result"]["height"] != height:
                problems.append(
                    f"{height} {block_hash}: recorded at height {height}, "
                    f"but its parent puts it at {answer['result']['height']}"
                )

    print(f"  {len(accepted)} accepted, at the height recorded for them")
    return problems, unchecked


def check_blocks(auth):
    # Ascending height again, so a block building on another block here is
    # submitted after it.
    paths = sorted(glob.glob(os.path.join(BLOCKS_DIR, "*.bin")),
                   key=lambda path: int(os.path.basename(path).split("-")[0]))
    print(f"checking {len(paths)} block files")

    problems = []
    for path in paths:
        with open(path, "rb") as f:
            block = f.read()
        # One block per call: a batch of these would be hundreds of megabytes.
        answer = rpc_call(auth, "submitblock", block.hex())
        error = error_message(answer)
        if error:
            problems.append(f"{os.path.basename(path)}: {error}")
        elif answer["result"] not in BLOCK_NOT_REJECTED:
            problems.append(f"{os.path.basename(path)}: {answer['result']}")

    print(f"  {len(paths) - len(problems)} accepted")
    return problems


def main():
    rows = read_rows()
    auth = credentials()

    print("importing the mainnet header chain")
    import_headers(auth, fetch_header_chain(sys.argv[1] if len(sys.argv) > 1 else None))
    require_chain_reaches(auth, max(height for height, _, _ in rows))

    header_problems, unchecked = check_headers(auth, rows)
    block_problems = check_blocks(auth)

    if unchecked:
        # Not failures. The parent is a stale block nobody recorded, so these
        # rows are out of this check's reach rather than wrong.
        print(f"\n{len(unchecked)} header(s) could not be checked:")
        for u in unchecked:
            print(f"  {u}")

    problems = header_problems + block_problems
    if problems:
        print("\ncheck-with-bitcoind failed:")
        for problem in problems:
            print(f"  {problem}")
        sys.exit(1)

    print("\ncheck-with-bitcoind successful")


if __name__ == "__main__":
    main()
