"""Metadata-only tests; the fake GitHub API never opens a network connection."""

import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "promote_demo.py"
SPEC = importlib.util.spec_from_file_location("promote_demo", SCRIPT)
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)
NOW = "2026-10-04T21:00:00Z"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
HISTORICAL_SHA = "c" * 40
EXTERNAL = demo.load_external_allowlist()


def asset(repository, platform, tag="old", version="old"):
    name = f"Demo-{platform}-{'old' if tag == 'old' else 'new'}" + (".tar.gz" if platform == "linux" else ".zip")
    return {"name": name, "url": demo.release_url(repository, tag, name),
            "sizeBytes": 12345, "sha256": "1" * 64, "version": version,
            "retainedMetadata": {"review": "actual packaging review"}}


def manifest():
    value = {"schemaVersion": 1, "updatedAt": NOW, "retainedRoot": {"format": "one"}, "games": {
        slug: {"tag": "old", "updatedAt": "2026-09-30", "repo": repository,
               "knownPublished": True, "title": slug, "statusNote": "Previous notes",
               "buildNotes": ["Retain player limitations"], "webDemo": "/demos/golden-ocean/",
               "directAssets": {p: asset(repository, p) for p in ("windows", "linux", "macos")},
               "customRecord": {"keep": True}}
        for slug, repository in demo.EXPECTED_REPOSITORIES.items()
    }}
    record = value["games"]["jabberwocky"]
    record["directAssets"].pop("macos")
    for platform, stored in record["directAssets"].items():
        stored["url"] = next(iter(EXTERNAL["jabberwocky"][platform]))
        stored["name"] = stored["url"].rsplit("/", 1)[1]
    return value


def release(record, tag):
    return {"tag_name": tag, "draft": False, "prerelease": True, "published_at": NOW,
            "assets": [{"name": a["name"], "state": "uploaded", "size": a["sizeBytes"],
                        "digest": "sha256:" + a["sha256"],
                        "content_type": "application/gzip" if a["name"].endswith(".tar.gz") else "application/zip",
                        "browser_download_url": a["url"]}
                       for a in record["directAssets"].values()]}


