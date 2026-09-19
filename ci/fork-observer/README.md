# fork-observer

The dashboard's header tree is drawn with
[fork-observer](https://github.com/0xB10C/fork-observer). This directory holds
what that takes.

The deploy workflow builds a fork-observer database from the main chain headers
of block-dn.org and the stale headers of `stale-blocks.csv`
(`ci/fork-observer-db.py`), starts a fork-observer instance on it with
`config.toml`, and exports the instance's tree into `site/tree`
(`ci/fork-observer-site.py`), which the dashboard embeds as an iframe.

## Where fork-observer comes from

Nothing is vendored, so the tree follows fork-observer's development:

- The binary is the `fork-observer` package of the
  [0xb10c/nix](https://github.com/0xb10c/nix) repository's master branch. That
  repository's CI builds its packages against the `nixos-26.05` channel and
  pushes them to the `b10c-nixpkgs` cachix cache, so the workflow uses the
  same channel and gets a cached build instead of compiling. When the channel
  moved since that CI last ran, the package is built from source, which takes
  a few minutes longer.
- The scripts, styles and images are those of fork-observer's `main` branch,
  fetched from GitHub by `ci/fork-observer-site.py`.

The package is bumped to new fork-observer commits by a bot, so it can lag
behind the frontend by a few days. If a change to the API response format and
the frontend lands in between, the tree breaks until the package catches up.

## The page

`tree.html` is the document the dashboard embeds. It's separate from the
dashboard because fork-observer's stylesheets restyle the whole page. It loads
fork-observer's `blocktree.js`, which draws the tree, and does the little that
fork-observer's `main.js` does on top of that on a live instance: define the
globals `blocktree.js` reads, load the data, draw once. Everything a live
instance has beyond the tree, like the node table, live updates or the mining
jobs feed, is left out.

The stale blocks are marked with two tip statuses of the dataset's own,
`full-block` and `header-only`, instead of the getchaintips statuses
fork-observer uses. `tree.html` supplies their colours, and it rewrites the
tip labels after every draw to drop the "1x " count fork-observer puts in
front of the status, which is meaningless with a single source. The "active"
tip is the main chain tip when the page was generated.

If a fork-observer change makes `blocktree.js` expect something new from
`main.js`, or renames what `tree.html` hooks into (`draw`, `recalc_tip_boxes`,
the `.tip-info-row` labels), `tree.html` has to follow. The browser console
shows the resulting error.

## Running it locally

```bash
nix-build https://github.com/0xb10c/nix/archive/master.tar.gz -A fork-observer -o fork-observer
python3 ci/fork-observer-db.py fork-observer-db/fork-observer.sqlite
CONFIG_FILE=ci/fork-observer/config.toml ./fork-observer/bin/fork-observer &
python3 ci/fork-observer-site.py
python3 ci/generate-website.py
python3 -m http.server --directory site
```
