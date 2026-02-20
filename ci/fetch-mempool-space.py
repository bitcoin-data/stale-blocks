import requests
import csv
import os

URLS = [
    "https://mempool.space",
    "https://mempool.ninja",
    "https://node201.tk7.mempool.space",
    "https://node202.tk7.mempool.space",
    "https://node203.tk7.mempool.space",
    "https://node204.tk7.mempool.space",
    "https://node205.tk7.mempool.space",
    "https://node206.tk7.mempool.space",
    "https://node201.va1.mempool.space",
    "https://node202.va1.mempool.space",
    "https://node203.va1.mempool.space",
    "https://node204.va1.mempool.space",
    "https://node205.va1.mempool.space",
    "https://node206.va1.mempool.space",
    "https://node207.va1.mempool.space",
    "https://node208.va1.mempool.space",
    "https://node209.va1.mempool.space",
    "https://node210.va1.mempool.space",
    "https://node211.va1.mempool.space",
    "https://node212.va1.mempool.space",
    "https://node213.va1.mempool.space",
    "https://node214.va1.mempool.space",
    "https://node201.fra.mempool.space",
    "https://node202.fra.mempool.space",
    "https://node203.fra.mempool.space",
    "https://node204.fra.mempool.space",
    "https://node205.fra.mempool.space",
    "https://node206.fra.mempool.space",
    "https://node207.fra.mempool.space",
    "https://node208.fra.mempool.space",
    "https://node209.fra.mempool.space",
    "https://node210.fra.mempool.space",
    "https://node211.fra.mempool.space",
    "https://node212.fra.mempool.space",
    "https://node213.fra.mempool.space",
    "https://node214.fra.mempool.space",
    "https://node202.sv1.mempool.space",
    "https://node203.sv1.mempool.space",
    "https://node201.sg1.mempool.space",
    "https://node202.sg1.mempool.space",
    "https://node203.sg1.mempool.space",
    "https://node204.sg1.mempool.space",
    "https://node201.hnl.mempool.space",
    "https://node202.hnl.mempool.space",
    "https://node203.hnl.mempool.space",
]

CSV_FILE = "stale-blocks.csv"
BLOCKS_DIR = "blocks"

def load_existing_rows(filename):
    rows = {}
    if not os.path.exists(filename):
        return rows

    skip_header = True
    with open(filename, "r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if skip_header:
                skip_header = False
                continue

            height = int(row[0])
            block_hash = row[1]
            header_hex = row[2]
            rows[block_hash] = (height, block_hash, header_hex)
    return rows


def fetch_tips_from_url(base_url):
    try:
        r = requests.get(f"{base_url}/api/v1/stale-tips", timeout=15)
        r.raise_for_status()
        print(f"Fetched from {base_url}")
        return r.json()
    except Exception as e:
        print(f"Failed fetching {base_url}: {e}")
        return []

def fetch_raw_block(block_hash):
    print(f"Trying to fetch raw block {block_hash}..")
    for base_url in URLS:
        try:
            url = f"{base_url}/api/block/{block_hash}/raw"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.content
        except Exception as e:
            print(f"failed to fetch from {url}: {e}")
            continue
    print(f"Failed fetching raw block {block_hash}")
    return None

def collect_stale_rows():
    merged = {}

    for url in URLS:
        tips = fetch_tips_from_url(url)

        for tip in tips:
            if "stale" not in tip:
                continue

            try:
                height = tip["height"]
                block_hash = tip["hash"]
                header_hex = tip["stale"]["extras"]["header"]
            except KeyError:
                continue

            merged[block_hash] = (height, block_hash, header_hex)

    return merged

def main():
    existing = load_existing_rows(CSV_FILE)
    fetched_data = collect_stale_rows()

    merged = {**existing, **fetched_data}

    if merged == existing:
        print("No new stale blocks.")
        return

    sorted_rows = sorted(
        merged.values(),
        key=lambda x: x[0],
        reverse=True
    )

    with open(CSV_FILE, "w") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["height", "hash", "header"])
        writer.writerows(sorted_rows)
    print(f"Wrote {len(merged)-len(existing)} new stale block(s).")



    for hash in fetched_data:
        height, hash, header = fetched_data[hash]
        block_path = os.path.join(BLOCKS_DIR, f"{height}-{hash}.bin")
        if os.path.exists(block_path):
            continue  # skip existing

        raw_block = fetch_raw_block(hash)
        if raw_block:
            with open(block_path, "wb") as f:
                f.write(raw_block)
            print(f"Saved raw block {block_hash} ({len(raw_block)} bytes)")


if __name__ == "__main__":
    main()
