#!/usr/bin/env python3
# Validates stale-blocks.csv and the block files it references.
#
# How much of a row can be checked depends on how much of the block it carries,
# so the checks are grouped below by the evidence they need. Each group is in
# addition to the ones above it. A row that is only a hash cannot be checked
# for anything beyond its shape, not even proof of work.
#
# every row:
# - file has only three columns (height, hash, header)
# - height is an integer > 0
# - file is ordered by block height in descending order
# - hash is 32-byte hex
# - hashes are unique
#
# rows that also carry an 80-byte header:
# - header is 80-byte hex and hashes to hash
# - header satisfies the PoW target encoded in nBits
# - header version meets the minimum enforced by BIP34, BIP66 and BIP65 at that height
#
# rows that also carry a block file:
# - block file starts with a matching 80-byte header
# - header column equals it, or is reported as missing along with the expected value
# - the coinbase scriptSig is 2 to 100 bytes
# - the coinbase scriptSig starts with the serialized height, from 224413 for
#   version 2 and newer blocks and from 227931 for every block
#
# The header checks read the column, not the block file, so an empty column
# skips them even when a block file is present. It cannot slip through: the
# empty column is itself reported as a missing header.
#
# These rules are necessary conditions: a block that fails one was invalid at
# the row's height and so was never stale. Passing them is weaker, only that
# nothing in the bytes read here shows otherwise. Heights are taken on trust,
# except where the BIP34 check corroborates them against the coinbase.
#
# The boundary is the bytes read: a header, plus at most the first 256 bytes
# of a block file. Whole-block rules (merkle root, coinbase position, size and
# weight, CheckTransaction, witness commitment, legacy sigops) are derivable
# from committed bytes and left for a follow-up. Rules needing chain context
# (median-time-past, expected difficulty) or the outputs being spent (all
# script-level rules, including the ones BIP66 and BIP65 actually introduced)
# are out of reach offline. time-too-new is also skipped: Core treats it as a clock
# condition, not block invalidity.

import csv
import hashlib
import os
import sys

EXPECTED_COLUMNS = 3
HEADER_LEN = 80

# Mainnet consensus deployment heights. BIP34 activated in two stages, which it
# calls the 75% and 95% rules: from 224413 the height prefix is enforced for
# version 2 and newer blocks; from 227931 version 1 blocks are rejected
# outright, making the prefix mandatory for every block from there on.
# Core carries only the second, as consensus.BIP34Height in
# src/kernel/chainparams.cpp alongside BIP66Height and BIP65Height. The first
# appears only in doc/bips.md: nothing on the main chain in that window
# violates it, so Core never needed to enforce it.
BIP34_VERSION_2_HEIGHT = 224413
BIP34_HEIGHT = 227931
BIP66_HEIGHT = 363725
BIP65_HEIGHT = 388381

# Consensus bounds on the coinbase scriptSig, enforced at every height. Core
# rejects a block breaking them with bad-cb-length, in CheckTransaction in
# src/consensus/tx_check.cpp. They have no BIP number.
MIN_COINBASE_SCRIPTSIG = 2
MAX_COINBASE_SCRIPTSIG = 100

# Enough of a block file to reach the end of any legal-length coinbase
# scriptSig: the header, the coinbase's version, the segwit marker and flag,
# the null outpoint and a 100-byte maximum scriptSig, plus the CompactSize
# counts between them, 249 bytes in all with every count at its maximal 9-byte
# width. The rest of the block is never read; an oversized scriptSig is still
# caught, since its declared length is known first.
BLOCK_PREFIX_LEN = 256


def dsha256(d):
    h1 = hashlib.sha256(d).digest()
    h2 = hashlib.sha256(h1).digest()
    return h2


