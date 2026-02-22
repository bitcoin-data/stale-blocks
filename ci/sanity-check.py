#!/usr/bin/env python3
# checks that:
# - file has only three columns (height, hash, header)
# - height is an integer > 0
# - file is ordered by block height in descending order
# - hash is 32-byte hex
# - header is empty or 80-byte hex and hashes to hash
# - hashes are unique
# - block files (if present) start with a matching 80-byte header
# - missing/mismatching headers report the expected header

import csv
import hashlib
import os
import sys

EXPECTED_COLUMNS = 3
HEADER_LEN = 80


def dsha256(d):
    h1 = hashlib.sha256(d).digest()
    h2 = hashlib.sha256(h1).digest()
    return h2


def try_parse_hex(field, value, expected_len_bytes, context, problems, required=False):
    if value == "":
        if required:
            problems.append(f"{context}: {field} is required but empty")
        return None

    try:
        b = bytes.fromhex(value)
    except ValueError:
        problems.append(f"{context}: {field} is not hex: {value}")
        return None

    if expected_len_bytes is not None and len(b) != expected_len_bytes:
        problems.append(f"{context}: {field} has wrong length: expected {expected_len_bytes} bytes, got {len(b)}")
        return None

    return b


hash_count = dict()
total_headers = 0
total_blocks = 0
problems = []

with open("stale-blocks.csv", "r", newline="") as f:
    last_height = None
    reader = csv.reader(f)
    next(reader, None)  # Skip header row
    for row_i, row in enumerate(reader, start=2):
        if len(row) != EXPECTED_COLUMNS:
            problems.append(f"stale-blocks.csv:{row_i}: expected {EXPECTED_COLUMNS} columns, got {len(row)}: {row}")
            continue

        try:
            height = int(row[0])
            if height <= 0:
                problems.append(f"stale-blocks.csv:{row_i}: height must be > 0: {height}")
        except ValueError:
            problems.append(f"stale-blocks.csv:{row_i}: invalid height: {row[0]}")
            continue

        if last_height is not None and last_height < height:
            problems.append(f"stale-blocks.csv:{row_i}: file not ordered by height descending: {last_height} < {height}")
        last_height = height

        header_hash, header = row[1], row[2]

        try_parse_hex("hash", header_hash, 32, f"stale-blocks.csv:{row_i}", problems, required=True)

        if header:
            header_bytes = try_parse_hex("header", header, HEADER_LEN, f"stale-blocks.csv:{row_i}", problems)
            if header_bytes is not None:
                total_headers += 1
                calculated_header_hash = bytes(reversed(dsha256(header_bytes))).hex()
                if header_hash != calculated_header_hash:
                    problems.append(f"stale-blocks.csv:{row_i}: header hash mismatch: {header_hash} != {calculated_header_hash}")

        hash_count[header_hash] = hash_count.get(header_hash, 0) + 1

        blockfile = f"blocks/{height}-{header_hash}.bin"
        if os.path.exists(blockfile):
            total_blocks += 1
            with open(blockfile, "rb") as block:
                header_bytes = block.read(HEADER_LEN)
            if len(header_bytes) != HEADER_LEN:
                problems.append(f"{blockfile}: expected {HEADER_LEN} header bytes, got {len(header_bytes)}")
                continue

            calculated_header_hash = bytes(reversed(dsha256(header_bytes))).hex()
            if header_hash != calculated_header_hash:
                problems.append(f"{blockfile}: header hash mismatch: {header_hash} != {calculated_header_hash}")

            expected_header = header_bytes.hex()
            if header:
                if header != expected_header:
                    problems.append(f"stale-blocks.csv:{row_i}: header does not match blockfile header; expected {expected_header}")
            else:
                problems.append(f"stale-blocks.csv:{row_i}: missing header for {height} {header_hash}; expected {expected_header}")

for header_hash, count in hash_count.items():
    if count > 1:
        problems.append(f"The hash {header_hash} appeared {count} times. It should only appear once.")

if problems:
    print("sanity-check failed:")
    for p in problems:
        print(p)
    sys.exit(1)

print("sanity-check successful")
print(f"  {total_headers} headers, {total_blocks} block files")
