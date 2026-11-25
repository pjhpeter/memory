---
name: memory-promotion
description: 给共用记忆库 ~/.agents/memory/ 下每个项目出一份「升格清单」请用户拍板：逐条建议保留、改写、删除、升格到规则或升格到 skill，用户答复后只执行同意的条目。每周定时任务、用户说「出升格清单」「记忆升格」时使用。不做日常整理（那是 memory-dream）。
---

给每个项目的共用记忆出一份「升格清单」，请用户拍板。分两段：先只读出清单，用户答复后才动手。

**只读段的边界**：用户答复前不改记忆、规则、skill 中的任何文件，不建副本，不写锁文件。

## 一、准备

1. 读 `~/.agents/rules/topics/11-memory.md`（重点「记什么、不记什么」「整理」两节）和 `~/.agents/skills/memory-dream/SKILL.md` 第 5 步的判定口径。
2. 运行 `git -C ~/.agents/memory pull --rebase`。某个项目目录下有 `.dream.lock` 时跳过该项目，在结果里说明。
3. 项目 = `~/.agents/memory/` 下含 `MEMORY.md` 的目录。逐个项目读 `MEMORY.md` 和每一个条目文件。条目的首次记录日期用 `git -C ~/.agents/memory log --diff-filter=A --format=%ad --date=short -- <文件>` 取；作者取 frontmatter 的 `created_by`，没有就写「未知」。

## 二、逐条给一个建议

- **保留**：仍然成立，且看代码、git、issue 得不到。
- **改写**：有过期或写错的内容，或夹着进度流水账；写明要改成什么。提到具体文件、命令、分支、issue 状态的，用一次低成本查询（`ls`、`rg`、`git log -1`、`glab issue view`）核对，查不了的标「未核对」。
- **删除**：看代码、git、issue 就能知道的现状和进度；已被推翻；全局规则、仓库 `AGENTS.md` 或某个 skill 已经写明同一件事（指出是哪个文件哪一节）。
- **升格到规则**：已经稳定、所有任务都要遵守。写明目标文件和小节（全局放 `~/.agents/rules/`，只和某个仓库有关放该仓库 `AGENTS.md`），并给出拟写入的原文。
- **升格到 skill**：已经是某类任务每次都要走的固定流程。写明目标 skill 和拟写入的原文。

## 三、输出清单（中文、大白话、简短）

- 每个项目一小节，开头一行写条目总数和各类建议的数量。
- 「保留」的只列文件名，不展开。
- 其余每类一张表：条目文件、首次记录日期、作者、建议、一句理由；升格的再加目标位置和拟写入原文。
- **同时生成交互式 HTML 决策页**：把全部待处理条目整理为 JSON（结构含 `projects[].{name, total, keep_files, items:[{file, created_at, author, action, reason, target, proposed_text}]}`），通过标准输入管道或临时文件调用本 skill 附带脚本：
  `python3 ~/.agents/skills/memory-promotion/scripts/render_decision_html.py --input - --out ~/.agents/memory/.promotion-decision.html`
  在会话末尾附上完整路径与可复制命令 `open ~/.agents/memory/.promotion-decision.html`，说明「可在网页里点选改动作/写备注，点底部「复制决策指令给 Agent」直接粘回会话」。
- 结尾问用户：哪些照办、哪些不动、哪些要调整，可以回复「全部照办」、按条目文件名指定，或直接粘贴交互页复制出的决策指令。

没有任何需要处理的条目时，只回复一句「本周记忆无需处理」，不生成 HTML 页。

## 四、用户答复后执行（只动用户同意的条目）

1. **升格到规则**：按 `~/.agents/rules/topics/10-rule-editing.md` 写入，运行 `sh ~/.agents/rules/check.sh` 看到「全部通过」。写进仓库 `AGENTS.md` 的，按该仓库的 Git 规则提交，不直接推 main，除非用户明确要求。
2. **升格到 skill**：直接编辑对应 `SKILL.md`。源文件在 Git 仓库里的（如记忆库 `skills/`、`~/.hwf/skills/`），改源文件并按该仓库规则提交。
3. 写入成功后，再删掉对应记忆条目和 `MEMORY.md` 里那一行。
4. **改写、删除**：按 `11-memory.md` 的「格式」「Git 同步」处理：`updated_by` 写自己的 Agent 名，删除用 `git rm`，只 add 自己改的文件，提交信息 `memory(<项目>): 升格清单处理`，然后 `pull --rebase` 并 `push`。`memory-context.py` 认这条提交信息来判断上次整理时间，不要改写法。
5. 最后汇报实际改了哪些文件和提交 SHA。
