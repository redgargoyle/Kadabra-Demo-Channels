# Kadabra Launcher preview distribution

This directory is the separate signed launcher catalog. The existing eight-game website `latest.json` remains independent.

- `v1/metadata/`: TUF root, timestamp, snapshot and targets metadata.
- `v1/targets/`: content-addressed public player catalogs.
- `catalog-source.json`: reviewed public game and package records used by the publisher.
- `publisher/`: publisher code using the maintained TUF model library. Its online signing keys are GitHub Actions secrets; root keys are retained separately by the operator and are never committed.

The scheduled workflow renews the preview metadata every12 hours; freshness expires after3 days. An expired catalog prevents new installs/updates while installed games remain playable. Failures must be resolved before expiry. GitHub's scheduler is not an uptime guarantee.

Package archive qualification, OS runtime acceptance, creator acceptance and signing/notarization are distinct checks. Preview metadata does not imply Windows/macOS acceptance. At the initial milestone Pixie Garden Linux and the platform-independent Poot-Poot browser archive have been checked; native packages for other games are still being qualified.

To change a release: review the private command-center proposal, qualify the exact archive and its save/launch contract, then commit the reviewed public records to `catalog-source.json` and run the publisher workflow. Reusing a package ID for different bytes or launch parameters is rejected. A game rollback is a new higher catalog revision selecting the earlier compatible package.

Root renewal and recovery are operator tasks and cannot be accomplished by the online-only renewal job. Back up root keys securely and renew/rotate root well before expiry.
