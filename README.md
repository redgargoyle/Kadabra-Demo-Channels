# Kadabra demo channels

The stable `latest.json` file points each Kadabra game at its current reviewed demo downloads. The website can update its download buttons from this small public file without uploading the complete website again.

[Read the current channel](https://raw.githubusercontent.com/redgargoyle/Kadabra-Demo-Channels/main/latest.json) · [View its change history](https://github.com/redgargoyle/Kadabra-Demo-Channels/commits/main/latest.json)

The archives themselves keep versioned URLs, sizes, and SHA-256 hashes. A promotion changes the Windows and Linux pointers together. An older macOS demo remains available with its own honest version label unless a replacement is explicitly supplied. Releases are chosen by their exact tag; the tool never guesses from GitHub’s “latest release,” which can be affected by prereleases or unrelated asset-pack releases.

## Update a GitHub-hosted demo

1. Build, test, package, and upload the Windows/Linux pair to the game’s public **binary release repository**. Publish the release after uploads finish. Private game source stays in its separate repository.
2. Use Python 3.10 or newer and an authenticated [GitHub CLI](https://cli.github.com/). Preview the exact pair and player notes:

```sh
python3 scripts/promote_demo.py promote \
  --game golden-keep-rts \
  --repository redgargoyle/Goldenkeep-Releases \
  --tag v0.9.1-racial-strategy.1 \
  --version 0.9.1-racial-strategy.1 \
  --windows Goldenkeep-0.9.1-racial-strategy.1-Windows.zip \
  --linux Goldenkeep-0.9.1-racial-strategy.1-Linux.tar.gz \
  --notes "October 4 development demo with racial contracts, squads and mobile teachers. Windows runtime play still needs testing." \
  --dry-run
```

3. Review the printed before/after URLs, version, sizes, hashes, retained macOS version, prerelease status, and notes. Run the same command with `--apply` instead of `--dry-run` to create one normal commit updating the channel.

The command is read-only by default. `--macos Exact-Mac-Archive.zip` updates macOS in the same commit; omitting it preserves that platform exactly. Omitting `--notes` preserves the existing status note. Other games, browser demo settings, build notes, and game-level metadata stay unchanged. A replaced platform gets only the newly verified asset identity: old size labels, packaging proofs, runtime QA claims, and source provenance are not copied onto different bytes. Explicit published prerelease tags are supported.

The tool checks the repository is public and matches that game’s fixed release repository, the release is published and not a draft, each named archive is uploaded, platform extensions and content types are appropriate, and GitHub reports a positive size and SHA-256 digest. It only transfers small API JSON responses. It does not download archives, upload a release, mutate tags, or store credentials.

Channel updates are limited to the fixed `main` branch and a manifest below 256 KiB. Asset names contain at most 180 letters, digits, spaces, periods, underscores or hyphens; version labels contain at most 160 UTF-16 text units. GitHub tags contain only letters, digits, periods, underscores and hyphens. GitHub assets must be smaller than 2 GiB and recorded digests use 64 lowercase hexadecimal characters. These limits match the website’s channel reader.

The update uses GitHub’s existing manifest blob SHA. If someone changes the channel during promotion, the command aborts rather than overwriting their change. Run a new dry run and review the current state before retrying. A failed or timed-out write response can have an unknown outcome: inspect the channel history before retrying. No write is automatically retried or forced. The commit SHA printed by `--apply` is the receipt. Your local checkout is not rewritten by the API commit; synchronize it before making later local edits.

## Restore an earlier demo

Choose a **full 40-character commit SHA from this channel repository** whose `latest.json` contains the desired game version:

```sh
python3 scripts/promote_demo.py rollback \
  --game golden-keep-rts \
  --revision FULL_CHANNEL_COMMIT_SHA \
  --dry-run
```

Review it, then repeat with `--apply`. Only that game’s record is restored; other games keep their current state. The tool rechecks each historical GitHub asset, including a macOS asset from a different release, and aborts if its size or digest changed or the release is no longer published. A rollback is another ordinary channel commit, preserving the full history.

## Jabberwocky’s existing hosted archives

Jabberwocky’s current archives exceed GitHub’s per-file upload size, so its current pair stays at the approved Sites download origin. The exact two versioned HTTPS URLs are listed in `channel-config.json`. Promotion of a new Jabberwocky pair remains a small reviewed metadata update: verify the complete uploaded bytes and hashes first, add the exact approved-origin URLs to the allowlist, update both platform records in `latest.json`, validate, and commit/push them together. Arbitrary hosts, unversioned files, query credentials, and URLs for other games are rejected.

```sh
python3 scripts/promote_demo.py validate --manifest latest.json
python3 -m unittest discover -s tests -v
```

`validate` checks the local schema, platform pairs, URL allowlist, and recorded sizes/hashes. It does not verify remote archive bytes. Rollback of a previously reviewed Sites pair uses the recorded hashes and exact approved URLs; it cannot obtain a fresh remote SHA-256 from that host’s GitHub API because those files are not GitHub assets.

## What this channel proves

GitHub’s API digest and uploaded size provide release metadata checks. They do not replace extraction verification, executable permissions, a clean build identity, Windows/Linux runtime play, save compatibility, or creative review. These checks belong to each game’s release process. Missing API digests are a reason to stop promotion and repair/reupload the reviewed release asset; the tool does not silently invent a digest or download gigabytes to guess one.

`latest.json` is public distribution metadata, not game source or a runtime configuration service. It contains exactly eight game records; platform versions may differ. Keep player-facing notes concise and preserve any remaining testing limitations.
