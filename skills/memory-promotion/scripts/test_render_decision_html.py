#!/usr/bin/env python3
"""测试 memory-promotion 交互式 HTML 决策页生成器。"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import render_decision_html as R


class RenderDecisionHtmlTests(unittest.TestCase):
    def test_render_contains_controls_and_escapes_script_breakout(self) -> None:
        payload = {
            "generated_at": "2026-11-25 12:40",
            "projects": [
                {
                    "name": "web-v1",
                    "total": 5,
                    "keep_files": ["keep-a.md"],
                    "items": [
                        {
                            "file": "rule-a.md",
                            "created_at": "2026-11-20",
                            "author": "antigravity",
                            "action": "升格到规则",
                            "reason": "已稳定 </script><script>alert(1)</script>",
                            "target": "~/.agents/rules/AGENTS.md",
                            "proposed_text": "新增规则正文",
                        },
                        {
                            "file": "stale-b.md",
                            "created_at": "2026-10-10",
                            "author": "codex",
                            "action": "删除",
                            "reason": "代码现状已覆盖",
                        },
                    ],
                }
            ],
        }
        doc = R.render_decision_html(payload)
        self.assertIn("共用记忆升格清单 · 交互决策页", doc)
        self.assertIn("复制决策指令给 Agent", doc)
        self.assertIn("rule-a.md", doc)
        self.assertIn("keep-a.md", doc)
        self.assertIn("buildPromptText", doc)
        # 确认 </script> 已转义，不会打断内联脚本块
        self.assertNotIn("</script><script>alert(1)", doc)
        self.assertIn("<\\/script>", doc)

    def test_cli_generates_file_from_json_and_demo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_json = tmp_dir / "in.json"
            in_json.write_text(json.dumps(R.demo_payload(), ensure_ascii=False), encoding="utf-8")
            out_html = tmp_dir / "out.html"
            rc = R.main(["--input", str(in_json), "--out", str(out_html)])
            self.assertEqual(rc, 0)
            self.assertTrue(out_html.exists())
            content = out_html.read_text(encoding="utf-8")
            self.assertIn("html-doc-svg-no-duplicate-charts.md", content)

            demo_out = tmp_dir / "demo.html"
            self.assertEqual(R.main(["--demo", "--out", str(demo_out)]), 0)
            self.assertTrue(demo_out.exists())


if __name__ == "__main__":
    unittest.main()
