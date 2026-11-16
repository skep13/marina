"""Unit tests for aiwsd's pure parts. Run: python -m unittest discover -s aiws/tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = tempfile.mkdtemp()
os.environ.update(AIWS_ETC=f"{TMP}/etc", AIWS_STATE=f"{TMP}/state",
                  AIWS_MODELS=f"{TMP}/models", XDG_CONFIG_HOME=f"{TMP}/cfg")
sys.path.insert(0, str(ROOT / "src"))

from aiws import models, projects, store  # noqa: E402
from aiws.agent import tools  # noqa: E402

LIB = {
    "big.yaml": """name: big
file: big.gguf
mmproj: proj.gguf
roles: [chat, code, vision]
profiles:
  interactive: {ctx: 32768, slots: 2, kv: q8_0, vision: false}
  long: {ctx: 131072, slots: 2, kv: q8_0}
""",
    "small.yaml": "name: small\nfile: small.gguf\nroles: [fast, code]\n",
    "emb.yaml": "name: emb\nfile: emb.gguf\nroles: [embed]\nresident: true\n",
    "far.yaml": "name: far\nruntime: remote\nbase_url: http://x:8080\nremote_model: m\nroles: [chat]\n",
    "gone.yaml": "name: gone\nfile: missing.gguf\nroles: [code]\n",
}


def setUpModule():
    (Path(TMP) / "etc/models.d").mkdir(parents=True)
    (Path(TMP) / "models").mkdir()
    for n, body in LIB.items():
        (Path(TMP) / "etc/models.d" / n).write_text(body)
    for f in ("big.gguf", "proj.gguf", "small.gguf", "emb.gguf"):
        (Path(TMP) / "models" / f).write_bytes(b"x")


class Models(unittest.TestCase):
    def test_served_names_include_profiles(self):
        lib, _ = models.library()
        self.assertEqual(models.served_names(lib["big"]), ["big", "big@long"])

    def test_role_resolution_order(self):
        store.put("roles", {})
        m, served = models.resolve("ai:code")
        self.assertEqual(m["name"], "big")          # first present model with the role
        models.set_role("code", "small")
        self.assertEqual(models.resolve("ai:code")[1], "small")
        self.assertEqual(models.resolve("ai:code", {"code": "big@long"})[1], "big@long")
        self.assertEqual(models.resolve("code")[1], "small")   # bare role
        self.assertEqual(models.resolve("nonsense"), (None, None))

    def test_missing_file_never_chosen_by_role(self):
        store.put("roles", {})
        for _ in range(3):
            self.assertNotEqual(models.resolve("ai:code")[0]["name"], "gone")

    def test_llama_swap_config(self):
        cfg = models.llama_swap_config()
        self.assertIn("big", cfg["models"])
        self.assertIn("big@long", cfg["models"])
        self.assertNotIn("far", cfg["models"])      # remote: not ours to run
        self.assertNotIn("gone", cfg["models"])     # file missing
        self.assertIn("-c 32768", cfg["models"]["big"]["cmd"])
        self.assertNotIn("--mmproj", cfg["models"]["big"]["cmd"])   # vision: false
        self.assertIn("--mmproj", cfg["models"]["big@long"]["cmd"])
        self.assertIn("--embeddings", cfg["models"]["emb"]["cmd"])
        self.assertEqual(cfg["groups"]["resident"]["members"], ["emb"])
        self.assertNotIn("emb", cfg["groups"]["gpu"]["members"])

    def test_write_is_idempotent(self):
        p = Path(TMP) / "state/ls.yaml"
        self.assertTrue(models.write_llama_swap_config(p))
        self.assertFalse(models.write_llama_swap_config(p))


class Tokens(unittest.TestCase):
    def test_token_roundtrip_and_revoke(self):
        t = store.new_token("t1", ("chat",))
        self.assertEqual(store.check_token(t)["scopes"], {"chat"})
        self.assertIsNone(store.check_token(t + "x"))
        self.assertIsNone(store.check_token(""))
        store.revoke("t1")
        self.assertIsNone(store.check_token(t))


class AgentConfinement(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "sub").mkdir()
        (self.root / "a.txt").write_text("one\ntwo\n")
        spec = projects.register(self.root, {"name": "p", "agent": {"paths": ["sub"]}})
        self.ctx = tools.Context(spec, gateway=None)

    def test_paths_outside_scope_refused(self):
        with self.assertRaises(tools.Refused):
            tools.write_file(self.ctx, "a.txt", "x")            # project root not allowed
        with self.assertRaises(tools.Refused):
            tools.read_file(self.ctx, "sub/../../etc/passwd")
        self.assertIn("wrote", tools.write_file(self.ctx, "sub/new.txt", "hi"))

    def test_git_dir_protected(self):
        spec = projects.register(self.root, {"name": "p2"})
        ctx = tools.Context(spec, None)
        with self.assertRaises(tools.Refused):
            tools.write_file(ctx, ".git/config", "x")

    def test_edit_needs_unique_match(self):
        spec = projects.register(self.root, {"name": "p3"})
        ctx = tools.Context(spec, None)
        (self.root / "b.txt").write_text("x x")
        self.assertIn("2 times", tools.edit_file(ctx, "b.txt", "x", "y"))

    def test_sudo_refused(self):
        for cmd in ("sudo ls", "ls; sudo rm -rf /", "true && su -", "pkexec id"):
            with self.assertRaises(tools.Refused, msg=cmd):
                tools.terminal_run(self.ctx, cmd)


if __name__ == "__main__":
    unittest.main()
