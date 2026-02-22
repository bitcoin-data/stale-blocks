#!/usr/bin/env python3
#
# A script to extract stale blocks (height, hash, header) from a
# Bitcoin Core node. Output is in CSV format.

import argparse
import csv
import json
import os.path
import subprocess
import sys

CSV_HEADER = ["height", "hash", "header"]

class Cli:
    def __init__(self, args):
        self.args = args

    def rpcargs(self):
        rpcopts = ["rpcuser", "rpcconnect", "rpcpassword", "rpcport"]
        rpcvals = [self.args.rpc_user, self.args.rpc_host, self.args.rpc_pass, self.args.rpc_port]
        a = []
        for o, v in zip(rpcopts, rpcvals):
            if not v: continue
            a.append(f"--{o}={v}")
        return a

    def cli(self, *args, **kwargs):
        cmd = ["bitcoin-cli"] + self.rpcargs() + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, **kwargs, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Command '{' '.join(cmd)}' with exit code {e.returncode}: {e.stderr}")
            exit(1)

def show_missing(args):
    if not os.path.exists(args.header_csv):
        print("Could not find csv file")
        return 1

    reader = csv.reader(open(args.header_csv, "r", newline=''))
    next(reader, None)  # skip the headers
    for height, bhash, header in reader:
        if header == "":
            print(f"Missing header {height} {bhash}")
        else:
            blockfile = f"{args.blocks_dir}/{height}-{bhash}.bin"
            if not os.path.exists(blockfile):
                print(f"Missing blockfile {height} {bhash}")

def main(args):
    cli = Cli(args).cli

    if args.show_missing:
        show_missing(args)

    existing = {}
    if os.path.exists(args.header_csv):
        # throw an exception if open/read fails
        reader = csv.reader(open(args.header_csv, "r", newline=''))
        next(reader, None)  # skip the headers
        for height, bhash, header in reader:
            height = int(height)
            if height not in existing:
                existing[height] = {}
            if bhash not in existing[height]:
                existing[height][bhash] = header
            # only overwrite the header if we actually have it
            if header != "":
                existing[height][bhash] = header
    else:
        # create a new file from scratch with a header
        print(f"{args.header_csv} does not exist, using empty file")

    bci = json.loads(cli("getblockchaininfo"))
    pruneheight = 0
    if bci["pruned"]:
        pruneheight = bci["pruneheight"]

    for tip in json.loads(cli("getchaintips")):
        if tip["status"] == "active" or tip["status"] == "invalid": continue
        depth = tip["branchlen"]
        height = tip["height"]
        blockhash = tip["hash"]
        if height > bci["blocks"]:
            print(f"Skipping new header {blockhash} (height={height} > tip={bci['blocks']})")
            continue
        while True:
            if height not in existing:
                existing[height] = {}
            if blockhash not in existing[height] or existing[height][blockhash] == "":
                header_hex = cli("getblockheader", blockhash, "false")
                existing[height][blockhash] = header_hex
                print(f"Adding {height} {blockhash}")

            blockfile = f"{args.blocks_dir}/{height}-{blockhash}.bin"
            if height >= pruneheight and tip["status"] in ["valid-headers","valid-fork"] and not os.path.exists(blockfile):
                try:
                    blockhex = cli("getblock", blockhash, "0")
                    blockdata = open(blockfile, "wb")
                    blockdata.write(bytes.fromhex(blockhex))
                    blockdata.close()
                    print(f"Saved {blockfile}")
                except subprocess.CalledProcessError:
                    print(f"Failed to get data for block {height}-{blockhash}")

            depth -= 1
            if depth == 0: break
            height -= 1
            header = json.loads(cli("getblockheader", blockhash))
            blockhash = header["previousblockhash"]

    with open(args.header_csv, "w", newline="") as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(CSV_HEADER)
        for height in sorted(existing, reverse=True):
            for bhash in sorted(existing[height], reverse=True):
                header = existing[height][bhash]
                w.writerow([height, bhash, header])

def get_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-user", default="", type=str)
    parser.add_argument("--rpc-host", default="", type=str)
    parser.add_argument("--rpc-pass", default="", type=str)
    parser.add_argument("--rpc-port", default="", type=str)
    parser.add_argument("--blocks-dir", default="blocks", type=str)
    parser.add_argument("--header-csv", default="stale-blocks.csv", type=str)

    parser.add_argument("--show-missing", default=False, action="store_true")

    return parser.parse_args(argv)

if __name__ == "__main__":
    main(get_args(sys.argv[1:]))
