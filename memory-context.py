#!/usr/bin/env python3
"""按当前工作目录找到对应项目的共用记忆库，输出要注入给 Agent 的上下文。

用法：
  memory-context.py --cwd <目录>              输出纯文本（omp 扩展用）
  memory-context.py --link-claude <仓库目录>  为已建记忆的项目补齐 Claude Code 软链接
  memory-context.py codex-session-start       从 stdin 读 Codex / Factory SessionStart hook JSON，输出 hookSpecificOutput
  memory-context.py factory-session-start     同上（两者格式一致）
  memory-context.py antigravity-session-start 从 stdin 读 Antigravity SessionStart hook JSON，输出 injectSteps
找不到对应项目时不输出任何内容（Antigravity 输出 {}），退出码 0，绝不阻塞 Agent 启动。
"""
import json
import os
import re
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
# 与记忆库内部结构冲突的保留目录名，自动识别时绝不占用
RESERVED_NAMES = frozenset({"skills", ".git"})
# 不当作自动记忆项目的系统/框架/临时目录前缀
EXCLUDED_ROOTS = tuple(
    os.path.realpath(path)
    for path in (
        MEMORY_ROOT,
        os.path.expanduser("~/.agents"),
        "/tmp",
        "/private/tmp",
        "/var",
        "/private/var",
    )
)


def _is_excluded_path(path):
    real = os.path.realpath(path)
    return any(real == root or real.startswith(root + os.sep) for root in EXCLUDED_ROOTS)


def _git_main_repo_root(cwd):
    """通过 git-common-dir 定位主仓库根目录（worktree 自动归到主仓库，避免碎片化建库）。"""
    if not cwd or not os.path.isdir(cwd) or _is_excluded_path(cwd):
        return None
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
    except Exception:
        return None
    if not out:
        return None
    common_dir = os.path.realpath(out if os.path.isabs(out) else os.path.join(cwd, out))
    repo_root = os.path.dirname(common_dir) if os.path.basename(common_dir) == ".git" else common_dir
    if _is_excluded_path(repo_root):
        return None
    return repo_root


def existing_projects():
    return {
        name
        for name in os.listdir(MEMORY_ROOT)
        if os.path.isfile(os.path.join(MEMORY_ROOT, name, "MEMORY.md"))
    }


def resolve_project(cwd):
    """先匹配已建库项目（含子项目与别名），未命中时按所在本地 Git 主仓库名自动识别。"""
    if not cwd:
        return None
    projects = existing_projects()
    real_cwd = os.path.realpath(cwd)
    # 1. 从最深的路径段往上找，子项目（如 web-v1/backend/drawing-board）优先于父项目。
    for segment in reversed(real_cwd.split(os.sep)):
        segment = PATH_ALIASES.get(segment, segment)
        if segment in projects:
            return segment
    # 2. 任意本地 Git 仓库自动按主仓库目录名识别（排除系统/框架/临时目录与保留名）。
    repo_root = _git_main_repo_root(real_cwd)
    if not repo_root:
        return None
    name = PATH_ALIASES.get(os.path.basename(repo_root), os.path.basename(repo_root))
    if not name or name.startswith(".") or name in RESERVED_NAMES:
        return None
    return name


def has_memory_index(project):
    return bool(project) and os.path.isfile(os.path.join(MEMORY_ROOT, project, "MEMORY.md"))


def ensure_claude_link(repo_path, project=None):
    """按 Claude Code 项目路径编码规则补齐 ~/.claude/projects/<encoded>/memory 软链接。"""
    real_path = os.path.realpath(repo_path)
    resolved = project or resolve_project(real_path)
    if not resolved:
        raise ValueError(f"无法从路径识别项目：{repo_path}")
    target = os.path.join(MEMORY_ROOT, resolved)
    if not os.path.isdir(target):
        raise ValueError(f"记忆目录尚不存在：{target}")
    # 若在仓库子目录调用且不是独立子项目目录（如 drawing-board），自动归到主仓库根路径再编码。
    git_root = _git_main_repo_root(real_path)
    link_base = real_path
    if git_root and PATH_ALIASES.get(os.path.basename(real_path), os.path.basename(real_path)) != resolved:
        link_base = git_root
    encoded = re.sub(r"[/.]", "-", link_base)
    dest = os.path.join(os.path.expanduser("~/.claude/projects"), encoded, "memory")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.islink(dest):
        if os.path.realpath(dest) == os.path.realpath(target):
            return f"已是正确链接：{dest} → {target}"
        os.unlink(dest)
    elif os.path.exists(dest):
        return f"跳过 {dest}：已有同名真实目录，请人工确认合并后再建软链接"
    os.symlink(target, dest)
    return f"已链接：{dest} → {target}"


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
    shown_dir = project_dir.replace(os.path.expanduser("~"), "~", 1)
    if not has_memory_index(project):
        # 惰性建库：新 Git 仓库不预先落盘空目录，只注入自动建库指引与漏记提醒。
        repo_root = _git_main_repo_root(os.path.realpath(cwd)) or os.path.realpath(cwd)
        return "\n".join(
            [
                "# 共用记忆库（启动时自动识别，按需自动建库）",
                f"当前项目：{project}（尚未建记忆目录）；目标记忆目录：{shown_dir}/",
                "本项目目前还没有记忆条目，不要预先建空目录。",
                "以下情况要当场自动新建记忆目录与 MEMORY.md、写入条目并提交推送（格式见 ~/.agents/rules/topics/11-memory.md）："
                "用户纠正了你的做法、说了偏好或习惯、拍板了方案或决策、你踩坑后查清了根因、发现了代码里看不出来但以后还会用到的事实。",
                f"首次建好目录后，顺手执行 `python3 ~/.agents/memory/memory-context.py --link-claude '{repo_root}'` 补齐 Claude Code 软链接。",
                "不用记：只对本次任务有效的一次性指令；看代码、git、issue 就能知道的现状和进度；规则或 skill 已经写明的事。"
                "回合结束时有检查，漏记会被拦下一次。",
            ]
        )

    with open(os.path.join(project_dir, "MEMORY.md"), encoding="utf-8") as handle:
        lines = handle.read().splitlines()[:MAX_INDEX_LINES]
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


def resolve_antigravity_cwd(payload):
    """Antigravity hook 进程的当前目录是 hooks.json 所在目录，优先从 cwd / workspacePaths 找项目。"""
    candidates = [payload.get("cwd"), *(payload.get("workspacePaths") or [])]
    for path in candidates:
        if path and resolve_project(path):
            return path
    return next((path for path in candidates if path), os.getcwd())


def main(argv):
    is_antigravity = argv[:1] == ["antigravity-session-start"]
    wrote_json = False
    try:
        if "--link-claude" in argv:
            idx = argv.index("--link-claude")
            target_repo = argv[idx + 1] if idx + 1 < len(argv) else os.getcwd()
            sys.stdout.write(ensure_claude_link(target_repo) + "\n")
            return 0
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
        if is_antigravity:
            payload = json.load(sys.stdin)
            context = build_context(resolve_antigravity_cwd(payload))
            out = {"injectSteps": [{"systemMessage": {"systemMessage": context}}]} if context else {}
            json.dump(out, sys.stdout, ensure_ascii=False)
            wrote_json = True
            return 0
        cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
        sys.stdout.write(build_context(cwd))
    except Exception as error:  # 记忆注入失败不能影响 Agent 启动
        if is_antigravity and not wrote_json:
            sys.stdout.write("{}")
        sys.stderr.write(f"memory-context: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
