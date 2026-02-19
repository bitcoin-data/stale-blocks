#!/usr/bin/env python3

import csv
import struct
from datetime import datetime, timezone
from pathlib import Path
from string import Template

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "stale-blocks.csv"
BLOCKS_DIR = REPO_ROOT / "blocks"
OUT_DIR = REPO_ROOT / "site"
TEMPLATE_PATH = Path(__file__).resolve().parent / "template.html"

REPO_URL = "https://github.com/bitcoin-data/stale-blocks"
BLOCKS_URL = f"{REPO_URL}/raw/master/blocks"


def read_csv():
    with open(CSV_PATH) as f:
        return list(csv.DictReader(f))


def has_block_file(height, hash):
    return (BLOCKS_DIR / f"{height}-{hash}.bin").exists()


def decode_header(hex_str):
    raw = bytes.fromhex(hex_str)
    version, = struct.unpack_from("<i", raw, 0)
    prev_hash = raw[4:36][::-1].hex()
    merkle_root = raw[36:68][::-1].hex()
    timestamp, = struct.unpack_from("<I", raw, 68)
    bits, = struct.unpack_from("<I", raw, 72)
    nonce, = struct.unpack_from("<I", raw, 76)
    return {
        "version": f"0x{version:08x}",
        "prev_hash": prev_hash,
        "merkle_root": merkle_root,
        "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "bits": f"0x{bits:08x}",
        "nonce": f"{nonce}",
    }


def build_table_rows(rows):
    parts = []
    for i, r in enumerate(rows):
        height = r["height"]
        hash = r["hash"]
        has_hdr = bool(r["header"])
        has_blk = has_block_file(height, hash)

        if has_hdr:
            hdr_cell = (
                f'<button onclick="toggle(\'d{i}\')" '
                f'class="text-green-400 hover:text-green-300 underline cursor-pointer">'
                f'details</button>'
            )
        else:
            hdr_cell = '<span class="text-red-400">missing</span>'

        if has_blk:
            blk_cell = (
                f'<a href="{BLOCKS_URL}/{height}-{hash}.bin" '
                f'class="text-blue-400 hover:text-blue-300 underline">download</a>'
            )
        else:
            blk_cell = '<span class="text-red-400">missing</span>'

        parts.append(f"""          <tr class="border-b border-gray-800 hover:bg-gray-800/50">
            <td class="py-2 px-3">{height}</td>
            <td class="py-2 px-3 font-mono text-sm truncate max-w-0" title="{hash}">{hash}</td>
            <td class="py-2 px-3 text-center">{hdr_cell}</td>
            <td class="py-2 px-3 text-center">{blk_cell}</td>
          </tr>""")

        if has_hdr:
            hdr = decode_header(r["header"])
            parts.append(f"""          <tr id="d{i}" class="hidden">
            <td colspan="4" class="px-3 pb-3 pt-1">
              <div class="bg-gray-900 rounded-lg p-4 border border-gray-800 text-sm font-mono grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <span class="text-gray-500">hash</span>         <span class="select-all">{hash}</span>
                <span class="text-gray-500">version</span>      <span>{hdr["version"]}</span>
                <span class="text-gray-500">prev block</span>   <span class="select-all break-all">{hdr["prev_hash"]}</span>
                <span class="text-gray-500">merkle root</span>  <span class="select-all break-all">{hdr["merkle_root"]}</span>
                <span class="text-gray-500">timestamp</span>    <span>{hdr["timestamp"]}</span>
                <span class="text-gray-500">bits</span>         <span>{hdr["bits"]}</span>
                <span class="text-gray-500">nonce</span>        <span>{hdr["nonce"]}</span>
                <span class="text-gray-500">hex</span>          <span class="max-w-[80ch] break-all">{r["header"]}</span>
              </div>
            </td>
          </tr>""")

    return "\n".join(parts)


def generate_html(rows):
    template = Template(TEMPLATE_PATH.read_text())
    return template.substitute(
        total=len(rows),
        with_header=sum(1 for r in rows if r["header"]),
        with_block=sum(1 for r in rows if has_block_file(r["height"], r["hash"])),
        repo_url=REPO_URL,
        table_rows=build_table_rows(rows),
    )


def main():
    rows = read_csv()
    html = generate_html(rows)
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(html)
    print(f"Generated site/index.html ({len(rows)} blocks)")


if __name__ == "__main__":
    main()
