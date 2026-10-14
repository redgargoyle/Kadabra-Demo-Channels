# Kadabra launcher and permanent game release records

The desktop launcher is a separate application for Linux, Windows and macOS. It reads the signed TUF catalog under `v1/`. The website reads the Stable selections in `latest.json` in this directory. Both publications are generated from the reviewed `catalog-source.json` by the same GitHub workflow.

- `catalog-source.json`: reviewed game metadata and immutable, qualified packages.
- `v1/metadata/`: TUF root, timestamp, snapshot and targets metadata.
- `v1/targets/`: content-addressed player catalogs.
- `latest.json`: all game records, with distinct Preview and Stable choices.
- `latest/<game-id>.json`: permanent per-game record address.
- `website-stable-baseline.json`: initial public website choices preserved during migration.
- `publisher/`: signing/pointer generation code and focused channel tests.

A reviewed Preview proposal updates the launcher preview choice without overwriting an existing public website release. A reviewed Stable proposal also advances the website pointer to the exact selected archive. Adding a new preview game does not create a public Stable release. A rollback is a new reviewed higher catalog revision selecting an earlier compatible package; old archives are never overwritten.

Website links stay fixed:

`https://kadabra.games/downloads/<game-id>/latest/linux`

Replace `linux` with `windows`, `macos`, or `web`. Omitting the platform opens the game chooser. Unreleased platforms return 404. The website validates the exact game/host/path, filename, size and SHA-256 before redirecting, without proxying game archive bytes. GitHub CDN propagation may take several minutes; the resolver retains a working record if refresh is unavailable.

The repository-root eight-game `../latest.json` is a retained legacy format. The current website uses this directory's canonical 21-game record. It was bootstrapped from the live public website, preserving Golden Keep 0.9.14 and other current public downloads rather than replacing them with older launcher previews.

The owner-private command center prepares exact SHA-256-bound proposals. Its dedicated GitHub App is limited to this repository, Contents write and Actions write, and uses short-lived installation tokens. The connection is installed and verified for this repository only. Its real Publish button completed the Pixie Garden 1.2.1 preview round trip through GitHub App commit `1bb5302`, successful signing workflow run `38650778179`, and official TUF verification of catalog revision 8. The existing reviewed CLI and manual GitHub workflow publication also work independently.

The workflow renews metadata every 12 hours; timestamp freshness expires after 3 days. Installed games remain playable after catalog expiry; new installs and updates require a current signed catalog. Root keys are retained separately by the operator. The workflow holds online role keys in GitHub Secrets; the Site and desktop never hold root keys. Root renewal and verified backup remain operator tasks.

Archive qualification, actual OS runtime tests, save compatibility, creator/player acceptance and signing/notarization are separate checks. A published metadata record does not imply full game acceptance on every operating system.
