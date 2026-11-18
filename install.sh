#!/usr/bin/env bash
# MemoryGene 一步安装
#
# 用法（macOS / Linux，Python 3.10+）：
#   curl -fsSL https://raw.githubusercontent.com/Loris018/MemoryGene/main/install.sh | bash
#
# 可调环境变量：
#   MEMORYGENE_DIR=~/code/MemoryGene   源码目录（默认 ~/MemoryGene）
#   MEMORYGENE_BRANCH=main             分支（默认 main）
#   NO_DSH_SKILL=1                     跳过 DeepSeek Harness skill 安装
#   DSH_SKILL_TARGET=user|project      skill 安装范围（默认 user，装到 ~/.dsh/skills）
#
#   MEMORYGENE_DEMO_WORKSPACE / MEMORYGENE_DEMO_DB  练习目录和数据库路径
# 克隆或更新源码，安装核心与可选技能，绑定练习目录并校验读操作。
set -euo pipefail

REPO_URL="https://github.com/Loris018/MemoryGene.git"
BRANCH="${MEMORYGENE_BRANCH:-main}"
DIR="${MEMORYGENE_DIR:-$HOME/MemoryGene}"
SKILL_TARGET="${DSH_SKILL_TARGET:-user}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "缺少 git"
command -v python3 >/dev/null 2>&1 || die "缺少 python3"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "需要 Python 3.10+（当前 $(python3 -V 2>&1)）"

if [ -d "$DIR/.git" ]; then
  say "更新已有源码：$DIR"
  remote_url=$(git -C "$DIR" config --get remote.origin.url)
  case "$remote_url" in
    "$REPO_URL"|https://github.com/Loris018/MemoryGene|git@github.com:Loris018/MemoryGene.git) ;;
    *) die "目录属于另一个项目。请设置 MEMORYGENE_DIR 选择新目录。" ;;
  esac
  [ "$(git -C "$DIR" branch --show-current)" = "$BRANCH" ] || die "当前目录不在 $BRANCH 分支。请设置 MEMORYGENE_DIR 选择新目录。"
  git -C "$DIR" pull --ff-only origin "$BRANCH" || die "源码更新失败；请检查网络或本地修改后重试。"
else
  [ -e "$DIR" ] && die "$DIR 已存在但不是 git 仓库；设置 MEMORYGENE_DIR 换一个目录"
  say "克隆源码到 $DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$DIR"
fi

cd "$DIR"

if [ -x .venv/bin/python ]; then
  say "复用已有虚拟环境 .venv"
else
  say "创建虚拟环境 .venv"
  python3 -m venv .venv
fi

say "安装 memorygene（可编辑模式）"
.venv/bin/python -m pip install -q -e .

if [ "${NO_DSH_SKILL:-0}" != "1" ] && [ -f scripts/install_dsh_skill.py ]; then
  say "安装 DeepSeek Harness skill（--target ${SKILL_TARGET}）"
  .venv/bin/python scripts/install_dsh_skill.py --target "$SKILL_TARGET" \
    || warn "skill 安装失败，可稍后手动执行：.venv/bin/python scripts/install_dsh_skill.py --target $SKILL_TARGET"
fi

say "自检 memorygene-dsh doctor"
.venv/bin/memorygene-dsh doctor || warn "doctor 未通过（可能本机未安装 DeepSeek Harness）"

demo_workspace="${MEMORYGENE_DEMO_WORKSPACE:-$HOME/MemoryGene-Demo}"
demo_db="${MEMORYGENE_DEMO_DB:-$HOME/.memorygene/projects/starter/decisions.sqlite}"
say "连接练习工作区 / Preparing the practice workspace"
.venv/bin/python scripts/bind_project.py --workspace "$demo_workspace" --db "$demo_db" --name mg_starter --grok
.venv/bin/python -m memorygene.project project_read --db "$demo_db" <<<'{"task":"poster"}' >/dev/null

say "安装完成 / Ready"
printf '工作目录 / Open this folder in your assistant: %s\n' "$demo_workspace"
printf '%s\n' '示例：在 release 任务中记下生产和测试日志都保留 7 天。' 'Try: For the release task, remember that production and test logs are kept for 7 days.'
