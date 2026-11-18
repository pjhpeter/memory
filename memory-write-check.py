#!/usr/bin/env python3
"""回合结束前的记忆检查：本轮用户消息像是纠正、偏好或决策，而记忆库没有任何新改动时，返回拦截理由。

用法：
  memory-write-check.py omp --transcript <会话 jsonl> --cwd <目录>   需要拦截时输出理由文本
  memory-write-check.py codex-stop                                 从 stdin 读 Codex Stop hook JSON
  memory-write-check.py factory-stop                               从 stdin 读 Factory Droid Stop hook JSON
同一条用户消息只拦一次：omp 由扩展记录，Codex 靠 stop_hook_active。任何异常都放行。
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime

MEMORY_ROOT = os.path.dirname(os.path.abspath(__file__))
# 调度者派活的长指令里也常有「必须」「统一」，人工纠正一般较短，超过这个长度不检查。
MAX_MESSAGE_CHARS = 500
SIGNALS = re.compile(
    r"记住|记下|以后|下次|每次|一律|统一|永远|总是|不要再|别再|再也别|不对|错了|搞错|说过|"
    r"应该(是|用|先|改)|我(喜欢|希望|习惯|偏好|要求)|决定|定了|就这么|就按|拍板|踩坑|原来是|根因"
)
SKIP_MARK = "无需记忆"
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?(</system-reminder>|$)", re.S)


def load_resolver():
    spec = importlib.util.spec_from_file_location("memory_context", os.path.join(MEMORY_ROOT, "memory-context.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.resolve_project


def parse_time(value):
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def read_omp(path):
    """返回 (最后一条真实用户消息, 时间戳, 之后最后一条助手文本)。"""
    user, at, assistant = None, None, ""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") or {}
            if entry.get("type") != "message":
                continue
            if message.get("role") == "user" and message.get("attribution", "user") == "user":
                user, at, assistant = text_of(message.get("content")), entry.get("timestamp"), ""
            elif message.get("role") == "assistant":
                text = text_of(message.get("content"))
                if text.strip():
                    assistant = text
    return user, at, assistant


def read_codex(path):
    user, at = None, None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            payload = entry.get("payload") or {}
            item = payload.get("item") or {}
            if payload.get("type") == "item_completed" and item.get("type") == "UserMessage":
                user, at = text_of(item.get("content")), entry.get("timestamp")
    return user, at


def read_factory(path):
    """Factory 会话里 role=user 的还有 hook 记录、工具结果和 llm_only 的系统提醒，只认用户亲手发的文本。"""
    user, at, assistant = None, None, ""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") or {}
            if entry.get("type") != "message":
                continue
            if message.get("role") == "assistant":
                text = text_of(message.get("content"))
                if text.strip():
                    assistant = text
                continue
            if message.get("role") != "user" or message.get("hookEventName") or message.get("visibility") == "llm_only":
                continue
            text = SYSTEM_REMINDER.sub("", text_of(message.get("content"))).strip()
            if text:
                user, at, assistant = text, entry.get("timestamp"), ""
    return user, at, assistant


def memory_changed_since(timestamp):
    status = subprocess.run(
        ["git", "-C", MEMORY_ROOT, "status", "--porcelain"], capture_output=True, text=True, timeout=5
    ).stdout
    if any(line.strip().endswith(".md") for line in status.splitlines()):
        return True
    log = subprocess.run(
        ["git", "-C", MEMORY_ROOT, "log", "-20", "--format=%ct"], capture_output=True, text=True, timeout=5
    ).stdout
    return any(int(t) >= int(timestamp) for t in log.split())


def check(user, at, assistant, cwd):
    if not user or at is None or len(user) > MAX_MESSAGE_CHARS:
        return ""
    project = load_resolver()(cwd)
    if not project:
        return ""
    match = SIGNALS.search(user)
    if not match or SKIP_MARK in (assistant or ""):
        return ""
    if memory_changed_since(parse_time(at)):
        return ""
    start = max(0, match.start() - 30)
    snippet = user[start : match.end() + 30].replace("\n", " ")
    return (
        f"[记忆检查] 本轮用户的话里有像是纠正、偏好或决策的内容：「…{snippet}…」，但记忆库没有新改动。\n"
        f"如果其中有以后还用得上的经验，按 ~/.agents/rules/topics/11-memory.md 的格式写进 "
        f"~/.agents/memory/{project}/（先查有没有已有条目可以改），在 MEMORY.md 补索引，然后提交并推送。\n"
        f"如果只是本次任务的一次性指令、没有值得长期记的，回复里写一句「{SKIP_MARK}」就可以结束。"
    )


def main(argv):
    try:
        if argv[:1] == ["codex-stop"]:
            payload = json.load(sys.stdin)
            if payload.get("stop_hook_active") or not payload.get("transcript_path"):
                return 0
            user, at = read_codex(payload["transcript_path"])
            reason = check(user, at, payload.get("last_assistant_message") or "", payload.get("cwd") or os.getcwd())
            if reason:
                json.dump({"decision": "block", "reason": reason}, sys.stdout, ensure_ascii=False)
            return 0
        if argv[:1] == ["factory-stop"]:
            payload = json.load(sys.stdin)
            if payload.get("stop_hook_active") or not payload.get("transcript_path"):
                return 0
            user, at, assistant = read_factory(payload["transcript_path"])
            reason = check(user, at, assistant, payload.get("cwd") or os.getcwd())
            if reason:
                json.dump({"decision": "block", "reason": reason}, sys.stdout, ensure_ascii=False)
            return 0
        if argv[:1] == ["omp"]:
            transcript = argv[argv.index("--transcript") + 1]
            cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
            user, at, assistant = read_omp(transcript)
            reason = check(user, at, assistant, cwd)
            if reason:
                sys.stdout.write(json.dumps({"key": f"{at}", "reason": reason}, ensure_ascii=False))
    except Exception as error:  # 检查失败一律放行，不能卡住 Agent
        sys.stderr.write(f"memory-write-check: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
