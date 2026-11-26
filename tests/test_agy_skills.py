"""Unit, integration, and security tests for agy-skills."""

from __future__ import annotations

import http.client
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agy_skills import cli  # noqa: E402


def _write_skill(base_dir: pathlib.Path, folder: str, content: str, scripts: list[str] | None = None) -> pathlib.Path:
    sdir = base_dir / folder
    sdir.mkdir(parents=True, exist_ok=True)
    md = sdir / "SKILL.md"
    md.write_text(content, encoding="utf-8")
    if scripts:
        sc_dir = sdir / "scripts"
        sc_dir.mkdir(exist_ok=True)
        for sname in scripts:
            (sc_dir / sname).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return md


class FrontmatterTests(unittest.TestCase):
    def test_parses_folded_block_and_leading_html_comments(self) -> None:
        raw = (
            "<!-- disableFinding(A) -->\n"
            "<!-- disableFinding(B) -->\n"
            "---\n"
            "name: secure-skill\n"
            "description: >-\n"
            "  First line of description.\n"
            "  Second line continues.\n"
            "disable-model-invocation: true\n"
            "---\n\n# Body\n"
        )
        fm, body, warns = cli.parse_frontmatter(raw)
        self.assertEqual(warns, [])
        self.assertEqual(fm["name"], "secure-skill")
        self.assertEqual(fm["description"], "First line of description. Second line continues.")
        self.assertIs(fm["disable-model-invocation"], True)
        self.assertIn("# Body", body)

    def test_atomic_toggle_round_trip_preserves_comments_and_description(self) -> None:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="agy_fm_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        md = tmp / "SKILL.md"
        original = (
            "<!-- leading comment -->\n"
            "---\n"
            "name: demo\n"
            "description: >\n"
            "  Keep this description intact.\n"
            "---\n\n# Demo Body\n"
        )
        md.write_text(original, encoding="utf-8")

        self.assertTrue(cli.update_disable_model_invocation(md, explicit=True))
        fm1, body1, _ = cli.parse_frontmatter(md.read_text(encoding="utf-8"))
        self.assertIs(fm1["disable-model-invocation"], True)
        self.assertEqual(fm1["description"], "Keep this description intact.")
        self.assertIn("# Demo Body", body1)
        self.assertIn("<!-- leading comment -->", md.read_text(encoding="utf-8"))

        # Idempotent no-op when already explicit
        self.assertFalse(cli.update_disable_model_invocation(md, explicit=True))

        # Toggle back to auto
        self.assertTrue(cli.update_disable_model_invocation(md, explicit=False))
        fm2, _, _ = cli.parse_frontmatter(md.read_text(encoding="utf-8"))
        self.assertNotIn("disable-model-invocation", fm2)
        self.assertEqual(fm2["description"], "Keep this description intact.")


class DiscoveryAndPrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="agy_disc_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.repo = self.tmp / "repo"
        (self.repo / ".git").mkdir(parents=True)

        # Workspace skill (Priority 1)
        _write_skill(
            self.repo / ".agents" / "skills",
            "shared-skill",
            "---\nname: shared-skill\ndescription: Workspace override.\n---\n",
            scripts=["run.py"],
        )

        # Global skill (Priority 3) - one unique explicit, one shadowed by workspace
        _write_skill(
            self.home / ".gemini" / "config" / "skills",
            "shared-skill",
            "---\nname: shared-skill\ndescription: Global copy.\n---\n",
        )
        _write_skill(
            self.home / ".gemini" / "config" / "skills",
            "citation-checker",
            "---\nname: citation-checker\ndisable-model-invocation: true\ndescription: Explicit citation checker.\n---\n",
            scripts=["a.py", "b.py"],
        )

        # Plugin skill (Priority 4)
        _write_skill(
            self.home / ".gemini" / "config" / "plugins" / "demo-plugin" / "skills",
            "plugin-skill",
            "---\nname: plugin-skill\ndescription: Provided by plugin.\n---\n",
        )

        # Built-in skill (Priority 5)
        _write_skill(
            self.home / ".gemini" / "antigravity-cli" / "builtin" / "skills",
            "internal-helper",
            "---\nname: internal-helper\ndisable-slash-command: true\ndescription: Auto-only built-in.\n---\n",
        )

        # Global skills.json pointing to external dir with exclude + camelCase warning
        ext_dir = self.home / ".external" / "skills"
        _write_skill(
            ext_dir,
            "excluded-skill",
            "---\nname: excluded-skill\ndescription: Should be excluded.\n---\n",
        )
        _write_skill(
            ext_dir,
            "camel-warn",
            "---\nname: camel-warn\ndisableModelInvocation: true\ndescription: Uses wrong casing.\n---\n",
        )
        sj = self.home / ".gemini" / "config" / "skills.json"
        sj.write_text(
            json.dumps({"entries": [{"path": str(ext_dir), "exclude": ["excluded-skill"]}]}),
            encoding="utf-8",
        )

    def test_precedence_shadowing_exclude_and_warnings(self) -> None:
        records = cli.discover_all_skills(cwd=self.repo, home=self.home)
        by_name: dict[str, list[cli.SkillRecord]] = {}
        for r in records:
            by_name.setdefault(r.name, []).append(r)

        # Workspace wins over global
        shared = by_name["shared-skill"]
        self.assertEqual(len(shared), 2)
        ws_rec = next(r for r in shared if r.source_kind == "workspace")
        gl_rec = next(r for r in shared if r.source_kind == "global")
        self.assertEqual(ws_rec.status, "active")
        self.assertEqual(gl_rec.status, "shadowed")
        self.assertIn("workspace", gl_rec.shadowed_by or "")

        # Explicit skill detected with 0 resident tokens
        cit = by_name["citation-checker"][0]
        self.assertEqual(cit.invocation_mode, "explicit")
        self.assertEqual(cit.est_resident_tokens, 0)
        self.assertEqual(len(cit.scripts), 2)

        # Built-in auto-only skill is non-editable
        bi = by_name["internal-helper"][0]
        self.assertEqual(bi.invocation_mode, "auto-only")
        self.assertFalse(bi.editable)

        # Excluded skill recorded as excluded
        ex = by_name["excluded-skill"][0]
        self.assertEqual(ex.status, "excluded")

        # camelCase disableModelInvocation generates warning and remains auto+slash
        cw = by_name["camel-warn"][0]
        self.assertEqual(cw.invocation_mode, "auto+slash")
        self.assertTrue(any("disableModelInvocation" in w for w in cw.warnings))


