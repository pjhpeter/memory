# memory：所有编码 Agent 共用的长期记忆库

**遇到的问题**：Claude Code、Codex、omp、Factory Droid 等 Agent 每开一个新会话就把之前的事全忘了。用户纠正过的做法、踩过的坑、拍板过的决定，换个会话或换个 Agent 又要再说一遍，就像每天来一个新实习生。

**怎么解决**：把这些经验按项目写成一条条小笔记，放在这个仓库里。每次 Agent 启动时，自动把对应项目的笔记目录塞给它；回合结束时，再检查有没有该记下却漏记的事。

**为什么这样做**：所有 Agent 读写同一份笔记，用户只需要纠正一次；用 Git 管理，多台电脑同步、改错了也能找回。

本机位置是 `~/.agents/memory/`，就是本仓库的克隆。

## 里面有什么

| 位置 | 作用 |
| --- | --- |
| `<项目>/MEMORY.md` | 该项目的笔记目录：每行一条，指向一个笔记文件，带一句话说明。只放目录，不放正文 |
| `<项目>/<名字>.md` | 一条笔记：一件事一个文件 |
| `memory-context.py` | 启动时运行：按当前所在目录找到项目，输出要注入给 Agent 的笔记目录；到了该整理的时候顺带提醒 |
| `memory-write-check.py` | 回合结束时运行：用户刚说的话像纠正、偏好或决定，而记忆库没有新改动，就拦一次要求补记 |
| `sync-github.sh` | 把框架文件（不含项目记忆）同步到 GitHub，见文末 |

现有项目：

| 目录 | 对应的代码 |
| --- | --- |
| `web-v1/` | `~/code/web-v1` |
| `drawing-board/` | `~/code/web-v1/backend/drawing-board` |
| `team-up/` | `~/.hwf`（Herdr 交付流程、飞书桥、秘书、收件箱、主动接活） |

`memory-context.py` 从当前目录的最深一层往上找同名的项目目录，所以子项目优先于父项目；目录名和项目名不一样的（如 `~/.hwf` → `team-up`）写在脚本里的 `PATH_ALIASES`。

## 一条笔记长什么样

```markdown
---
name: run-commands-yourself
description: 本机能执行的命令 Agent 自己跑，不写成让用户动手的步骤
metadata:
  type: feedback        # user / feedback / project / reference
  created_by: factory   # 谁建的，以后不改
  updated_by: factory   # 最后谁改的，每次改都换成自己
---

事实写在这里，日期一律写绝对日期。

**Why:** 为什么要记（通常是用户的原话或踩坑经过）。
**How to apply:** 以后遇到什么情况、该怎么做。
```

写完在同目录的 `MEMORY.md` 加一行：`- [标题](文件.md) — 一句话说明`。

**记什么**：用户纠正过的做法和偏好、反复试错才查清的根因、为什么选这个方案、代码里看不出来的外部事实。
**不记什么**：看代码、`git log`、issue 就能知道的现状和进度；全局规则或 skill 已经写明的事。

## 怎么接到各个 Agent

| Agent | 启动时注入 | 回合结束检查 |
| --- | --- | --- |
| Factory Droid | `~/.factory/settings.json` 的 SessionStart hook：`memory-context.py factory-session-start` | Stop hook：`memory-write-check.py factory-stop` |
| Codex | `~/.codex/hooks.json` 的 SessionStart hook：`memory-context.py codex-session-start`（新 hook 要在 Codex 里用 `/hooks` 信任后才生效） | Stop hook：`memory-write-check.py codex-stop` |
| omp | 扩展 `~/.omp/agent/extensions/shared-memory-context.ts` 调 `memory-context.py --cwd <目录>` | 同一扩展的 session_stop 调 `memory-write-check.py omp` |
| Claude Code | 把 `~/.claude/projects/<项目>/memory` 做成指向本仓库项目目录的软链接 | — |

找不到对应项目时脚本什么都不输出、退出码 0，脚本出任何错都放行，不会卡住 Agent 启动。改了脚本或 hook 要新开一个会话实测。

## 装到一台新电脑

```sh
git clone git@git.bootingai.net:ai-hub/skills/workflow/memory.git ~/.agents/memory
```

再按上表给要用的 Agent 配好 hook 或软链接。

## 日常怎么用

- **写完就提交**：新建、修改、删除笔记后，同一轮里提交并推送，只 add 自己改的文件：
  ```sh
  cd ~/.agents/memory && git add <改动的文件> && git commit -m "memory(<项目>): <一句话说明>" && git pull --rebase && git push
  ```
- **多人同时写**：一条笔记一个文件，不同 Agent 写不同文件不冲突。改 `MEMORY.md` 只追加或改自己那一行；`pull --rebase` 冲突时两边的目录行都保留。
- **用之前先核对**：笔记里提到的文件、命令、分支、issue 状态可能已过期，用前先查一下，不一致就当场改掉那条笔记。
- **新项目**：建 `<项目名>/MEMORY.md`，需要时在 `PATH_ALIASES` 里加目录映射。
- **定期整理**：距上次整理超过 14 天、或之后新增了 15 条以上，启动时会提醒。用共用 skill `memory-dream` 合并重复、删掉过时的、把已经稳定的经验升格进规则或 skill，并把 `MEMORY.md` 控制在 200 行以内。整理时持有 `<项目>/.dream.lock`，看到别人的锁就别动这个项目。

## GitHub 镜像只放框架

https://github.com/pjhpeter/memory 只放框架：本 README、`.gitignore`、两个 hook 脚本和同步脚本 `sync-github.sh`，**不放任何项目记忆，也不带本仓库的提交历史**（项目记忆含公司内部信息，只留在 GitLab）。

改了框架文件并推到 GitLab 后，运行一次：

```sh
sh ~/.agents/memory/sync-github.sh
```

脚本把白名单文件复制到本机镜像目录 `~/.agents/memory-github`（独立的 Git 仓库），有变化就提交并推到 GitHub；镜像里出现 `MEMORY.md` 时拒绝推送。新增框架文件时，要同时加进脚本里的 `FILES`。

完整规则在本机 `~/.agents/rules/topics/11-memory.md`。
