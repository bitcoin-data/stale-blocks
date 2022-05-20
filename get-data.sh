#!/bin/sh
#
# A script to extract stale blocks (height, hash, header) from a
# Bitcoin Core node. Output is in CSV format.

RPC_HOST=""
RPC_PORT=""
RPC_USER=""
RPC_PASS=""
RPC_INFO="--rpcuser=$RPC_USER --rpcconnect=$RPC_HOST --rpcpassword=$RPC_PASS --rpcport=$RPC_PORT"

bitcoin-cli $RPC_INFO getchaintips \
	 | jq -rc '.[] | select (.status != "active" and .status != "invalid")
                       | ( (.height | tostring) + " " + .hash )' \
	 | while read height bhash;
		do
			echo "$height,$bhash,$(bitcoin-cli $RPC_INFO getblockheader $bhash false)"
		done