def target_from_bits(bits):
    # Expand ordinary positive Bitcoin compact nBits values (4 bytes) to a
    # 256-bit target integer. High byte is the size/exponent; low 3 bytes are
    # the mantissa.
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def header_version_error(height, version):
    # Core rejects outdated block versions once each deployment is active:
    # BIP34 requires version 2, BIP66 version 3 and BIP65 version 4. nVersion is
    # a signed 32-bit field, so a version-rolled header with the high bit set
    # reads as negative and falls below every one of these minimums.
    if height >= BIP65_HEIGHT and version < 4:
        rule = f"BIP65 requires version 4 from height {BIP65_HEIGHT}"
    elif height >= BIP66_HEIGHT and version < 3:
        rule = f"BIP66 requires version 3 from height {BIP66_HEIGHT}"
    elif height >= BIP34_HEIGHT and version < 2:
        rule = f"BIP34 requires version 2 from height {BIP34_HEIGHT}"
    else:
        return None
    # Report the field both ways round: a version-rolled 0xe0000000 reads as
    # -536870912 once signed, which looks like corruption on its own. Masking
    # back to 32 bits recovers the bytes as they appear in the header.
    unsigned = version & 0xFFFFFFFF
    return f"block version {version} (0x{unsigned:08x}) is below the minimum: {rule}"


def read_compact_size(data, offset):
    # Read the variable-length integer Bitcoin uses for counts and lengths: a
    # first byte under 0xFD is the value itself, while 0xFD, 0xFE and 0xFF mean
    # 2, 4 or 8 little-endian bytes follow. Returns the value and where the next
    # field starts, or (None, offset) when the field does not fit in data.
    if offset >= len(data):
        return None, offset
    first = data[offset]
    if first < 0xFD:
        return first, offset + 1
    width = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
    if offset + 1 + width > len(data):
        return None, offset
    return int.from_bytes(data[offset + 1:offset + 1 + width], "little"), offset + 1 + width


def coinbase_scriptsig(data):
    # Walk the front of a serialized block to the coinbase scriptSig. Returns
    # (scriptSig, declared length), both None when the data is not shaped like
    # a coinbase. A scriptSig running past the bytes read yields a None
    # scriptSig but a real length: either the declared length is illegal, or
    # the data itself ends before a legal scriptSig is complete.

    # The header is followed by the number of transactions in the block. The
    # coinbase is always the first of them.
    tx_count, offset = read_compact_size(data, HEADER_LEN)
    if not tx_count:
        return None, None

    offset += 4  # the coinbase transaction's version

    # What follows the version is either the segwit marker and flag or, in a
    # legacy transaction, the input count. A transaction with no inputs is
    # invalid, so a 0x00 here can only be the marker, never a count.
    marker_flag = data[offset:offset + 2]
    if len(marker_flag) == 2 and marker_flag[0] == 0x00 and marker_flag[1] != 0x00:
        offset += 2

    # A coinbase has exactly one input, however many outputs it pays to.
    input_count, offset = read_compact_size(data, offset)
    if input_count != 1:
        return None, None

    # That input spends nothing, so its outpoint is null: a zero hash and an
    # index of 0xffffffff. Anything else means this is not a coinbase.
    outpoint = data[offset:offset + 36]
    if len(outpoint) != 36 or outpoint[:32] != bytes(32) or outpoint[32:] != b"\xff\xff\xff\xff":
        return None, None
    offset += 36

    # The scriptSig is length-prefixed, so its length arrives before its bytes.
    script_len, offset = read_compact_size(data, offset)
    if script_len is None:
        return None, None

    scriptsig = data[offset:offset + script_len]
    if len(scriptsig) != script_len:
        return None, script_len
    return scriptsig, script_len


def header_version(header_bytes):
    # nVersion is the first four bytes of the header, little-endian and signed.
    return int.from_bytes(header_bytes[0:4], "little", signed=True)


