# Bounded observation memory for ARC-AGI-3

A fixed command policy with explicit transition evidence and limited planning.

This project implements a bounded observation-memory policy for interactive ARC-AGI-3 environments. It stores complete commands and observed transitions, then uses that evidence to order later experiments. A separate planning variant searches retained transitions. The evaluated policy is `transition_memory`, with planning disabled.

## Paper and result

Read [the paper](paper/paper.md) and its [conceptual methods diagram](paper/paper-cover.png). The diagram is not a recorded game trajectory.

On October 29, 2026, Kaggle marked the competition submission Succeeded and displayed Public Score **0.21** for [the evaluated notebook, Version 2](https://www.kaggle.com/code/jordanskinner313/arc-transition-memory-baseline?scriptVersionId=363475807), script version 363475807. The value is reported as displayed, without a percentage conversion. It is a single-policy public result, not a comparative ablation or a private final score. It does not establish an improvement from memory or planning. No per-game outcomes or actual scored-run runtime are reported.

Separately, an ordinary CPU commit passed offline installation and runtime preflight in 38.5 seconds. That commit ran zero games and reported `dry_run`. Its Parquet file is a commit-stage placeholder, not the measured competition result. No independent fresh export hash match for hosted source is asserted.

Source destination for this release: [jskinner215/arc-transition-memory](https://github.com/jskinner215/arc-transition-memory). The evaluated Kaggle version may require competition access until Kaggle makes it public; the same frozen local source notebook is included here.

## Run through the official competition environment

Use [the frozen notebook](notebooks/arc-memory-kaggle-v3.ipynb) in the [official ARC-AGI-3 Kaggle competition](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3). Attach that competition's input, select CPU and disable internet. The notebook expects `arc_agi_3_wheels` from the official input. Follow the platform's applicable competition rules and limits for any evaluation.

The wrapper verifies an installed CPython 3.12 interpreter, creates an isolated pipless environment and uses existing host pip's `--python` option to install exactly 31 hash-locked wheels offline. The observed child interpreter was `/usr/bin/python3.12`, CPython 3.12.3, while the notebook host used Python 3.13.15. It does not download an interpreter or fall back to a package index. Other containers are not certified by that observation.

An ordinary run performs setup and the dry-run branch. The competition controls the scored gateway branch and writes the actual scoring artifact through its gateway protocol. An ordinary commit is not a scoring request. No competition rerun flag should be manually set to imitate a scored result.

## Source layout and reproducibility limits

`src/` contains ten runtime/replay modules, four wrapper/build sources and the five unchanged embedded reproduction/configuration files. Two additional metadata files expose the comparison design: `protocol/reasoning-protocol-v2.json` and its required allowlist at `src/assets/public-assets-manifest.json`. `notebooks/` contains the unchanged generated notebook. `paper/` contains the exact paper body and cover. The [release manifest](RELEASE_MANIFEST.json) records file hashes; [EXCLUSIONS.json](EXCLUSIONS.json) lists the omitted upstream wheels and assets.

The notebook is the supported entry point for this release. The historical builders are preserved source, not a portable standalone build pipeline: the V3 builder reads an earlier V2 notebook omitted here, and the V2 builder expects its original package/helper layout. Replay tools also need original public game assets or fixtures not included here. Do not claim this tree alone rebuilds the notebook or reproduces the historical checkpoint.

The historical public-development checkpoint requires CPython 3.12.13 exactly. The observed hosted child was 3.12.3 and recorded `checkpoint_python_match: false`. Successful hosted setup does not establish exact checkpoint reproduction. Checkpoint metadata describes public-development evidence, not additional held-out paper results.

## Conditional public-development comparison

The [frozen five-policy protocol](protocol/reasoning-protocol-v2.json) specifies the candidate-pool, memory and planning comparisons described in the paper. Its SHA-256 is `f2cb667fb776be8f189596ebde0d649e08e58091624f8cb7eebe0802a6c542b9`. The [asset allowlist](src/assets/public-assets-manifest.json), SHA-256 `b4d199379755a877ba493f2b82b3739df30c66094a6b715b03b928427461df70`, is included because the runner reads that fixed location even when `--assets` is supplied. Both are metadata only; none of the allowlisted game source or metadata bytes is included.

This historical local comparison requires Linux x86_64, **CPython 3.12.13 exactly**, all packages at the protocol's pinned versions, and the 51 matching official public-development files obtained separately through authorized competition data access. The runner verifies source hashes, package versions, asset hashes and the complete game-source/metadata inventory. Current competition data may differ; unavailable or mismatched historical assets are a reproduction blocker, not permission to substitute different games. The Kaggle child observed at 3.12.3 does not meet this exact checkpoint requirement.

After independently supplying that runtime and hash-matched asset tree, the source-defined comparison invocation from the repository root is:

```sh
python3.12 src/run_matched_v2.py \
  --protocol protocol/reasoning-protocol-v2.json \
  --assets /path/to/hash-matched/environment_files \
  --output src/evidence/reasoning-reproduction \
  --seeds 0 \
  --policies uniform least_visited candidate_uniform transition_memory frontier_plan \
  --max-actions 500 --max-seconds 10
```

The output must be a fresh `src/evidence/reasoning-*` directory. This command is documented from the frozen source interface; it was not rerun from this assembled release. It is a public-development experiment, not a Kaggle score or a reportable five-policy result in this paper. Do not claim a new experiment or measured improvement from including the protocol and command.

`src/verify_memory_bundle.py` verifies a different historical bundle: it requires `bundle-manifest.json`, the original file layout and exactly three notebook profiles. It is **not** a validator for this tree or `RELEASE_MANIFEST.json`. The historical builders and offline replay helpers likewise depend on their stated original package/assets context; their presence does not make every helper a portable release command. Source and manifest hashes can be inspected without executing those archival tools.

## Licence scope and upstream dependencies

A release's accompanying `LICENSE` file, when present, defines the first-party permission. The intended licence is MIT No Attribution (MIT-0), applying only to confirmed first-party software and associated method documentation. This tree contains no licence grant until that file accompanies the release. No dependency or game asset is relicensed by a first-party grant.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [EXCLUSIONS.json](EXCLUSIONS.json). All 31 dependency wheels and all 51 public-development asset files are omitted. Their licences and notices remain upstream. The release includes no model weights, SDK distributions, game assets, raw action recordings, internal reviews, account/session records or client material.
