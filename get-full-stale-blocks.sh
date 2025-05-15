#!/bin/sh
#
# A script to extract stale blocks as binary files from a
# Bitcoin Core node. Output is a .bin file per block into $BLOCK_DIR.

RPC_HOST=""
RPC_PORT=""
RPC_USER=""
RPC_PASS=""
#RPC_INFO="--rpcuser=$RPC_USER --rpcconnect=$RPC_HOST --rpcpassword=$RPC_PASS --rpcport=$RPC_PORT"

BLOCK_DIR="blocks"
mkdir -p $BLOCK_DIR

bitcoin-cli $RPC_INFO getchaintips \
	 | jq -rc '.[] | select (.status != "active" and .status != "invalid")
                       | ( (.height | tostring) + " " + .hash )' \
	 | while read height bhash;
		do
			echo "trying to get block $bhash ($height).."
			FILENAME="$height-$bhash.bin"
			if [ -s "$BLOCK_DIR/$FILENAME" ]; then continue; fi
			block=$(bitcoin-cli $RPC_INFO getblock $bhash 0)
			GETBLOCK_ERROR=$?
			if [ $GETBLOCK_ERROR -eq 0 ];
			then
				echo $block | xxd -r -p > "$BLOCK_DIR/$FILENAME"
				echo "saved $BLOCK_DIR/$FILENAME"
			fi
		done
