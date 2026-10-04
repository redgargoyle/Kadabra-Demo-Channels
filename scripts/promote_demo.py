#!/usr/bin/env python3
"""Promote an explicitly reviewed native demo pair through one GitHub manifest commit.

Only small JSON metadata is transferred. No archive download, release upload,
tag mutation, credential storage, or force update is performed.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

CHANNEL_REPOSITORY = "redgargoyle/Kadabra-Demo-Channels"
MANIFEST_PATH = "latest.json"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ASSET_BYTES = 10 * 1024**3
GITHUB_ASSET_LIMIT = 2 * 1024**3
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._ -]{1,180}$")
SAFE_TAG = re.compile(r"^[A-Za-z0-9._-]+$")
EXPECTED_REPOSITORIES = {
    "golden-ocean": "redgargoyle/Golden-Ocean-Releases",
    "chantilly": "redgargoyle/Chantilly-Releases",
    "golden-keep-rts": "redgargoyle/Goldenkeep-Releases",
    "dark-between-stations": "redgargoyle/The-Dark-Between-Stations-Releases",
    "cliff-cities": "redgargoyle/The-Cliff-Cities-Releases",
    "jabberwocky": "",
    "your-happy-place": "redgargoyle/YourHappyPlace-Releases",
    "inhospitable": "redgargoyle/Inhospitable-Releases",
}
EXTERNAL_HOST = "kadabra-video-library-review.amcorblue.chatgpt.site"
EXTENSIONS = {
    "windows": (".zip",),
    "linux": (".tar.gz", ".tgz", ".tar.zst", ".zip"),
    "macos": (".zip", ".tar.gz", ".dmg"),
}
MIME_TYPES = {
    ".zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
    ".tar.gz": {"application/gzip", "application/x-gzip", "application/x-tar", "application/x-gtar", "application/octet-stream"},
    ".tgz": {"application/gzip", "application/x-gzip", "application/x-tar", "application/x-gtar", "application/octet-stream"},
    ".tar.zst": {"application/zstd", "application/x-tar", "application/octet-stream"},
    ".dmg": {"application/x-apple-diskimage", "application/octet-stream"},
}


class PromotionError(Exception):
    """A validation or GitHub request could not complete; writes are never retried."""


def require(condition, message):
    if not condition:
        raise PromotionError(message)


def text_units(value):
    require(isinstance(value, str), "Expected a text value.")
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeError as exc:
        raise PromotionError("Text contains an invalid Unicode surrogate.") from exc


def label(value, description, limit=200):
    require(isinstance(value, str) and bool(value.strip()) and text_units(value) <= limit,
            f"{description} must be a nonempty string of at most {limit} characters.")
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value),
            f"{description} cannot contain control characters.")
    return value


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def timestamp(value, description):
    label(value, description, 40)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError(f"{description} must be an ISO timestamp.") from exc
    require(parsed.tzinfo is not None, f"{description} must include its timezone.")


def filename(value, platform):
    require(isinstance(value, str) and SAFE_FILENAME.fullmatch(value),
            f"{platform} asset name must be a plain archive filename.")
    require(value.lower().endswith(EXTENSIONS[platform]),
            f"Unsupported {platform} archive extension: {value}")
    return value


def release_url(repository, tag, name):
    return f"https://github.com/{repository}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"


def github_asset_location(url):
    """Return repository/tag/name only for one exact GitHub release asset URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.scheme != "https" or parts.netloc != "github.com" or parts.query
            or parts.fragment or parts.username or parts.password):
        return None
    segments = parts.path.split("/")
    if len(segments) != 7 or segments[0] or segments[3:5] != ["releases", "download"]:
        return None
    owner, repo, tag, name = [unquote(segments[i]) for i in (1, 2, 5, 6)]
    if (not all((owner, repo, tag, name)) or "/" in owner or "/" in repo or "/" in name
            or not SAFE_TAG.fullmatch(segments[5])):
        return None
    return f"{owner}/{repo}", tag, name


