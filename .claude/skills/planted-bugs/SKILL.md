---
name: planted-bugs
description: Change the sandbox fork's history - a planted bug, a harmless commit, the v1.3.0 setup, or the overlay files (compose.versions.yaml, compose.extras.yaml, .env.override) - and regenerate the patches, tags, SHAs and images. Use when editing anything under sandbox/overlay or sandbox/patches, or when a bug needs to move or change.
---

# Change the fork's planted commits

The fork is generated: `make sandbox` rebuilds branch `sandbox` from `sandbox/upstream.env`,
`sandbox/overlay/` and `sandbox/patches/` with fixed authors and dates. Edit those sources,
never the fork by hand, or the next `make sandbox` throws the edit away.

## Overlay files (fork-owned config)

1. Edit `sandbox/overlay/<file>`.
2. `make sandbox`: it warns that the tag SHAs differ from `upstream.env`.
3. Put the new short SHAs in `EXPECTED_V1_3_0` / `EXPECTED_V1_4_0` in `sandbox/upstream.env`;
   rerun `make sandbox` and confirm no warning.

## A commit in v1.3.0 or v1.4.0

1. In the fork, stop at the commit to change (non-interactively), change it, and continue.
   Amending keeps the author and date; setup.sh fixes the committer date.
   ```bash
   cd ../opentelemetry-demo
   sha=$(git log --format=%h --grep='simplify card expiry' -1 v1.4.0)   # the commit to change
   GIT_SEQUENCE_EDITOR="sed -i.bak 's/^pick $sha/edit $sha/'" git rebase -i v1.3.0
   # edit the files, then:
   git add -A && git commit --amend --no-edit && git rebase --continue
   ```
   For v1.3.0's patch, rebase onto `UPSTREAM_SHA` from `sandbox/upstream.env` instead. To add a
   commit, commit it at the right point the same way. Keep messages ordinary: no commit message
   may say what it breaks.
2. Export again, replacing the old files:
   ```bash
   rm sandbox/patches/v1.4.0/*.patch
   git -C ../opentelemetry-demo format-patch --zero-commit --no-signature \
     -o "$PWD/sandbox/patches/v1.4.0" v1.3.0..HEAD
   ```
3. `make sandbox`, then update the SHAs in `upstream.env` as above.
4. `make sandbox-images` (rebuilds images whose tag moved).

## Keep everything that describes the bugs in step

- `tests/test_sandbox_fork.py`: `V1_4_0` (commits and files) and `BUGS` (file, line, text).
- `sandbox/README.md`'s bug table and line numbers; AGENTS.md's bug table and tag SHAs.
- A bug's scenario in `scenarios/scenario.py`, and `FakeShop` in `tests/test_scenarios.py` so
  the scenario still passes with the bug and fails without it.
- The plan's "Planted bugs" table if the bug itself changed.

## Verify

`make test test-sandbox`, then `make shop-up` (or `make deploy`) and `make test-shop`.
`git -C ../opentelemetry-demo status` must be clean afterwards. Then follow "Finishing a task"
in AGENTS.md.
