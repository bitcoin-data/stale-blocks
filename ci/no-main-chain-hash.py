# checks that:
# - header hashes match header (by hashing)

import csv
import json
import sys
import time
from urllib.request import urlopen

reader = csv.reader(sys.stdin)
for row in reader:
    print("checking row:", row)
    header_hash = row[1]
    with urlopen("https://blockstream.info/api/block/"+header_hash+"/status") as response:
        response_content = json.loads(response.read())
        assert(response_content["in_best_chain"] == False)
        time.sleep(0.3)

print("not-in-best-chain-check successful")