def load_external_allowlist(path=None):
    """Existing non-GitHub assets are approved individually, never by a broad host."""
    config_path = path or Path(__file__).resolve().parents[1] / "channel-config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PromotionError("Cannot read channel-config.json.") from exc
    require(isinstance(config, dict) and type(config.get("schemaVersion")) is int
            and config["schemaVersion"] == 1,
            "Invalid channel-config.json schema.")
    external = config.get("approvedExternalAssets")
    require(isinstance(external, dict) and not set(external) - set(EXPECTED_REPOSITORIES),
            "External asset allowlist contains an unknown game.")
    result = {}
    for game, platforms in external.items():
        require(isinstance(platforms, dict) and not set(platforms) - set(EXTENSIONS),
                f"Invalid external asset platforms for {game}.")
        result[game] = {}
        for platform, urls in platforms.items():
            require(isinstance(urls, list) and len(urls) <= 20,
                    f"Invalid external URL list for {game}/{platform}.")
            for url in urls:
                require(isinstance(url, str), "External URL must be a string.")
                try:
                    parts = urlsplit(url)
                except ValueError as exc:
                    raise PromotionError("Invalid approved external URL.") from exc
                require(parts.scheme == "https" and bool(parts.netloc)
                        and not parts.username and not parts.password
                        and not parts.query and not parts.fragment,
                        "Approved external URLs must be exact HTTPS URLs without credentials or query strings.")
                require(github_asset_location(url) is None,
                        "GitHub URLs must use the fixed binary repository mapping, not the external allowlist.")
                suffix = "Windows" if platform == "windows" else "Linux"
                require(game == "jabberwocky" and platform in ("windows", "linux")
                        and parts.netloc == EXTERNAL_HOST
                        and re.fullmatch(r"/downloads/Jabberwocky-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}-" + suffix + r"\.zip", parts.path),
                        "External allowlist only supports the approved, versioned Jabberwocky download origin.")
            result[game][platform] = frozenset(urls)
    return result


def validate_asset(game, platform, asset, external):
    require(isinstance(asset, dict), f"{game}/{platform} asset must be an object.")
    for key in ("name", "url", "version", "sizeBytes", "sha256"):
        require(key in asset, f"{game}/{platform} is missing {key}.")
    filename(asset["name"], platform)
    label(asset["version"], f"{game}/{platform} version", 160)
    require(type(asset["sizeBytes"]) is int and 0 < asset["sizeBytes"] <= MAX_ASSET_BYTES,
            f"{game}/{platform} sizeBytes must be a positive bounded integer.")
    require(isinstance(asset["sha256"], str) and SHA256.fullmatch(asset["sha256"]),
            f"{game}/{platform} requires a SHA-256 digest.")
    url = asset["url"]
    require(isinstance(url, str) and len(url) <= 2000, f"{game}/{platform} URL is invalid.")
    location = github_asset_location(url)
    if location:
        repo, _, name = location
        require(bool(EXPECTED_REPOSITORIES[game]) and repo == EXPECTED_REPOSITORIES[game]
                and name == asset["name"] and asset["sizeBytes"] < GITHUB_ASSET_LIMIT,
                f"{game}/{platform} URL does not match its binary repository and filename.")
    else:
        require(url in external.get(game, {}).get(platform, frozenset()),
                f"{game}/{platform} URL is not an approved exact HTTPS download.")
        require(urlsplit(url).path.rsplit("/", 1)[1] == asset["name"],
                f"{game}/{platform} hosted URL does not match its filename.")