def bip34_height_prefix(height):
    # The exact push Core builds with CScript() << height for every height this
    # check runs on, and compares against the front of the coinbase scriptSig,
    # rejecting a mismatch with bad-cb-height in ContextualCheckBlock in
    # src/validation.cpp. E.g. height 227931 (0x037a5b) becomes 03 5b7a03.
    # Core has shorter forms for 0 and for 1 to 16 (OP_0, and OP_1 through
    # OP_16), but the check starts at 224413, so those never come up.

    # A CScriptNum is the value's bytes, little-endian, with no leading zeros:
    # CScriptNum::serialize in src/script/script.h.
    num = height.to_bytes((height.bit_length() + 7) // 8, "little")

    # The high bit of the last byte is the sign bit. A height whose top byte
    # would set it gets a zero byte appended, keeping the number positive.
    if num[-1] & 0x80:
        num += b"\x00"

    # Opcodes 0x01..0x4b push that many following bytes, so the push opcode is
    # simply the length.
    return bytes([len(num)]) + num


def bip34_height_error(height, version, scriptsig):
    # BIP34 in its two stages: from 224413 a version 2 or newer block must start
    # its coinbase scriptSig with the serialized height, and from 227931 version
    # 1 is invalid too, so the prefix is mandatory regardless of version.
    if height < BIP34_VERSION_2_HEIGHT:
        return None
    if height < BIP34_HEIGHT and version < 2:
        return None
    prefix = bip34_height_prefix(height)
    if scriptsig.startswith(prefix):
        return None
    return f"coinbase scriptSig does not begin with the BIP34 height push {prefix.hex()}"


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
total_rows = 0
total_headers = 0
total_blocks = 0
total_coinbases = 0
total_hash_only = 0
problems = []

with open("stale-blocks.csv", "r", newline="") as f:
    last_height = None
    reader = csv.reader(f)
    next(reader, None)  # Skip header row
    for row_i, row in enumerate(reader, start=2):
        total_rows += 1
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
        if not header:
            total_hash_only += 1

        try_parse_hex("hash", header_hash, 32, f"stale-blocks.csv:{row_i}", problems, required=True)

        if header:
            header_bytes = try_parse_hex("header", header, HEADER_LEN, f"stale-blocks.csv:{row_i}", problems)
            if header_bytes is not None:
                total_headers += 1
                calculated_header_hash = bytes(reversed(dsha256(header_bytes))).hex()
                if header_hash != calculated_header_hash:
                    problems.append(f"stale-blocks.csv:{row_i}: header hash mismatch: {header_hash} != {calculated_header_hash}")
                else:
                    bits = int.from_bytes(header_bytes[72:76], "little")
                    target = target_from_bits(bits)
                    if int(calculated_header_hash, 16) > target:
                        problems.append(
                            f"stale-blocks.csv:{row_i}: header does not satisfy PoW target: "
                            f"hash {calculated_header_hash} > target {target:064x} (nBits {bits:08x})"
                        )

                    version_error = header_version_error(height, header_version(header_bytes))
                    if version_error is not None:
                        problems.append(f"stale-blocks.csv:{row_i}: {version_error}")

        hash_count[header_hash] = hash_count.get(header_hash, 0) + 1

        blockfile = f"blocks/{height}-{header_hash}.bin"
        if os.path.exists(blockfile):
            total_blocks += 1
            with open(blockfile, "rb") as block:
                block_prefix = block.read(BLOCK_PREFIX_LEN)
            header_bytes = block_prefix[:HEADER_LEN]
            if len(header_bytes) != HEADER_LEN:
                problems.append(f"{blockfile}: expected {HEADER_LEN} header bytes, got {len(header_bytes)}")
                continue

            calculated_header_hash = bytes(reversed(dsha256(header_bytes))).hex()
            if header_hash != calculated_header_hash:
                problems.append(f"{blockfile}: header hash mismatch: {header_hash} != {calculated_header_hash}")

            scriptsig, scriptsig_len = coinbase_scriptsig(block_prefix)
            if scriptsig_len is None:
                problems.append(f"{blockfile}: could not read a coinbase transaction from the block")
            else:
                total_coinbases += 1
                if not MIN_COINBASE_SCRIPTSIG <= scriptsig_len <= MAX_COINBASE_SCRIPTSIG:
                    problems.append(
                        f"{blockfile}: coinbase scriptSig length out of consensus range: "
                        f"{scriptsig_len} not in {MIN_COINBASE_SCRIPTSIG}..{MAX_COINBASE_SCRIPTSIG}"
                    )

                # A scriptSig too long to have been read has already failed the
                # length rule above, and its bytes are not here to check. One of
                # legal length always fits in the bytes read, so if it still
                # overran them the block file itself is truncated.
                if scriptsig is not None:
                    height_error = bip34_height_error(height, header_version(header_bytes), scriptsig)
                    if height_error is not None:
                        problems.append(f"{blockfile}: {height_error}, got {scriptsig[:16].hex()}")
                elif MIN_COINBASE_SCRIPTSIG <= scriptsig_len <= MAX_COINBASE_SCRIPTSIG:
                    problems.append(
                        f"{blockfile}: file is truncated: coinbase scriptSig declares "
                        f"{scriptsig_len} bytes but the file ends before them"
                    )

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
print(
    f"  {total_rows} rows, {total_headers} headers, {total_blocks} block files, "
    f"{total_coinbases} coinbases, {total_hash_only} hash-only"
)
