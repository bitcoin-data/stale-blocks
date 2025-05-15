#!/usr/bin/env python3
#
# A script to extract stale blocks (height, hash, header) from a
# Bitcoin Core node. Output is in CSV format.

import argparse
import json
import os.path
import subprocess
import sys

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
        out = subprocess.run(cmd, capture_output=True, **kwargs, check=True).stdout
        if isinstance(out, bytes):
            out = out.decode('utf8')
        return out.strip()

def main(args):
    cli = Cli(args).cli

    if os.path.exists(args.header_csv):
        # throw an exception if open/read fails
        existing = list(open(args.header_csv, "r").readlines())
    else:
        # create a new file from scratch with a header
        print(f"{args.header_csv} does not exist, using empty file")
        existing = ["height,hash,header\n"]

    for tip in json.loads(cli("getchaintips")):
        if tip["status"] == "active" or tip["status"] == "invalid": continue
        depth = tip["branchlen"]
        height = tip["height"]
        blockhash = tip["hash"]
        while True:
            header_hex = cli("getblockheader", blockhash, "false")
            line = f"{height},{blockhash},{header_hex}\n"
            if line not in existing:
                print(f"Adding {height} {blockhash}")
                existing.append(line)

            blockfile = f"{args.blocks_dir}/{height}-{blockhash}.bin"
            if args.get_full_blocks and not os.path.exists(blockfile):
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

    f = open(args.header_csv, "w")
    for l in sorted(existing, reverse=True):
        f.write(l)
    f.close()

def get_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-user", default="", type=str)
    parser.add_argument("--rpc-host", default="", type=str)
    parser.add_argument("--rpc-pass", default="", type=str)
    parser.add_argument("--rpc-port", default="", type=str)
    parser.add_argument("--get-full-blocks", default=False, action="store_true")
    parser.add_argument("--blocks-dir", default="blocks", type=str)
    parser.add_argument("--header-csv", default="stale-blocks.csv", type=str)

    return parser.parse_args(argv)

if __name__ == "__main__":
    main(get_args(sys.argv[1:]))