def validate_manifest(manifest, external):
    require(isinstance(manifest, dict) and type(manifest.get("schemaVersion")) is int
            and manifest["schemaVersion"] == 1, "latest.json requires schemaVersion 1.")
    timestamp(manifest.get("updatedAt"), "Manifest updatedAt")
    try:
        serialized = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PromotionError("Manifest contains invalid JSON or Unicode metadata.") from exc
    require(len(serialized) < MAX_MANIFEST_BYTES,
            "latest.json must remain below the 256 KiB edge metadata limit.")
    games = manifest.get("games")
    require(isinstance(games, dict) and set(games) == set(EXPECTED_REPOSITORIES),
            "latest.json must contain exactly the eight supported game slugs.")
    for game, record in games.items():
        require(isinstance(record, dict), f"{game} must be an object.")
        label(record.get("tag"), f"{game} tag")
        require(isinstance(record.get("updatedAt"), str), f"{game} updatedAt is required.")
        try:
            dt.datetime.fromisoformat(record["updatedAt"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise PromotionError(f"{game} updatedAt must be an ISO date or timestamp.") from exc
        require(type(record.get("knownPublished")) is bool and record["knownPublished"],
                f"{game} must describe published downloads.")
        require(record.get("repo") == EXPECTED_REPOSITORIES[game],
                f"{game} repo is outside its binary repository mapping.")
        assets = record.get("directAssets")
        require(isinstance(assets, dict) and {"windows", "linux"} <= set(assets)
                and not set(assets) - set(EXTENSIONS),
                f"{game} requires a Windows/Linux pair and optional macOS asset.")
        for platform, asset in assets.items():
            validate_asset(game, platform, asset, external)
        if any(github_asset_location(a["url"]) for a in assets.values()):
            require(record["repo"] == EXPECTED_REPOSITORIES[game],
                    f"{game} GitHub assets require the matching repo field.")
        if "assets" in record:
            require(isinstance(record["assets"], dict), f"{game} legacy assets must be an object.")
        if "buildNotes" in record:
            require(isinstance(record["buildNotes"], list)
                    and len(record["buildNotes"]) <= 30
                    and all(isinstance(note, str) and text_units(note) <= 2000 for note in record["buildNotes"]),
                    f"{game} buildNotes must be a list of strings.")
        for key in ("title", "tag", "updatedAt", "statusNote", "releasePage", "webDemo", "webDemoLabel", "freshLabel", "packagingReviewedAt"):
            if key in record:
                require(isinstance(record[key], str) and text_units(record[key]) <= 2000,
                        f"{game}/{key} must be a bounded string.")
        if record.get("releasePage"):
            try:
                parts = urlsplit(record["releasePage"])
            except ValueError as exc:
                raise PromotionError(f"{game} releasePage is invalid.") from exc
            segments = parts.path.split("/")
            require(parts.scheme == "https" and parts.netloc == "github.com"
                    and not parts.query and not parts.fragment and len(segments) == 6
                    and "/".join(segments[1:3]) == EXPECTED_REPOSITORIES[game]
                    and segments[3:5] == ["releases", "tag"] and bool(SAFE_TAG.fullmatch(segments[5]))
                    and bool(EXPECTED_REPOSITORIES[game]),
                    f"{game} releasePage must point to its expected public binary release repository.")
        if record.get("webDemo"):
            require(re.fullmatch(r"/demos/[a-z0-9-]+/?", record["webDemo"]),
                    f"{game} webDemo must be a local /demos/ game route.")
        for key in ("webDemoPrimary",):
            if key in record:
                require(type(record[key]) is bool, f"{game}/{key} must be a boolean.")
    return manifest


class GitHubAPI:
    """Use gh's existing authentication; JSON is supplied directly over stdin."""

    def request(self, method, endpoint, body=None):
        args = ["gh", "api", "--hostname", "github.com", "--method", method,
                "-H", "Accept: application/vnd.github+json",
                "-H", "X-GitHub-Api-Version: 2022-11-28", endpoint]
        payload = None
        if body is not None:
            args.extend(["--input", "-"])
            payload = json.dumps(body, ensure_ascii=False)
        try:
            result = subprocess.run(args, input=payload, capture_output=True, text=True,
                                    check=False, timeout=45)
        except FileNotFoundError as exc:
            raise PromotionError("Install GitHub CLI and sign in with gh auth login before using this tool.") from exc
        except subprocess.TimeoutExpired as exc:
            suffix = " Inspect the channel before retrying; the write outcome is unknown." if method == "PUT" else ""
            raise PromotionError("GitHub request timed out; no automatic retry was attempted." + suffix) from exc
        if result.returncode:
            # Do not echo stderr, subprocess environment, token values, or request bodies.
            suffix = " Inspect the channel before retrying; a failed response cannot prove no write occurred." if method == "PUT" else ""
            require(False, f"GitHub {method} request failed for {endpoint}. No retry or force update was attempted." + suffix)
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise PromotionError("GitHub returned invalid JSON.") from exc


class Channel:
    def __init__(self, api, external=None):
        self.api = api
        self.external = external if external is not None else load_external_allowlist()
        self.branch = None
        self.public_repositories = set()

    def public_repository(self, repository):
        if repository in self.public_repositories:
            return None
        data = self.api.request("GET", f"repos/{repository}")
        require(isinstance(data, dict) and data.get("full_name") == repository
                and data.get("private") is False,
                f"{repository} must be the expected public repository.")
        self.public_repositories.add(repository)
        return data

    def current(self):
        data = self.public_repository(CHANNEL_REPOSITORY)
        require(data is not None, "Read the current manifest only once per operation.")
        require(data.get("default_branch") == "main", "The public channel must use its fixed main branch.")
        self.branch = "main"
        return self.manifest_at(self.branch)

    def manifest_at(self, revision):
        endpoint = f"repos/{CHANNEL_REPOSITORY}/contents/{MANIFEST_PATH}?ref={quote(revision, safe='')}"
        record = self.api.request("GET", endpoint)
        require(isinstance(record, dict) and record.get("type") == "file"
                and record.get("encoding") == "base64"
                and isinstance(record.get("sha"), str) and GIT_SHA.fullmatch(record["sha"]),
                "GitHub did not return the expected latest.json file and blob SHA.")
        require(type(record.get("size")) is int and 0 < record["size"] < MAX_MANIFEST_BYTES,
                "latest.json exceeds its metadata size limit.")
        require(isinstance(record.get("content"), str)
                and len(record["content"]) <= MAX_MANIFEST_BYTES * 2,
                "latest.json content is missing or too large.")
        try:
            raw = base64.b64decode("".join(record["content"].split()), validate=True)
            require(len(raw) == record["size"], "latest.json size disagrees with its GitHub content.")
            manifest = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise PromotionError("latest.json content is not valid base64 JSON.") from exc
        return validate_manifest(manifest, self.external), record["sha"]

    def release(self, repository, tag):
        self.public_repository(repository)
        data = self.api.request("GET", f"repos/{repository}/releases/tags/{quote(tag, safe='')}")
        require(isinstance(data, dict) and data.get("tag_name") == tag and data.get("draft") is False,
                f"{repository}/{tag} must be the requested published, non-draft release.")
        require(type(data.get("prerelease")) is bool, "Release prerelease state is missing.")
        require(isinstance(data.get("published_at"), str), "Release has no publication timestamp.")
        timestamp(data["published_at"], "Release published_at")
        require(isinstance(data.get("assets"), list) and len(data["assets"]) <= 200,
                "Release asset inventory is missing or too large.")
        return data

    def release_asset(self, game, platform, release, name, tag, version):
        filename(name, platform)
        matches = [a for a in release["assets"] if isinstance(a, dict) and a.get("name") == name]
        require(len(matches) == 1, f"Release must contain exactly one {platform} asset named {name}.")
        asset = matches[0]
        require(asset.get("state") == "uploaded", f"{name} has not finished uploading.")
        require(type(asset.get("size")) is int and 0 < asset["size"] < GITHUB_ASSET_LIMIT,
                f"{name} requires a positive uploaded size.")
        digest = asset.get("digest")
        require(isinstance(digest, str) and digest.startswith("sha256:")
                and SHA256.fullmatch(digest[7:].lower()), f"{name} requires GitHub's SHA-256 digest.")
        extension = next(ext for ext in EXTENSIONS[platform] if name.lower().endswith(ext))
        require(asset.get("content_type") in MIME_TYPES[extension],
                f"{name} content type does not match a supported archive.")
        url = asset.get("browser_download_url")
        require(isinstance(url, str)
                and github_asset_location(url) == (EXPECTED_REPOSITORIES[game], tag, name),
                f"{name} download URL disagrees with the expected repository, tag, or filename.")
        result = {"name": name, "url": url, "sizeBytes": asset["size"],
                  "sha256": digest[7:].lower(), "version": version}
        validate_asset(game, platform, result, self.external)
        return result

    def commit(self, manifest, expected_blob_sha, message):
        validate_manifest(manifest, self.external)
        raw = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        require(len(raw) < MAX_MANIFEST_BYTES, "Updated latest.json exceeds its metadata size limit.")
        require(self.branch == "main", "Current main manifest must be read before writing.")
        # Contents API compares the existing blob SHA and creates one normal Git commit.
        # A conflict aborts this operation; reread and review with a new dry run.
        result = self.api.request("PUT", f"repos/{CHANNEL_REPOSITORY}/contents/{MANIFEST_PATH}", {
            "message": message, "content": base64.b64encode(raw).decode("ascii"),
            "sha": expected_blob_sha, "branch": self.branch,
        })
        require(isinstance(result, dict) and isinstance(result.get("commit"), dict)
                and isinstance(result["commit"].get("sha"), str)
                and GIT_SHA.fullmatch(result["commit"]["sha"]),
                "GitHub accepted the update but returned no valid commit identity; inspect the channel before retrying.")
        return result["commit"]["sha"]

    def promote(self, game, repository, tag, version, windows, linux, macos=None,
                notes=None, apply=False, now=None):
        require(game in EXPECTED_REPOSITORIES, "Unknown game slug.")
        require(game != "jabberwocky", "Jabberwocky uses its reviewed hosted pair; GitHub promotion is not supported.")
        require(repository == EXPECTED_REPOSITORIES[game],
                f"{game} can only use {EXPECTED_REPOSITORIES[game]}.")
        label(tag, "Release tag")
        require(SAFE_TAG.fullmatch(tag), "Release tag may only contain letters, digits, periods, underscores and hyphens.")
        label(version, "Version label", 160)
        if notes is not None:
            label(notes, "Player-facing status note", 2000)
        names = {"windows": windows, "linux": linux}
        if macos is not None:
            names["macos"] = macos
        require(len(set(names.values())) == len(names), "Each platform must name a distinct release asset.")
        for platform, name in names.items():
            filename(name, platform)
        current, blob_sha = self.current()
        release = self.release(repository, tag)
        verified = {platform: self.release_asset(game, platform, release, name, tag, version)
                    for platform, name in names.items()}
        # No current record is mutated until the entire requested pair has passed validation.
        candidate = copy.deepcopy(current)
        record = candidate["games"][game]
        old_assets = copy.deepcopy(record["directAssets"])
        for platform, new_asset in verified.items():
            # Archive-level proof belongs to the exact old bytes. New binaries only
            # receive identity fields verified in this operation, never old QA claims.
            record["directAssets"][platform] = copy.deepcopy(new_asset)
        record["repo"] = repository
        record["tag"] = version
        record["releasePage"] = f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}"
        record["knownPublished"] = True
        candidate["updatedAt"] = now or utc_now()
        record["updatedAt"] = candidate["updatedAt"][:10]
        if notes is not None:
            record["statusNote"] = notes
        validate_manifest(candidate, self.external)
        summary = {"action": "promote", "game": game, "releaseTag": tag,
                   "version": version, "prerelease": release["prerelease"],
                   "expectedManifestBlob": blob_sha, "before": old_assets,
                   "after": copy.deepcopy(record["directAssets"]),
                   "notesBefore": current["games"][game].get("statusNote", ""),
                   "notesAfter": record.get("statusNote", ""),
                   "macosRetained": macos is None and "macos" in old_assets,
                   "applied": bool(apply)}
        if apply:
            summary["commit"] = self.commit(candidate, blob_sha, f"Promote {game} to {version} ({tag})")
        return candidate, summary

    def verify_record_assets(self, game, record):
        releases = {}
        for platform, recorded in record["directAssets"].items():
            location = github_asset_location(recorded["url"])
            if location is None:
                # Exact previously reviewed non-GitHub URLs are permitted by the allowlist.
                # Their digest is a recorded provenance value, not a fresh remote hash check.
                continue
            repository, tag, name = location
            key = (repository, tag)
            if key not in releases:
                releases[key] = self.release(repository, tag)
            asset = self.release_asset(game, platform, releases[key], name, tag, recorded["version"])
            require(asset["sizeBytes"] == recorded["sizeBytes"]
                    and asset["sha256"] == recorded["sha256"].lower(),
                    f"Historical {game}/{platform} size or digest has changed; rollback aborted.")

    def rollback(self, game, revision, apply=False, now=None):
        require(game in EXPECTED_REPOSITORIES, "Unknown game slug.")
        require(isinstance(revision, str) and GIT_SHA.fullmatch(revision),
                "Rollback revision must be a full lowercase 40-character channel commit SHA.")
        current, blob_sha = self.current()
        historical, _ = self.manifest_at(revision)
        self.verify_record_assets(game, historical["games"][game])
        candidate = copy.deepcopy(current)
        candidate["games"][game] = copy.deepcopy(historical["games"][game])
        candidate["updatedAt"] = now or utc_now()
        validate_manifest(candidate, self.external)
        summary = {"action": "rollback", "game": game, "revision": revision,
                   "expectedManifestBlob": blob_sha,
                   "before": copy.deepcopy(current["games"][game]["directAssets"]),
                   "after": copy.deepcopy(candidate["games"][game]["directAssets"]),
                   "applied": bool(apply)}
        if apply:
            summary["commit"] = self.commit(candidate, blob_sha, f"Restore {game} channel from {revision}")
        return candidate, summary


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    subcommands = cli.add_subparsers(dest="command", required=True)
    promote = subcommands.add_parser("promote", help="Point one game at an explicitly verified release pair.")
    promote.add_argument("--game", required=True,
                         choices=[game for game, repository in EXPECTED_REPOSITORIES.items() if repository])
    promote.add_argument("--repository", required=True)
    promote.add_argument("--tag", required=True)
    promote.add_argument("--version", required=True)
    promote.add_argument("--windows", required=True, help="Exact uploaded Windows .zip filename.")
    promote.add_argument("--linux", required=True, help="Exact uploaded Linux archive filename.")
    promote.add_argument("--macos", help="Exact macOS archive filename; omitted means preserve current macOS.")
    promote.add_argument("--notes", help="Optional replacement player-facing status note.")
    rollback = subcommands.add_parser("rollback", help="Restore only one game's record from a channel commit.")
    rollback.add_argument("--game", required=True, choices=EXPECTED_REPOSITORIES)
    rollback.add_argument("--revision", required=True, help="Full channel repository commit SHA.")
    validate = subcommands.add_parser("validate", help="Validate a local manifest; this performs no remote asset check.")
    validate.add_argument("--manifest", type=Path,
                          default=Path(__file__).resolve().parents[1] / MANIFEST_PATH)
    for command in (promote, rollback):
        mode = command.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Commit the validated change to the channel repository.")
        mode.add_argument("--dry-run", action="store_true", help="Validate and print the change without writing (default).")
    return cli


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0].startswith("--") and args[0] not in ("--help", "-h"):
        args.insert(0, "promote")
    cli = parser()
    options = vars(cli.parse_args(args))
    command = options.pop("command")
    options.pop("dry_run", None)
    try:
        if command == "validate":
            path = options["manifest"]
            try:
                require(0 < path.stat().st_size < MAX_MANIFEST_BYTES,
                        "Local manifest exceeds its metadata size limit.")
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise PromotionError("Cannot read local manifest JSON.") from exc
            validate_manifest(value, load_external_allowlist())
            print(json.dumps({"action": "validate", "games": len(value["games"]),
                              "platformAssets": sum(len(g["directAssets"]) for g in value["games"].values()),
                              "remoteAssetsChecked": False}))
            return 0
        channel = Channel(GitHubAPI())
        _, summary = getattr(channel, command)(**options)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if not summary["applied"]:
            print("Dry run only. Repeat with --apply after reviewing the pair and notes.")
        return 0
    except PromotionError as exc:
        print(f"Promotion aborted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
