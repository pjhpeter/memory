#!/bin/sh
# 把本仓库维护的 skill 链接到各 Agent 的 skill 目录。可重复运行；已是正确链接的跳过，同名真实目录不覆盖。
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)

link() {
  target=$1
  dest=$2
  mkdir -p "$(dirname "$dest")"
  if [ -L "$dest" ]; then
    [ "$(readlink "$dest")" = "$target" ] && return 0
    rm "$dest"
  elif [ -e "$dest" ]; then
    echo "跳过 $dest：已有同名文件或目录，先确认能否删除" >&2
    return 0
  fi
  ln -s "$target" "$dest"
  echo "已链接 $dest → $target"
}

for skill in "$SRC"/skills/*/; do
  name=$(basename "$skill")
  link "$SRC/skills/$name" "$HOME/.agents/skills/$name"
  link "$HOME/.agents/skills/$name" "$HOME/.claude/skills/$name"
done
