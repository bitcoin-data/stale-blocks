# stale-blocks

Dataset of stale headers and blocks observed on the Bitcoin network.

## Contributing stale-block headers

Ideally, stale-block hashes should be provided along with the corresponding
block-header. A hash without a block header could easily be fake.

Stale block data can be queried via the `getchaintips` RPC of Bitcoin Core.
The [`get-data.sh`](./get-data.sh) script can be used to directly query the
stale-blocks and their headers. It produces CSV output in the same format as
the [`stale-blocks.csv`](./stale-blocks.csv) file. Tips that are `active` or
`invalid` are already filtered.

To automatically add your data to [`stale-blocks.csv`](./stale-blocks.csv) you
can use the following:

```
sh get-data.sh > my-stale-blocks.csv
cat stale-blocks.csv my-stale-blocks.csv | sort --reverse --unique --output stale-blocks.csv
rm my-stale-blocks.csv
git diff stale-blocks.csv
```

Create a commit and open a PR. Keep in mind that this allows to figure out how
long you've been running a Bitcoin Core node. If that's a problem, you can also
submit your data to the project's maintainer to contribute anonymously.

## Contributing full stale blocks

Where possible, it's favorable to have the full blocks belonging to the stale
block headers. Similar to the get-data.sh script, the `get-full-stale-blocks.sh`
script can be used to store the full blocks as binary blobs in the `blocks`
direcory.

These can be imported back to a Bitcoin Core node with, for example:

```
cat blocks/813210-000000000000000000021c9f203786c0adcd7ae9a68a25d5e430d2a3dba613d5.bin | xxd -p | tr -d $'\n' | bitcoin-cli -stdin submitblock
```
