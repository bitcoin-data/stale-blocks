# checks that:
# - file has only three columns (height, hash, header)
# - height is an integer > 0
# - file is ordered by block height in descending order
# - header hashes match header (by hashing)

import csv
import hashlib

EXPECTED_COLUMNS = 3

def dsha256(d):
    h1 = hashlib.sha256(d).digest()
    h2 = hashlib.sha256(h1).digest()
    return h2

with open("stale-blocks.csv", "r") as f:
    last_height = None
    reader = csv.reader(f)
    for row in reader:
        print("checking row:", row)
        assert(len(row) == EXPECTED_COLUMNS)

        height = int(row[0])
        assert(height > 0)

        if last_height != None:
            assert(last_height >= height)

        header_hash = row[1]
        header = row[2]

        if header != "":
            calculated_header_hash = bytes(reversed(dsha256(bytes.fromhex(header)))).hex()
            assert(header_hash == calculated_header_hash)

print("sanity-check successful")
