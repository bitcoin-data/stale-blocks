# stale-blocks

Dataset of stale headers and blocks observed on the Bitcoin network.

## Contributing stale-block headers

Ideally, stale-block hashes should be provided along with the corresponding
block-header. A hash without a block header could easily be fake.

Stale block data can be queried via the `getchaintips` RPC of Bitcoin Core.
The [`get-data.py`](./get-data.py) script can be used to directly query the
stale-blocks and their headers. It produces CSV output in the same format as
the [`stale-blocks.csv`](./stale-blocks.csv) file. Tips that are `active` or
`invalid` are already filtered.

To automatically add your data to [`stale-blocks.csv`](./stale-blocks.csv) you
can use the following:

```bash
python3 get-data.py
git diff stale-blocks.csv
```

Create a commit and open a PR. Keep in mind that this allows to figure out how
long you've been running a Bitcoin Core node. If that's a problem, you can also
submit your data to the project's maintainer to contribute anonymously.

## Contributing full stale blocks

Where possible, it's favorable to have the full blocks belonging to the stale
block headers. You can use the `--get-full-blocks` argument to get-data.py
to store the full blocks as binary blobs in the `blocks` direcory.

These can be imported back to a Bitcoin Core node with, for example:

```
cat blocks/813210-000000000000000000021c9f203786c0adcd7ae9a68a25d5e430d2a3dba613d5.bin | xxd -p | tr -d $'\n' | bitcoin-cli -stdin submitblock
```

## Show missing headers and block

To list the headers and block-files missing from the dataset, the following
command can be used:

```
$ get-data.py --show-missing
...
Missing blockfile 845869 00000000000000000000858fe3cb999f449bcbfcadd3bdb240641b6b9c39bb30
Missing blockfile 833411 000000000000000000018450917aeae08339ffd3172807420dd35c736032898f
Missing header 824221 00000000000000000003a0653dbab14cc0f6fef121442b29d6b4005cdcdbc0d5
...
```
