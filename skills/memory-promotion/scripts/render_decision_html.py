#!/usr/bin/env python3
"""将 memory-promotion 升格清单 JSON 渲染成可交互单文件 HTML 决策页。

用法：
    python3 render_decision_html.py --input items.json [--out ~/.agents/memory/.promotion-decision.html] [--open]
    python3 render_decision_html.py --demo [--out ~/.agents/memory/.promotion-decision.html] [--open]

为什么有它：
    记忆升格清单往往一次含多条「改写 / 删除 / 升格到规则 / 升格到 skill」待拍板项。
    做成浏览器直接打开的交互决策页，用户逐条点选并填简短备注后，一键复制结构化中文指令粘回会话即可执行，
    免去对着长表格手工敲文件名和指令的摩擦。
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

DEFAULT_OUT = Path.home() / ".agents" / "memory" / ".promotion-decision.html"
ACTION_CHOICES = ("保留", "改写", "删除", "升格到规则", "升格到 skill")


def _safe_json_for_script(data: Any) -> str:
    """将对象编码为可安全内嵌在 <script> 中的 JSON，避免 </script> 注入。"""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """规整输入数据结构，补齐默认值并计算稳定的页面状态键。"""
    generated_at = str(payload.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M"))
    projects_in = payload.get("projects") or []
    projects: list[dict[str, Any]] = []
    item_seq = 0
    for proj in projects_in:
        if not isinstance(proj, Mapping):
            continue
        name = str(proj.get("name") or "").strip()
        if not name:
            continue
        keep_files = [str(f).strip() for f in (proj.get("keep_files") or []) if str(f).strip()]
        items_out: list[dict[str, Any]] = []
        for raw in proj.get("items") or []:
            if not isinstance(raw, Mapping):
                continue
            file_name = str(raw.get("file") or "").strip()
            if not file_name:
                continue
            item_seq += 1
            suggested = str(raw.get("action") or "保留").strip()
            if suggested not in ACTION_CHOICES:
                suggested = "改写"
            items_out.append({
                "id": f"m-{item_seq}",
                "project": name,
                "file": file_name,
                "created_at": str(raw.get("created_at") or "未知"),
                "author": str(raw.get("author") or "未知"),
                "suggested": suggested,
                "reason": str(raw.get("reason") or ""),
                "target": str(raw.get("target") or ""),
                "proposed_text": str(raw.get("proposed_text") or ""),
            })
        total = int(proj.get("total") or (len(keep_files) + len(items_out)))
        projects.append({
            "name": name,
            "total": total,
            "keep_files": keep_files,
            "items": items_out,
        })
    fingerprint = hashlib.sha1(
        json.dumps(projects, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return {
        "generated_at": generated_at,
        "storage_key": f"memory-promotion-v1-{fingerprint}",
        "projects": projects,
    }


def render_decision_html(payload: Mapping[str, Any]) -> str:
    """渲染单文件暗/亮自适应交互式记忆升格决策页。"""
    data = normalize_payload(payload)
    e = html.escape
    projects = data["projects"]
    all_items = [it for p in projects for it in p["items"]]

    summary_rows = "".join(
        f"<tr>"
        f"<td><b>{e(p['name'])}</b></td>"
        f"<td>{p['total']}</td>"
        f"<td>{len(p['keep_files'])}</td>"
        f"<td>{len(p['items'])}</td>"
        f"<td>{sum(1 for it in p['items'] if it['suggested'].startswith('升格'))}</td>"
        f"<td>{sum(1 for it in p['items'] if it['suggested'] == '改写')}</td>"
        f"<td>{sum(1 for it in p['items'] if it['suggested'] == '删除')}</td>"
        f"</tr>"
        for p in projects
    ) or "<tr><td colspan='7' class='empty'>本周记忆无需处理。</td></tr>"

    sections: list[str] = []
    for p in projects:
        keep_html = ""
        if p["keep_files"]:
            chips = " ".join(f"<code>{e(f)}</code>" for f in p["keep_files"])
            keep_html = (
                f"<details class='keep-box'><summary>建议保留不动（{len(p['keep_files'])} 条，点击展开文件名）</summary>"
                f"<div class='chips'>{chips}</div></details>"
            )

        cards: list[str] = []
        for it in p["items"]:
            options_html = "".join(
                f"<button type='button' class='opt-btn{' active' if act == it['suggested'] else ''}' "
                f"data-id='{e(it['id'])}' data-action='{e(act)}'>"
                f"{e(act)}{'（建议）' if act == it['suggested'] else ''}</button>"
                for act in ACTION_CHOICES
            )
            extra_html = ""
            if it["target"] or it["proposed_text"]:
                target_line = f"<div class='meta-line'><b>目标位置：</b><code>{e(it['target'])}</code></div>" if it["target"] else ""
                prop_block = f"<pre class='proposed'>{e(it['proposed_text'])}</pre>" if it["proposed_text"] else ""
                extra_html = (
                    f"<details class='detail-box'><summary>查看拟写入目标与原文</summary>"
                    f"{target_line}{prop_block}</details>"
                )
            cards.append(
                f"<article class='item-card' data-id='{e(it['id'])}' data-project='{e(p['name'])}' "
                f"data-suggested='{e(it['suggested'])}'>"
                f"<div class='item-head'>"
                f"<div><code class='fname'>{e(it['file'])}</code>"
                f"<span class='meta'>首次记录：{e(it['created_at'])} · 作者：{e(it['author'])}</span></div>"
                f"<span class='badge' data-badge='{e(it['id'])}'>按建议：{e(it['suggested'])}</span>"
                f"</div>"
                f"<p class='reason'>{e(it['reason'])}</p>"
                f"{extra_html}"
                f"<div class='controls'>"
                f"<div class='btn-group' role='group' aria-label='选择处理动作'>{options_html}</div>"
                f"<input type='text' class='note-input' data-note='{e(it['id'])}' "
                f"placeholder='可选备注：要改哪一句、换目标文件或补充说明…'>"
                f"</div>"
                f"</article>"
            )

        body_html = "".join(cards) or "<p class='empty'>该项目没有待拍板的变动条目。</p>"
        sections.append(
            f"<section class='proj-sec' data-proj-sec='{e(p['name'])}'>"
            f"<div class='sec-head'><h2>项目：{e(p['name'])}（待拍板 {len(p['items'])} 条）</h2>"
            f"<div class='sec-tools'>"
            f"<button type='button' class='mini-btn' data-proj-follow='{e(p['name'])}'>本项目全部照办</button>"
            f"<button type='button' class='mini-btn' data-proj-keep='{e(p['name'])}'>本项目全部先保留</button>"
            f"</div></div>"
            f"{keep_html}{body_html}</section>"
        )

    return HTML_TEMPLATE.format(
        generated_at=e(data["generated_at"]),
        pending_count=len(all_items),
        summary_rows=summary_rows,
        sections="".join(sections) or "<p class='empty'>本周记忆无需处理。</p>",
        bootstrap_json=_safe_json_for_script(data),
    )


def demo_payload() -> dict[str, Any]:
    """构造示例数据，方便首次体验与自测。"""
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "projects": [
            {
                "name": "web-v1",
                "total": 12,
                "keep_files": ["user-profile-jiahui.md", "canvas-v2-wasm-hardening.md"],
                "items": [
                    {
                        "file": "html-doc-svg-no-duplicate-charts.md",
                        "created_at": "2026-11-21",
                        "author": "factory",
                        "action": "升格到规则",
                        "reason": "已成为所有 HTML 报告的稳定规范，写入全局 HTML 审阅专题后可删重复记忆。",
                        "target": "~/.agents/rules/topics/12-html-review-pages.md「四、图表与主题铁线」",
                        "proposed_text": "表格已列出的数字不再另画条形图/KPI卡；结构 SVG 不画底色，仅用 currentColor 或主题 CSS 变量。",
                    },
                    {
                        "file": "old-branch-temp-note.md",
                        "created_at": "2026-10-18",
                        "author": "codex",
                        "action": "删除",
                        "reason": "对应分支已合入 main，看 git log 即可查清现状。",
                    },
                ],
            }
        ],
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>共用记忆升格清单 · 交互决策页</title>
<style>
:root {{
  --bg: #f7f8fa;
  --card: #ffffff;
  --ink: #1f2328;
  --muted: #59636e;
  --line: #d0d7de;
  --accent: #0969da;
  --accent-bg: #ddf4ff;
  --ok: #1a7f37;
  --ok-bg: #dafbe1;
  --warn: #9a6700;
  --warn-bg: #fff8c5;
  --danger: #cf222e;
  --danger-bg: #ffebe9;
  --tag-bg: #eef1f4;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --ink: #e6edf3;
    --muted: #8b949e;
    --line: #30363d;
    --accent: #58a6ff;
    --accent-bg: #13233a;
    --ok: #3fb950;
    --ok-bg: #132d1c;
    --warn: #d29922;
    --warn-bg: #32240c;
    --danger: #f85149;
    --danger-bg: #3b1719;
    --tag-bg: #21262d;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.6 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 24px 16px 130px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
h2 {{ font-size: 17px; margin: 0; }}
.sub {{ color: var(--muted); margin: 0 0 16px; }}
.plain {{ background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 10px; padding: 12px 14px; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; margin-bottom: 20px; }}
th, td {{ text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line); }}
th {{ font-size: 13px; color: var(--muted); background: var(--tag-bg); }}
tr:last-child td {{ border-bottom: none; }}
.proj-sec {{ margin-top: 22px; }}
.sec-head {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }}
.sec-tools {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.keep-box, .detail-box {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin-bottom: 10px; }}
summary {{ cursor: pointer; font-weight: 600; color: var(--muted); }}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
.item-card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; transition: border-color .15s; }}
.item-card.changed {{ border-color: var(--warn); }}
.item-head {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; }}
.fname {{ font-weight: 700; font-size: 13px; }}
.meta {{ color: var(--muted); font-size: 12px; margin-left: 8px; }}
.badge {{ display: inline-block; padding: 2px 9px; border-radius: 99px; font-size: 12px; font-weight: 600; background: var(--accent-bg); color: var(--accent); }}
.badge.changed {{ background: var(--warn-bg); color: var(--warn); }}
.badge.keep {{ background: var(--tag-bg); color: var(--muted); }}
.reason {{ margin: 8px 0; }}
.meta-line {{ margin: 6px 0; font-size: 13px; }}
.proposed {{ margin: 8px 0 0; padding: 10px 12px; background: var(--tag-bg); border-radius: 6px; white-space: pre-wrap; word-break: break-word; font: 12.5px/1.5 ui-monospace, Menlo, monospace; }}
.controls {{ margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }}
.btn-group {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.opt-btn, .mini-btn, .primary-btn {{
  cursor: pointer; border: 1px solid var(--line); background: var(--card); color: var(--ink);
  border-radius: 8px; padding: 5px 10px; font-size: 13px; transition: all .12s;
}}
.opt-btn:hover, .mini-btn:hover {{ border-color: var(--accent); }}
.opt-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; }}
.note-input {{ width: 100%; border: 1px solid var(--line); background: var(--bg); color: var(--ink); border-radius: 8px; padding: 7px 10px; font-size: 13px; }}
code {{ font: 12px ui-monospace, Menlo, monospace; background: var(--tag-bg); padding: 1px 5px; border-radius: 4px; }}
.empty {{ color: var(--muted); text-align: center; padding: 16px; }}
.dock {{
  position: fixed; left: 0; right: 0; bottom: 0; background: var(--card); border-top: 1px solid var(--line);
  box-shadow: 0 -4px 18px rgba(0,0,0,.08); padding: 12px 16px; z-index: 50;
}}
.dock-inner {{ max-width: 1080px; margin: 0 auto; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; }}
.dock-stat {{ font-size: 13px; color: var(--muted); }}
.dock-stat b {{ color: var(--ink); }}
.dock-actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
.primary-btn {{ background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; padding: 7px 14px; }}
.primary-btn:hover {{ opacity: .92; }}
.toast {{ font-size: 12.5px; color: var(--ok); font-weight: 600; min-height: 18px; }}
.preview-wrap {{ max-width: 1080px; margin: 10px auto 0; display: none; }}
.preview-wrap.open {{ display: block; }}
.preview-area {{ width: 100%; min-height: 120px; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: var(--bg); color: var(--ink); font: 12.5px/1.5 ui-monospace, Menlo, monospace; }}
</style>
</head>
<body>
<main>
  <h1>共用记忆升格清单 · 交互决策页</h1>
  <p class="sub">生成于 {generated_at} · 待拍板 {pending_count} 条 · 点选完直接点右下角「复制决策指令」粘回会话即可</p>

  <div class="plain">
    <b>怎么用（30 秒拍完板）：</b>每条记忆已默认选中 Agent 建议动作；觉得没问题就不用动，想换动作直接点按钮或写一句备注。全部看一遍后点底部<b>「复制决策指令」</b>，直接粘回会话发给 Agent 执行。
  </div>

  <table>
    <thead>
      <tr>
        <th>项目</th>
        <th>总条目</th>
        <th>建议保留</th>
        <th>待拍板</th>
        <th>升格</th>
        <th>改写</th>
        <th>删除</th>
      </tr>
    </thead>
    <tbody>{summary_rows}</tbody>
  </table>

  {sections}
</main>

<div class="dock">
  <div class="dock-inner">
    <div class="dock-stat" id="dockStat">加载中…</div>
    <div class="dock-actions">
      <span class="toast" id="toast" role="status" aria-live="polite"></span>
      <button type="button" class="mini-btn" id="btnReset">恢复全部建议</button>
      <button type="button" class="mini-btn" id="btnTogglePreview">查看/手动复制</button>
      <button type="button" class="primary-btn" id="btnCopy">复制决策指令给 Agent</button>
    </div>
  </div>
  <div class="preview-wrap" id="previewWrap">
    <textarea class="preview-area" id="previewArea" readonly aria-label="生成的决策指令"></textarea>
  </div>
</div>

<script>
const DATA = {bootstrap_json};
const STORAGE_KEY = DATA.storage_key;
const ITEMS = [];
for (const p of DATA.projects) {{
  for (const it of p.items) ITEMS.push(it);
}}

function loadState() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {{}};
  }} catch (_e) {{
    return {{}};
  }}
}}

function saveState(st) {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(st)); }} catch (_e) {{}}
}}

const state = loadState();
for (const it of ITEMS) {{
  if (!state[it.id]) {{
    state[it.id] = {{ action: it.suggested, note: "" }};
  }}
}}

function buildPromptText() {{
  if (!ITEMS.length) return "本周记忆无需处理。";
  const allFollow = ITEMS.every(it => state[it.id].action === it.suggested && !(state[it.id].note || "").trim());
  if (allFollow) {{
    return "按本周记忆升格清单全部照办。";
  }}
  const lines = ["按以下决定处理本周共用记忆升格清单（其余未列项保持不变）："];
  for (const p of DATA.projects) {{
    if (!p.items.length) continue;
    lines.push("", `## 项目：${{p.name}}`);
    for (const it of p.items) {{
      const cur = state[it.id];
      const note = (cur.note || "").trim();
      const tag = cur.action === it.suggested ? "照办" : "改动作";
      const notePart = note ? `｜补充：${{note}}` : "";
      lines.push(`- ${{it.file}}：${{cur.action}}（${{tag}}，原建议：${{it.suggested}}）${{notePart}}`);
    }}
  }}
  return lines.join("\\n");
}}

function renderAll() {{
  let follow = 0, changed = 0, keep = 0;
  for (const it of ITEMS) {{
    const cur = state[it.id];
    const hasNote = Boolean((cur.note || "").trim());
    const isKeep = cur.action === "保留";
    const isChanged = cur.action !== it.suggested || hasNote;
    if (isKeep && cur.action !== it.suggested) keep++;
    else if (isChanged) changed++;
    else follow++;

    const card = document.querySelector(`.item-card[data-id="${{it.id}}"]`);
    if (card) card.classList.toggle("changed", isChanged);
    const badge = document.querySelector(`[data-badge="${{it.id}}"]`);
    if (badge) {{
      badge.classList.remove("changed", "keep");
      if (isKeep && cur.action !== it.suggested) {{
        badge.classList.add("keep");
        badge.textContent = "改回保留不动";
      }} else if (isChanged) {{
        badge.classList.add("changed");
        badge.textContent = `调整为：${{cur.action}}`;
      }} else {{
        badge.textContent = `按建议：${{cur.action}}`;
      }}
    }}
    document.querySelectorAll(`.opt-btn[data-id="${{it.id}}"]`).forEach(btn => {{
      btn.classList.toggle("active", btn.dataset.action === cur.action);
    }});
    const inp = document.querySelector(`.note-input[data-note="${{it.id}}"]`);
    if (inp && inp.value !== cur.note) inp.value = cur.note;
  }}
  const stat = document.getElementById("dockStat");
  stat.innerHTML = `待拍板 <b>${{ITEMS.length}}</b> 条：按建议照办 <b>${{follow}}</b> · 调整动作/备注 <b>${{changed}}</b> · 改回保留 <b>${{keep}}</b>`;
  document.getElementById("previewArea").value = buildPromptText();
}}

function showToast(msg) {{
  const el = document.getElementById("toast");
  el.textContent = msg;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {{ el.textContent = ""; }}, 3000);
}}

async function copyText(text) {{
  const area = document.getElementById("previewArea");
  area.value = text;
  if (navigator.clipboard && window.isSecureContext) {{
    try {{
      await navigator.clipboard.writeText(text);
      return true;
    }} catch (_e) {{}}
  }}
  const wrap = document.getElementById("previewWrap");
  wrap.classList.add("open");
  area.focus();
  area.select();
  try {{
    return document.execCommand("copy");
  }} catch (_e) {{
    return false;
  }}
}}

document.addEventListener("click", async (ev) => {{
  const opt = ev.target.closest(".opt-btn");
  if (opt) {{
    const id = opt.dataset.id;
    state[id].action = opt.dataset.action;
    saveState(state);
    renderAll();
    return;
  }}
  const followProj = ev.target.closest("[data-proj-follow]");
  if (followProj) {{
    const pname = followProj.dataset.projFollow;
    for (const it of ITEMS) {{
      if (it.project === pname) {{ state[it.id].action = it.suggested; state[it.id].note = ""; }}
    }}
    saveState(state);
    renderAll();
    return;
  }}
  const keepProj = ev.target.closest("[data-proj-keep]");
  if (keepProj) {{
    const pname = keepProj.dataset.projKeep;
    for (const it of ITEMS) {{
      if (it.project === pname) state[it.id].action = "保留";
    }}
    saveState(state);
    renderAll();
    return;
  }}
  if (ev.target.id === "btnReset") {{
    for (const it of ITEMS) state[it.id] = {{ action: it.suggested, note: "" }};
    saveState(state);
    renderAll();
    showToast("已恢复默认建议");
    return;
  }}
  if (ev.target.id === "btnTogglePreview") {{
    document.getElementById("previewWrap").classList.toggle("open");
    return;
  }}
  if (ev.target.id === "btnCopy") {{
    const ok = await copyText(buildPromptText());
    showToast(ok ? "已复制决策指令，直接粘回会话发送即可" : "已展开文本框，请按 Cmd+C 复制");
  }}
}});

document.addEventListener("input", (ev) => {{
  const inp = ev.target.closest(".note-input");
  if (!inp) return;
  state[inp.dataset.note].note = inp.value;
  saveState(state);
  renderAll();
}});

renderAll();
</script>
</body>
</html>
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="将记忆升格清单 JSON 生成单文件交互式 HTML 决策页")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="清单 JSON 文件路径（传 - 从标准输入读取）")
    src.add_argument("--demo", action="store_true", help="使用示例数据生成预览页")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"输出 HTML 路径，默认 {DEFAULT_OUT}")
    parser.add_argument("--open", action="store_true", help="生成后自动用系统默认浏览器打开")
    opts = parser.parse_args(argv)

    if opts.demo:
        payload = demo_payload()
    elif opts.input == "-":
        payload = json.loads(sys.stdin.read())
    else:
        payload = json.loads(Path(opts.input).read_text(encoding="utf-8"))

    out_path = Path(opts.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_decision_html(payload), encoding="utf-8")
    print(str(out_path))
    if opts.open:
        subprocess.run(["open", str(out_path)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