class FakeAPI:
    def __init__(self):
        self.manifest = manifest()
        self.historical = copy.deepcopy(self.manifest)
        self.calls = []
        self.puts = []
        self.conflict = False
        self.repositories = {repo: {"full_name": repo, "private": False, "default_branch": "main"}
                             for repo in (*demo.EXPECTED_REPOSITORIES.values(), demo.CHANNEL_REPOSITORY) if repo}
        self.releases = {}
        for game, record in self.manifest["games"].items():
            repo = demo.EXPECTED_REPOSITORIES[game]
            if not repo:
                continue
            self.releases[(repo, "old")] = release(record, "old")
            new_record = {"directAssets": {p: asset(repo, p, "new", "new label")
                                           for p in ("windows", "linux", "macos")}}
            self.releases[(repo, "new")] = release(new_record, "new")

    def request(self, method, endpoint, body=None):
        self.calls.append((method, endpoint))
        prefix = f"repos/{demo.CHANNEL_REPOSITORY}/contents/latest.json"
        if method == "GET" and endpoint.startswith(prefix + "?ref="):
            selected = self.historical if endpoint.endswith(HISTORICAL_SHA) else self.manifest
            raw = (json.dumps(selected) + "\n").encode()
            return {"type": "file", "encoding": "base64", "size": len(raw),
                    "sha": OLD_SHA, "content": base64.b64encode(raw).decode()}
        if method == "PUT" and endpoint == prefix:
            self.puts.append(copy.deepcopy(body))
            if self.conflict or body["sha"] != OLD_SHA:
                raise demo.PromotionError("GitHub conflict. No retry or force update was attempted.")
            self.manifest = json.loads(base64.b64decode(body["content"]))
            return {"commit": {"sha": NEW_SHA}}
        if method == "GET" and "/releases/tags/" in endpoint:
            repo, tag = endpoint.removeprefix("repos/").split("/releases/tags/")
            if (repo, tag) not in self.releases:
                raise demo.PromotionError("Release missing")
            return copy.deepcopy(self.releases[(repo, tag)])
        if method == "GET" and endpoint.startswith("repos/"):
            repository = endpoint.removeprefix("repos/")
            if repository in self.repositories:
                return copy.deepcopy(self.repositories[repository])
        raise AssertionError(f"Unexpected API call {method} {endpoint}")


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.game = "golden-keep-rts"
        self.repo = demo.EXPECTED_REPOSITORIES[self.game]

    def run_promote(self, **overrides):
        options = {"game": self.game, "repository": self.repo, "tag": "new", "version": "new label",
                   "windows": "Demo-windows-new.zip", "linux": "Demo-linux-new.tar.gz", "now": NOW}
        options.update(overrides)
        return demo.Channel(self.api, external=EXTERNAL).promote(**options)

    def failed_promote(self, **options):
        before = copy.deepcopy(self.api.manifest)
        with self.assertRaises(demo.PromotionError):
            self.run_promote(apply=True, **options)
        self.assertEqual(before, self.api.manifest)
        self.assertEqual([], self.api.puts)

    def test_dry_run_is_default_and_pair_is_verified(self):
        before = copy.deepcopy(self.api.manifest)
        candidate, summary = self.run_promote()
        self.assertFalse(summary["applied"])
        self.assertTrue(summary["prerelease"])
        self.assertEqual([], self.api.puts)
        self.assertEqual(before, self.api.manifest)
        self.assertEqual("new label", candidate["games"][self.game]["directAssets"]["windows"]["version"])
        self.assertEqual("new label", candidate["games"][self.game]["directAssets"]["linux"]["version"])

    def test_apply_commits_both_platforms_once_with_expected_blob_sha(self):
        _, summary = self.run_promote(apply=True)
        self.assertEqual(1, len(self.api.puts))
        self.assertEqual(OLD_SHA, self.api.puts[0]["sha"])
        self.assertEqual("main", self.api.puts[0]["branch"])
        self.assertNotIn("force", self.api.puts[0])
        self.assertEqual(NEW_SHA, summary["commit"])
        self.assertEqual("new label", self.api.manifest["games"][self.game]["directAssets"]["linux"]["version"])

    def test_conflict_aborts_without_retry_or_partial_update(self):
        self.api.conflict = True
        before = copy.deepcopy(self.api.manifest)
        with self.assertRaisesRegex(demo.PromotionError, "conflict"):
            self.run_promote(apply=True)
        self.assertEqual(before, self.api.manifest)
        self.assertEqual(1, len(self.api.puts))

    def test_macos_other_games_unknown_fields_and_notes_are_retained(self):
        before = copy.deepcopy(self.api.manifest)
        candidate, summary = self.run_promote()
        record = candidate["games"][self.game]
        self.assertTrue(summary["macosRetained"])
        self.assertEqual(before["games"][self.game]["directAssets"]["macos"], record["directAssets"]["macos"])
        for game in before["games"]:
            if game != self.game:
                self.assertEqual(before["games"][game], candidate["games"][game])
        for field in ("customRecord", "buildNotes", "statusNote", "webDemo"):
            self.assertEqual(before["games"][self.game][field], record[field])
        self.assertEqual(before["retainedRoot"], candidate["retainedRoot"])
        self.assertNotIn("retainedMetadata", record["directAssets"]["windows"])

    def test_replaced_binary_does_not_inherit_stale_archive_proof(self):
        for platform in ("windows", "linux"):
            self.api.manifest["games"][self.game]["directAssets"][platform].update({
                "sizeLabel": "Previous 1 GB archive", "verification": "old extracted archive passed",
                "sourceCommit": "d" * 40, "runtimeQA": {"allTestsPassed": True},
            })
        candidate, _ = self.run_promote()
        for platform in ("windows", "linux"):
            self.assertEqual({"name", "url", "sizeBytes", "sha256", "version"},
                             set(candidate["games"][self.game]["directAssets"][platform]))

    def test_explicit_macos_replacement(self):
        candidate, summary = self.run_promote(macos="Demo-macos-new.zip", notes="Current limitations")
        self.assertFalse(summary["macosRetained"])
        self.assertEqual("new label", candidate["games"][self.game]["directAssets"]["macos"]["version"])
        self.assertEqual("Current limitations", candidate["games"][self.game]["statusNote"])

    def test_missing_second_platform_prevents_first_platform_promotion(self):
        self.api.releases[(self.repo, "new")]["assets"] = self.api.releases[(self.repo, "new")]["assets"][:1]
        self.failed_promote()

    def test_duplicate_exact_filename_is_rejected(self):
        self.api.releases[(self.repo, "new")]["assets"].append(copy.deepcopy(self.api.releases[(self.repo, "new")]["assets"][0]))
        self.failed_promote()

    def test_incomplete_upload_is_rejected(self):
        self.api.releases[(self.repo, "new")]["assets"][1]["state"] = "new"
        self.failed_promote()

    def test_size_required_positive_integer_not_boolean(self):
        for invalid in (None, 0, -1, True, "12345", demo.MAX_ASSET_BYTES + 1):
            with self.subTest(size=invalid):
                self.api.releases[(self.repo, "new")]["assets"][1]["size"] = invalid
                self.failed_promote()

    def test_sha256_digest_required(self):
        for invalid in (None, "", "sha1:" + "1" * 40, "sha256:" + "1" * 63, "sha256:" + "z" * 64):
            with self.subTest(digest=invalid):
                self.api.releases[(self.repo, "new")]["assets"][1]["digest"] = invalid
                self.failed_promote()

    def test_sha256_normalized_lowercase(self):
        self.api.releases[(self.repo, "new")]["assets"][1]["digest"] = "sha256:" + "A" * 64
        candidate, _ = self.run_promote()
        self.assertEqual("a" * 64, candidate["games"][self.game]["directAssets"]["linux"]["sha256"])

    def test_draft_wrong_release_tag_and_unpublished_release_are_rejected(self):
        for key, value in (("draft", True), ("tag_name", "another-tag"), ("published_at", None)):
            with self.subTest(field=key):
                old = self.api.releases[(self.repo, "new")][key]
                self.api.releases[(self.repo, "new")][key] = value
                self.failed_promote()
                self.api.releases[(self.repo, "new")][key] = old

    def test_prerelease_is_allowed_when_tag_was_explicitly_chosen(self):
        _, summary = self.run_promote()
        self.assertTrue(summary["prerelease"])

    def test_private_repository_is_rejected(self):
        self.api.repositories[self.repo]["private"] = True
        self.failed_promote()

    def test_private_channel_repository_is_rejected(self):
        self.api.repositories[demo.CHANNEL_REPOSITORY]["private"] = True
        self.failed_promote()

    def test_channel_cannot_switch_from_fixed_main_branch(self):
        self.api.repositories[demo.CHANNEL_REPOSITORY]["default_branch"] = "development"
        self.failed_promote()

    def test_github_two_gib_boundary_is_rejected(self):
        for size in (demo.GITHUB_ASSET_LIMIT, demo.GITHUB_ASSET_LIMIT + 1):
            with self.subTest(size=size):
                self.api.releases[(self.repo, "new")]["assets"][1]["size"] = size
                self.failed_promote()

    def test_release_tags_outside_edge_contract_are_rejected_before_network(self):
        for tag in ("v1+preview", "feature/1", "with space", "v%31", "v1?query"):
            with self.subTest(tag=tag):
                self.failed_promote(tag=tag)
                self.assertEqual([], self.api.calls)

    def test_version_and_filename_limits_match_edge_utf16_and_ascii_contract(self):
        self.failed_promote(version="x" * 161)
        self.failed_promote(version="\U0001f600" * 81)
        self.failed_promote(windows="x" * 177 + ".zip")
        self.failed_promote(windows="Demo+new.zip")
        stored = asset(self.repo, "windows")
        stored["name"] = "A " + "x" * 174 + ".zip"
        stored["url"] = demo.release_url(self.repo, "old", stored["name"])
        stored["version"] = "x" * 160
        demo.validate_asset(self.game, "windows", stored, EXTERNAL)

    def test_uppercase_recorded_sha_is_rejected(self):
        self.api.manifest["games"][self.game]["directAssets"]["linux"]["sha256"] = "A" * 64
        self.failed_promote()

    def test_candidate_manifest_cannot_exceed_edge_limit(self):
        base = len((json.dumps(self.api.manifest, indent=2, ensure_ascii=False) + "\n").encode())
        self.api.manifest["retainedRoot"]["padding"] = "x" * (demo.MAX_MANIFEST_BYTES - base - 800)
        demo.validate_manifest(self.api.manifest, EXTERNAL)
        self.failed_promote(notes="x" * 2000)

    def test_game_text_and_build_notes_limits_match_edge(self):
        for field, value in (("title", "x" * 2001), ("statusNote", "\U0001f600" * 1001),
                             ("buildNotes", ["x"] * 31), ("buildNotes", ["x" * 2001])):
            with self.subTest(field=field):
                original = copy.deepcopy(self.api.manifest)
                self.api.manifest["games"][self.game][field] = value
                self.failed_promote()
                self.api.manifest = original

    def test_no_github_promotion_for_jabberwocky(self):
        self.failed_promote(game="jabberwocky", repository="")
        self.assertEqual([], self.api.calls)

    def test_wrong_repository_cannot_be_substituted(self):
        self.failed_promote(repository="redgargoyle/goldenkeep-rts")
        self.assertEqual([], self.api.calls)

    def test_api_repository_identity_cannot_be_substituted(self):
        self.api.repositories[self.repo]["full_name"] = "someone/Goldenkeep-Releases"
        self.failed_promote()

    def test_asset_download_repository_tag_or_name_cannot_be_substituted(self):
        for url in (
            "https://github.com/redgargoyle/goldenkeep-rts/releases/download/new/Demo-linux-new.tar.gz",
            demo.release_url(self.repo, "old", "Demo-linux-new.tar.gz"),
            demo.release_url(self.repo, "new", "Another-linux.tar.gz"),
            "https://evil.example/Demo-linux-new.tar.gz",
            "https://github.com@evil.example/file.zip",
            demo.release_url(self.repo, "new", "Demo-linux-new.tar.gz") + "?token=bad",
        ):
            with self.subTest(url=url):
                self.api.releases[(self.repo, "new")]["assets"][1]["browser_download_url"] = url
                self.failed_promote()

    def test_invalid_platform_filename_and_mime_are_rejected(self):
        self.failed_promote(windows="Game.exe")
        self.failed_promote(linux="../Game.tar.gz")
        self.failed_promote(linux="Game.tar.gz?token=anything")
        self.api.releases[(self.repo, "new")]["assets"][1]["content_type"] = "text/html"
        self.failed_promote()

    def test_control_characters_cannot_enter_commit_message(self):
        self.failed_promote(version="v1\nplease push")
        self.failed_promote(tag="release\x00")

    def test_corrupt_current_manifest_cannot_be_promoted(self):
        self.api.manifest["games"]["chantilly"]["directAssets"]["linux"]["url"] = "https://evil.example/demo.tar.gz"
        self.failed_promote()

    def test_release_page_and_browser_demo_cannot_point_to_arbitrary_sites(self):
        for field, url in (("releasePage", "https://evil.example/release"),
                           ("releasePage", "https://github.com/redgargoyle/goldenkeep-rts/releases/tag/old"),
                           ("webDemo", "//evil.example/demos/game/"),
                           ("webDemo", "javascript:alert(1)"),
                           ("webDemo", "/demos/../private/")):
            with self.subTest(field=field, url=url):
                original = copy.deepcopy(self.api.manifest)
                self.api.manifest["games"]["chantilly"][field] = url
                self.failed_promote()
                self.api.manifest = original

    def test_current_manifest_has_exact_game_set_and_complete_pairs(self):
        for corrupt in ("unknown-game", "missing-platform", "missing-digest"):
            with self.subTest(corrupt=corrupt):
                original = copy.deepcopy(self.api.manifest)
                if corrupt == "unknown-game":
                    self.api.manifest["games"]["unknown"] = {}
                elif corrupt == "missing-platform":
                    del self.api.manifest["games"][self.game]["directAssets"]["linux"]
                else:
                    del self.api.manifest["games"][self.game]["directAssets"]["linux"]["sha256"]
                self.failed_promote()
                self.api.manifest = original

    def test_rollback_restores_one_game_only_in_one_cas_commit(self):
        self.run_promote(apply=True)
        self.api.puts.clear()
        self.api.manifest["games"]["chantilly"]["statusNote"] = "Concurrent independent update"
        before = copy.deepcopy(self.api.manifest)
        candidate, summary = demo.Channel(self.api, external=EXTERNAL).rollback(self.game, HISTORICAL_SHA, apply=True, now=NOW)
        self.assertEqual(self.api.historical["games"][self.game], candidate["games"][self.game])
        for game in before["games"]:
            if game != self.game:
                self.assertEqual(before["games"][game], candidate["games"][game])
        self.assertEqual(1, len(self.api.puts))
        self.assertEqual(OLD_SHA, self.api.puts[0]["sha"])
        self.assertEqual(NEW_SHA, summary["commit"])

    def test_rollback_is_dry_run_by_default(self):
        _, summary = demo.Channel(self.api, external=EXTERNAL).rollback(self.game, HISTORICAL_SHA, now=NOW)
        self.assertFalse(summary["applied"])
        self.assertEqual([], self.api.puts)

    def test_rollback_requires_full_channel_commit_sha(self):
        for revision in ("main", "c" * 7, "c" * 39, "C" * 40, "../other"):
            with self.subTest(revision=revision):
                with self.assertRaises(demo.PromotionError):
                    demo.Channel(self.api, external=EXTERNAL).rollback(self.game, revision, apply=True)
        self.assertEqual([], self.api.puts)

    def test_rollback_rejects_changed_or_deleted_historical_asset(self):
        self.api.releases[(self.repo, "old")]["assets"][1]["digest"] = "sha256:" + "2" * 64
        with self.assertRaisesRegex(demo.PromotionError, "has changed"):
            demo.Channel(self.api, external=EXTERNAL).rollback(self.game, HISTORICAL_SHA, apply=True)
        self.assertEqual([], self.api.puts)

    def test_rollback_checks_retained_mac_from_its_own_release_tag(self):
        self.api.releases[(self.repo, "old")]["assets"][2]["state"] = "new"
        with self.assertRaises(demo.PromotionError):
            demo.Channel(self.api, external=EXTERNAL).rollback(self.game, HISTORICAL_SHA, apply=True)
        self.assertEqual([], self.api.puts)

    def test_no_archive_download_endpoint_is_requested(self):
        self.run_promote(apply=True)
        for _, endpoint in self.api.calls:
            self.assertTrue(endpoint.startswith("repos/"))
            self.assertNotIn("releases/download/", endpoint)
            self.assertNotIn("/releases/assets/", endpoint)