class WebSecurityAndApiTests(unittest.TestCase):
    def test_static_frontend_security_hygiene(self) -> None:
        src = (ROOT / "src" / "agy_skills" / "cli.py").read_text(encoding="utf-8")
        non_comment = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        for banned in ("innerHTML", "outerHTML", "document.write", "insertAdjacentHTML", "unsafe-inline", "unsafe-eval", "0.0.0.0"):
            self.assertNotIn(banned, non_comment)
        self.assertIsNone(re.search(r"\b(?:alert|confirm|prompt)\s*\(", cli.WEB_JS))

    def test_localhost_web_headers_csrf_and_mode_toggle(self) -> None:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="agy_web_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        ws = tmp / "ws"
        demo_md = _write_skill(
            ws / ".agents" / "skills",
            "web-demo",
            "---\nname: web-demo\ndescription: Web API test skill.\n---\n\n# Demo\n",
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        env = dict(os.environ)
        env["HOME"] = str(tmp / "fake_home")
        (tmp / "fake_home").mkdir()

        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "agy_skills" / "cli.py"), "--cwd", str(ws), "web", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            html_body = ""
            hdrs: dict[str, str] = {}
            for _ in range(40):
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    conn.request("GET", "/")
                    resp = conn.getresponse()
                    html_body = resp.read().decode("utf-8")
                    hdrs = dict(resp.getheaders())
                    conn.close()
                    if resp.status == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            else:
                self.fail("Web server failed to start")

            self.assertEqual(hdrs.get("X-Frame-Options"), "DENY")
            self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(hdrs.get("Cache-Control"), "no-store")
            csp = hdrs.get("Content-Security-Policy", "")
            self.assertIn("script-src 'nonce-", csp)
            self.assertNotIn("unsafe-inline", csp)
            self.assertIn("frame-ancestors 'none'", csp)

            m_csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', html_body)
            self.assertIsNotNone(m_csrf)
            csrf = m_csrf.group(1)  # type: ignore[union-attr]

            # Method allow-list rejects DELETE
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("DELETE", "/api/skills")
            r_del = conn.getresponse()
            r_del.read()
            conn.close()
            self.assertEqual(r_del.status, 405)

            # Fetch skills
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/api/skills")
            r_ls = conn.getresponse()
            skills = json.loads(r_ls.read().decode("utf-8"))["skills"]
            conn.close()
            demo = next(x for x in skills if x["name"] == "web-demo")

            # Traversal / unknown ID blocked with 404
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/api/body?id=../../etc/passwd")
            r_trav = conn.getresponse()
            r_trav.read()
            conn.close()
            self.assertEqual(r_trav.status, 404)

            payload = json.dumps({"id": demo["id"], "mode": "explicit"})

            # Missing Origin -> 403
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("POST", "/api/mode", body=payload, headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
            r_orig = conn.getresponse()
            r_orig.read()
            conn.close()
            self.assertEqual(r_orig.status, 403)

            # Invalid CSRF -> 403
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request(
                "POST",
                "/api/mode",
                body=payload,
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": "invalid"},
            )
            r_csrf = conn.getresponse()
            r_csrf.read()
            conn.close()
            self.assertEqual(r_csrf.status, 403)

            # Valid POST toggles skill cleanly
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request(
                "POST",
                "/api/mode",
                body=payload,
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": csrf},
            )
            r_ok = conn.getresponse()
            ok_data = json.loads(r_ok.read().decode("utf-8"))
            conn.close()
            self.assertEqual(r_ok.status, 200)
            self.assertTrue(ok_data["ok"])
            self.assertIn("disable-model-invocation: true", demo_md.read_text(encoding="utf-8"))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
