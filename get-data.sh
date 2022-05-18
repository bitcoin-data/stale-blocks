#!/bin/bash

# A script to extract stale blocks (height, hash, header) from a
# Bitcoin Core node. Output is in CSV format.
# This assumes .cookie-file authentication to the Bitcoin Core node.

TIPS=$(bitcoin-cli getchaintips)
STALE_TIP_PER_LINE=$(echo $TIPS | jq -c '.[] | select( .status == "valid-fork" or .status == "headers-only" or .status == "valid-headers" )')

for tip in $STALE_TIP_PER_LINE
do
	height=$(echo $tip | jq .height)
	hash=$(echo $tip | jq -r .hash)
	header=$(bitcoin-cli getblockheader $hash false)
	echo "$height,$hash,$header"
done
