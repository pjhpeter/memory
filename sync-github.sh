#!/bin/sh
# 把记忆库的「框架」同步到 GitHub：只含下面列出的文件，不含任何项目记忆，也不带本仓库的提交历史。
# 用法：sh ~/.agents/memory/sync-github.sh
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
MIRROR=${MEMORY_GITHUB_MIRROR:-$HOME/.agents/memory-github}
REMOTE=git@github.com:pjhpeter/memory.git
FILES="README.md .gitignore memory-context.py memory-write-check.py sync-github.sh"

if [ ! -d "$MIRROR/.git" ]; then
  git init -q -b main "$MIRROR"
  git -C "$MIRROR" remote add github "$REMOTE"
fi

# 镜像里只允许出现白名单文件；先清掉其余内容，避免旧文件或误放的记忆残留
find "$MIRROR" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
for f in $FILES; do
  cp "$SRC/$f" "$MIRROR/$f"
done

if find "$MIRROR" -name MEMORY.md -not -path "*/.git/*" | grep -q .; then
  echo "镜像里出现了 MEMORY.md，拒绝推送" >&2
  exit 1
fi

cd "$MIRROR"
git add -A
if git diff --cached --quiet; then
  echo "框架没有变化，无需同步"
else
  git commit -q -m "同步框架（来源 $(git -C "$SRC" rev-parse --short HEAD)）"
fi
git push -q github main
echo "已同步：$(git rev-parse --short HEAD) → $REMOTE"
