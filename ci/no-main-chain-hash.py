# checks that:
# - header hashes match header (by hashing)

import csv
import json
import sys
import time
import urllib.error
from urllib.request import urlopen

MAX_RETRIES = 5
BASE_DELAY_S = 1.0
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def fetch_status(header_hash):
    url = f"https://blockstream.info/api/block/{header_hash}/status"
    for attempt in range(MAX_RETRIES):
        try:
            with urlopen(url, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code in RETRYABLE_STATUSES and attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY_S * (2 ** attempt)
                print(
                    f"  HTTP {e.code} for {header_hash}, "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY_S * (2 ** attempt)
                print(
                    f"  network error for {header_hash}: {e}, "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f"exhausted {MAX_RETRIES} retries for {header_hash}")


reader = csv.reader(sys.stdin)
next(reader, None)
for row in reader:
    print("checking row:", row)
    header_hash = row[1]
    response_content = fetch_status(header_hash)
    assert not response_content["in_best_chain"]
    time.sleep(0.3)

print("not-in-best-chain-check successful")
