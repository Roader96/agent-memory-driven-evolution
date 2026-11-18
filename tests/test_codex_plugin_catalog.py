"""Plugin baseline regressions using isolated Codex homes and caches."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codex_evolution


class TestPluginCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "codex"
        self.home.mkdir()
        self.market = Path(self.tmp.name) / "market"

    def skill(self, root, name="documents"):
        path = root / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic skill\n")
        return path

    def plugin(self, name="documents", version="2.0", skills=None):
        root = self.home / "plugins/cache/example" / name / version
        manifest = root / ".codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"name": name, "version": version,
                                       "skills": skills or "./skills"}))
        self.skill(root, name)
        return root

    def configure(self, enabled=True):
        (self.home / "config.toml").write_text(
            '[plugins."documents@example"]\n'
            f'enabled = {str(enabled).lower()}\n'
            '[marketplaces.example]\nsource_type = "local"\n'
            f'source = {json.dumps(str(self.market))}\n')

    def source(self, version):
        catalog = self.market / ".agents/plugins/marketplace.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(json.dumps({"plugins": [{"name": "documents", "source": {
            "source": "local", "path": "./plugins/documents"}}]}))
        root = self.market / "plugins/documents"
        manifest = root / ".codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"name": "documents", "version": version,
                                       "skills": "./skills"}))
        self.skill(root)
        return root

    def test_prepare_includes_enabled_plugin_and_both_skill_roots(self):
        self.configure()
        self.plugin()
        self.skill(self.home, "personal")
        self.skill(self.home.parent / ".agents", "shared")
        memory = self.home.parent / "memory"
        packet = codex_evolution.prepare(memory, self.home)
        data = json.loads(packet.read_text())
        self.assertEqual({s["name"] for s in data["skill_catalog"]},
                         {"documents", "personal", "shared"})
        self.assertEqual(data["skill_catalog_warnings"], [])
        for skill in data["skill_catalog"]:
            self.assertEqual(skill["usage_quality"], "unknown")
            self.assertIsNone(skill["load_sessions"])

    def test_disabled_and_unconfigured_caches_are_excluded(self):
        self.configure(enabled=False)
        self.plugin()
        self.plugin("unused")
        self.assertEqual(codex_evolution.skill_catalog(self.home), ([], []))

    def test_marketplace_version_wins_over_newer_cache(self):
        self.configure()
        root = self.plugin(version="2.0")
        self.plugin(version="10.0")
        self.source("2.0")
        skills, warnings = codex_evolution.skill_catalog(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["path"], str(root / "skills/documents/SKILL.md"))
        self.assertEqual(skills[0]["plugin_version"], "2.0")

    def test_ambiguous_cache_produces_visible_warning(self):
        self.configure()
        self.plugin(version="2.0")
        self.plugin(version="10.0")
        skills, warnings = codex_evolution.skill_catalog(self.home)
        self.assertEqual(skills, [])
        self.assertIn("active version", warnings[0])

    def test_uncached_source_version_is_used(self):
        self.configure()
        self.plugin(version="old")
        source = self.source("current")
        skills, warnings = codex_evolution.skill_catalog(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(skills[0]["path"], str(source / "skills/documents/SKILL.md"))

    def test_symlink_aliases_are_counted_once(self):
        self.configure()
        root = self.plugin()
        self.skill(root, "second")
        target = root / "skills/documents"
        personal = self.home / "skills"
        personal.mkdir()
        (personal / "alias").symlink_to(target, target_is_directory=True)
        # An explicit file alias is also supported by manifest declarations.
        manifest = root / ".codex-plugin/plugin.json"
        data = json.loads(manifest.read_text())
        data["skills"] = ["./skills", "./skills/documents/SKILL.md"]
        manifest.write_text(json.dumps(data))
        skills, warnings = codex_evolution.skill_catalog(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(len(skills), 2)
        self.assertEqual(len({Path(s["path"]).resolve() for s in skills}), 2)

    def test_same_named_skills_in_distinct_plugins_are_preserved(self):
        self.configure()
        self.plugin()
        root = self.plugin("other")
        self.skill(root, "documents")
        with (self.home / "config.toml").open("a") as f:
            f.write('[plugins."other@example"]\nenabled = true\n')
        skills, warnings = codex_evolution.skill_catalog(self.home)
        self.assertEqual(warnings, [])
        self.assertEqual(sum(s["name"] == "documents" for s in skills), 2)

    def test_missing_declared_skills_are_reported(self):
        self.configure()
        self.plugin(skills="./missing")
        skills, warnings = codex_evolution.skill_catalog(self.home)
        self.assertEqual(skills, [])
        self.assertIn("location missing", warnings[0])

    def test_python39_config_parser_handles_quotes_comments_and_disabled(self):
        self.configure(enabled=False)
        with (self.home / "config.toml").open("a") as f:
            f.write("[plugins.'other@example'] # comment\nenabled = true # comment\n")
        with patch.dict(sys.modules, {"tomllib": None}):
            config, warnings = codex_evolution.plugin_config(self.home / "config.toml")
        self.assertEqual(warnings, [])
        self.assertFalse(config["plugins"]["documents@example"]["enabled"])
        self.assertTrue(config["plugins"]["other@example"]["enabled"])
        self.assertEqual(config["marketplaces"]["example"]["source"], str(self.market))

    def test_unsupported_old_runtime_config_is_visible(self):
        path = self.home / "config.toml"
        path.write_text('plugins = { "documents@example" = { enabled = true } }\n')
        with patch.dict(sys.modules, {"tomllib": None}):
            _, warnings = codex_evolution.plugin_config(path)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
