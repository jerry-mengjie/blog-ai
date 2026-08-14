#!/usr/bin/env bash
# 一键启动五个进程: backend-blog / backend-agent / backend-rag / frontend-app / frontend-admin
#
# 用法:
#   ./dev.sh <AI_API_KEY>
#   AI_API_KEY=sk-xxx ./dev.sh
#
# Key 会以环境变量覆盖 backend-agent / backend-rag 的 .env, 不写回文件。
# Ctrl+C 会把五个子进程一起停掉。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
KEY="${1:-${AI_API_KEY:-}}"

if [[ -z "${KEY}" ]]; then
  echo "用法: $0 <AI_API_KEY>" >&2
  echo "  或: AI_API_KEY=sk-xxx $0" >&2
  exit 1
fi

# 子进程 PID, Ctrl+C 时统一回收
PIDS=()

cleanup() {
  trap - EXIT INT TERM
  local pid
  # 先杀直接子进程, 再扫 uvicorn --reload / npm→vite 拉起的孙进程
  for pid in "${PIDS[@]}"; do
    pkill -P "${pid}" 2>/dev/null || true
    kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 带颜色前缀转发子进程日志, 五个窗口挤在一个终端里也能分清来源
prefix() {
  local name="$1" color="$2"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    printf "\033[%sm[%s]\033[0m %s\n" "${color}" "${name}" "${line}"
  done
}

start() {
  local name="$1" color="$2" dir="$3"
  shift 3
  # 进程替换转发日志, $! 仍是服务本身的 PID(管道写法会拿到 prefix 的 PID)
  (
    cd "${ROOT}/${dir}"
    exec "$@"
  ) > >(prefix "${name}" "${color}") 2>&1 &
  PIDS+=("$!")
}

export AI_API_KEY="${KEY}"

echo "启动中 (AI_API_KEY 已注入 agent / rag) ..."
echo "  移动端     http://localhost:5173"
echo "  管理后台   http://localhost:5174"
echo "  业务 API   http://127.0.0.1:8000/docs"
echo "  编排 API   http://127.0.0.1:8001/docs"
echo "  检索 API   http://127.0.0.1:8002/docs"
echo "Ctrl+C 停止全部进程"
echo

# 颜色: 32 绿 / 36 青 / 35 紫 / 33 黄 / 34 蓝
start blog   32 backend-blog  uv run uvicorn app.main:app --reload --port 8000
start agent  36 backend-agent uv run uvicorn app.main:app --reload --port 8001
start rag    35 backend-rag   uv run uvicorn app.main:app --reload --port 8002
start app    33 frontend-app  npm run dev
start admin  34 frontend-admin npm run dev

wait
