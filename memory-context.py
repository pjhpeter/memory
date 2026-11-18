#!/usr/bin/env python3
"""按当前工作目录找到对应项目的共用记忆库，输出要注入给 Agent 的上下文。

用法：
  memory-context.py --cwd <目录>          输出纯文本（omp 扩展用）
  memory-context.py codex-session-start   从 stdin 读 Codex / Factory SessionStart hook JSON，输出 hookSpecificOutput
  memory-context.py factory-session-start 同上（两者格式一致）
找不到对应项目时不输出任何内容，退出码 0，绝不阻塞 Agent 启动。
"""
import json
import os
import subprocess
import sys
import time

MEMORY_ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_INDEX_LINES = 200
# 整理到期条件：距上次整理超过这么多天，或之后新增了这么多条目（见 11-memory.md「整理」）。
DREAM_MAX_DAYS = 14
DREAM_MAX_NEW_ENTRIES = 15
# 本地目录名和记忆项目名不同的仓库：目录段 → 项目名
PATH_ALIASES = {".hwf": "team-up"}


def resolve_project(cwd):
    projects = {
        name
        for name in os.listdir(MEMORY_ROOT)
        if os.path.isfile(os.path.join(MEMORY_ROOT, name, "MEMORY.md"))
    }
    # 从最深的路径段往上找，子项目（如 web-v1/backend/drawing-board）优先于父项目。
    for segment in reversed(os.path.realpath(cwd).split(os.sep)):
        segment = PATH_ALIASES.get(segment, segment)
        if segment in projects:
            return segment
    return None


def git_lines(*args):
    out = subprocess.run(
        ["git", "-C", MEMORY_ROOT, *args], capture_output=True, text=True, timeout=3, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


# 整理和每周升格都会做合并、删除，两种提交都算一次整理。
DREAM_SUBJECTS = ("dream 整理", "升格清单处理")


def last_dream_commit(project):
    """返回最近一次整理提交的 (SHA, 时间戳)，没有就返回 None。

    认两种：提交信息一字不差为「memory(<项目>): <整理类型>」的（含没有改动时的空提交），
    以及提交信息含整理类型、且改到了该项目目录的（每周升格一次提交会顺带处理多个项目）。
    """
    found = []
    for subject in DREAM_SUBJECTS:
        for grep, paths in ((f"memory({project}): {subject}", []), (subject, ["--", project])):
            found += git_lines("log", "-1", "--format=%ct %H", "--fixed-strings", f"--grep={grep}", *paths)
    if not found:
        return None
    stamp, sha = max(found, key=lambda line: int(line.split()[0])).split()
    return sha, stamp


def dream_reminder(project):
    """上次整理按 git 历史里的整理提交算；从没整理过就从该项目第一次提交算。"""
    try:
        last = last_dream_commit(project)
        if last:
            base, stamp = last
            revision_range = [f"{base}..HEAD"]
        else:
            stamp = git_lines("log", "--reverse", "--format=%ct", "--", project)[0]
            revision_range = []
        added = git_lines("log", *revision_range, "--diff-filter=A", "--name-only", "--format=", "--", project)
        # 只数现在还在的条目：整理后被删掉或合并掉的不算新增。
        existing = set(git_lines("ls-files", "--", project))
        new_entries = len({name for name in added if name in existing and name.endswith(".md") and not name.endswith("/MEMORY.md")})
        days = int((time.time() - int(stamp)) // 86400)
    except Exception:  # 没有 git、不是仓库、超时：不提醒
        return ""
    if days <= DREAM_MAX_DAYS and new_entries < DREAM_MAX_NEW_ENTRIES:
        return ""
    since = f"距上次整理 {days} 天" if last else f"从未整理过，建库已 {days} 天"
    return (
        f"记忆库该整理了（{since}，期间新增 {new_entries} 条）：本次任务收尾时告诉用户一句"
        "「记忆库该整理了，要整理就说『整理记忆』」，不要自行开始整理。"
    )


def build_context(cwd):
    project = resolve_project(cwd)
    if not project:
        return ""
    project_dir = os.path.join(MEMORY_ROOT, project)
    with open(os.path.join(project_dir, "MEMORY.md"), encoding="utf-8") as handle:
        lines = handle.read().splitlines()[:MAX_INDEX_LINES]
    shown_dir = project_dir.replace(os.path.expanduser("~"), "~", 1)
    return "\n".join(
        [
            "# 共用记忆库（启动时自动注入）",
            f"当前项目：{project}；记忆目录：{shown_dir}/",
            "下面是记忆索引，每行指向目录里的一个条目文件，记录了用户偏好、纠正过的做法、项目决策和已踩过的坑。"
            "开始任何任务（写代码、排查、评审、写 issue、回答问题）前，先对照索引找出和这次任务相关的条目，"
            "打开读完再动手；条目和你的默认做法冲突时，以条目为准。问到用户本人或过往约定时，同样先查索引，不要直接说不知道。",
            "条目里提到具体文件、命令、分支、issue 或 MR 状态时，用之前先花一次查询核对（ls、rg、git log、glab）；"
            "和现状不一致就以核对结果为准，并当场改掉这条记忆。用户的偏好、纠正和决策不用核对，照做。",
            "以下情况要当场写一条记忆（格式见 ~/.agents/rules/topics/11-memory.md，写完补索引并提交推送）："
            "用户纠正了你的做法、说了偏好或习惯、拍板了方案或决策、你踩坑后查清了根因、发现了代码里看不出来但以后还会用到的事实。"
            "不用记：只对本次任务有效的一次性指令；看代码、git、issue 就能知道的现状和进度；规则或 skill 已经写明的事。"
            "回合结束时有检查，漏记会被拦下一次。",
            *filter(None, [dream_reminder(project)]),
            "",
            *lines,
        ]
    )


def main(argv):
    try:
        if argv[:1] in (["codex-session-start"], ["factory-session-start"]):
            payload = json.load(sys.stdin)
            context = build_context(payload.get("cwd") or os.getcwd())
            if context:
                json.dump(
                    {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                    sys.stdout,
                    ensure_ascii=False,
                )
            return 0
        cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
        sys.stdout.write(build_context(cwd))
    except Exception as error:  # 记忆注入失败不能影响 Agent 启动
        sys.stderr.write(f"memory-context: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