class ExternalAllowlistTests(unittest.TestCase):
    def test_existing_exact_jabber_pair_is_supported(self):
        external = demo.load_external_allowlist()
        value = manifest()
        record = value["games"]["jabberwocky"]
        record["repo"] = ""
        for platform, stored in record["directAssets"].items():
            stored["url"] = next(iter(external["jabberwocky"][platform]))
            stored["name"] = stored["url"].rsplit("/", 1)[1]
        demo.validate_manifest(value, external)
        record["directAssets"]["linux"]["url"] = record["directAssets"]["linux"]["url"].replace("3a0193d5", "01234567")
        with self.assertRaises(demo.PromotionError):
            demo.validate_manifest(value, external)

    def test_allowlist_cannot_approve_arbitrary_origin_or_another_game(self):
        for game, platform, url in (
            ("jabberwocky", "linux", "https://evil.example/Jabberwocky-2026-10-03-3a0193d5-Linux.zip"),
            ("chantilly", "linux", "https://kadabra-video-library-review.amcorblue.chatgpt.site/downloads/Jabberwocky-2026-10-03-3a0193d5-Linux.zip"),
            ("jabberwocky", "linux", "https://kadabra-video-library-review.amcorblue.chatgpt.site/downloads/unversioned.zip"),
            ("jabberwocky", "macos", "https://kadabra-video-library-review.amcorblue.chatgpt.site/downloads/Jabberwocky-2026-10-03-3a0193d5-Linux.zip"),
            ("jabberwocky", "linux", "https://kadabra-video-library-review.amcorblue.chatgpt.site/downloads/Jabberwocky-2026-10-03-3a0193d-Linux.zip"),
            ("jabberwocky", "linux", "https://kadabra-video-library-review.amcorblue.chatgpt.site/downloads/Jabberwocky-2026-10-03-3a0193d51-Linux.zip"),
        ):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "config.json"
                path.write_text(json.dumps({"schemaVersion": 1, "approvedExternalAssets": {game: {platform: [url]}}}))
                with self.assertRaises(demo.PromotionError):
                    demo.load_external_allowlist(path)

    def test_jabber_requires_empty_repo_and_matching_exact_archive_name(self):
        value = manifest()
        value["games"]["jabberwocky"]["repo"] = "redgargoyle/Jabberwocky-Releases"
        with self.assertRaises(demo.PromotionError):
            demo.validate_manifest(value, EXTERNAL)
        value = manifest()
        value["games"]["jabberwocky"]["directAssets"]["linux"]["name"] = "Other-Linux.zip"
        with self.assertRaises(demo.PromotionError):
            demo.validate_manifest(value, EXTERNAL)

    def test_malformed_url_is_rejected_without_parser_traceback(self):
        stored = asset(demo.EXPECTED_REPOSITORIES["chantilly"], "windows")
        stored["url"] = "https://[malformed"
        with self.assertRaises(demo.PromotionError):
            demo.validate_asset("chantilly", "windows", stored, {})


if __name__ == "__main__":
    unittest.main()
