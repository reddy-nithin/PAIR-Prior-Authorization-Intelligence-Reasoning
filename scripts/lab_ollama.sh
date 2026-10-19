#!/usr/bin/env bash
# shellcheck disable=SC2016  # single-quoted $ expands on the lab server, by design
# Control PAIR's Ollama on the shared lab GPU server.
#
# Rule: Nithin picks the GPU every run. Nothing starts without an explicit GPU
# number, and every run ends with `stop`.
#
#   scripts/lab_ollama.sh gpus          show GPUs and which are free
#   scripts/lab_ollama.sh start <gpu>   start Ollama on that GPU + open the tunnel
#   scripts/lab_ollama.sh status        is it running, on which GPU
#   scripts/lab_ollama.sh stop          stop Ollama + close the tunnel
#
# Env: PAIR_LAB_HOST (ssh alias, default umkc), PAIR_LAB_PORT (Mac port, default 11435).

set -euo pipefail

HOST="${PAIR_LAB_HOST:-umkc}"
LOCAL_PORT="${PAIR_LAB_PORT:-11435}"
REMOTE_PORT=11434
FREE_MIB=1024
STATE_FILE="$(cd "$(dirname "$0")/.." && pwd)/.claude/lab-ollama.state"
TUNNEL_PATTERN="ssh .*-L ${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}"

remote() {
    # The server prints a logon banner; drop it so output stays readable.
    ssh -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10 "$HOST" "$1" 2>&1 | grep -v -E '^\*|║|╔|╚' || true
}

running_gpu() {
    # Prints the GPU our Ollama was started on, or nothing if it isn't running.
    remote 'pid=$(pgrep -u "$USER" -x ollama | head -1); [ -n "$pid" ] && tr "\0" "\n" < /proc/$pid/environ | sed -n "s/^CUDA_VISIBLE_DEVICES=//p"'
}

cmd_gpus() {
    echo "GPUs on $HOST (free = under ${FREE_MIB} MiB used and under 5% load):"
    remote "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits" |
        awk -F', ' -v free="$FREE_MIB" '{
            state = ($3 < free && $5 < 5) ? "FREE" : "busy";
            printf "  GPU %s  %-16s %6s / %s MiB  %3s%%  %s\n", $1, $2, $3, $4, $5, state }'
    local gpu
    gpu="$(running_gpu)"
    if [ -n "$gpu" ]; then echo "PAIR Ollama is running on GPU $gpu."; else echo "PAIR Ollama is not running."; fi
}

cmd_start() {
    local gpu="${1:-}" force="${2:-}"
    if ! [[ "$gpu" =~ ^[0-9]+$ ]]; then
        echo "Pick a GPU first: run '$0 gpus', then '$0 start <gpu>'." >&2
        exit 2
    fi
    local current
    current="$(running_gpu)"
    if [ -n "$current" ]; then
        echo "PAIR Ollama is already running on GPU $current. Run '$0 stop' first." >&2
        exit 1
    fi
    local used
    used="$(remote "nvidia-smi -i $gpu --query-gpu=memory.used --format=csv,noheader,nounits" | tr -d ' ')"
    if ! [[ "$used" =~ ^[0-9]+$ ]]; then
        echo "GPU $gpu not found on $HOST: $used" >&2
        exit 1
    fi
    if [ "$used" -ge "$FREE_MIB" ] && [ "$force" != "--force" ]; then
        echo "GPU $gpu already has ${used} MiB in use (someone else's job?). Pick another, or add --force." >&2
        exit 1
    fi
    if lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "Mac port $LOCAL_PORT is busy. Set PAIR_LAB_PORT to a free port." >&2
        exit 1
    fi
    # Vulkan off: it ignores CUDA_VISIBLE_DEVICES and would see every GPU.
    remote "CUDA_VISIBLE_DEVICES=$gpu OLLAMA_VULKAN=0 GGML_VK_VISIBLE_DEVICES= OLLAMA_HOST=127.0.0.1:$REMOTE_PORT \
        nohup setsid \$HOME/.local/ollama/bin/ollama serve > \$HOME/.local/ollama/serve.log 2>&1 < /dev/null &"
    ssh -o BatchMode=yes -o LogLevel=ERROR -o ExitOnForwardFailure=yes -f -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "$HOST"
    local version=""
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        version="$(curl -s -m 2 "http://localhost:${LOCAL_PORT}/api/version" || true)"
        [ -n "$version" ] && break
        sleep 1
    done
    if [ -z "$version" ]; then
        echo "Ollama didn't answer. Stopping to leave nothing behind." >&2
        cmd_stop
        exit 1
    fi
    printf 'gpu=%s\nport=%s\nstarted=%s\n' "$gpu" "$LOCAL_PORT" "$(date '+%Y-%m-%d %H:%M')" > "$STATE_FILE"
    echo "PAIR Ollama running on GPU $gpu, reachable at http://localhost:${LOCAL_PORT} $version"
    echo "When done: $0 stop"
}

cmd_stop() {
    pkill -f "$TUNNEL_PATTERN" && echo "Tunnel closed." || echo "No tunnel open."
    remote 'if pgrep -u "$USER" -x ollama >/dev/null; then pkill -u "$USER" -x ollama; sleep 2; fi;
            pgrep -u "$USER" -x ollama >/dev/null && echo "WARNING: Ollama still running" || echo "Lab Ollama stopped."'
    rm -f "$STATE_FILE"
    cmd_gpus
}

cmd_status() {
    local gpu
    gpu="$(running_gpu)"
    if [ -n "$gpu" ]; then echo "Lab Ollama: running on GPU $gpu"; else echo "Lab Ollama: stopped"; fi
    if pgrep -f "$TUNNEL_PATTERN" >/dev/null; then echo "Tunnel: open on localhost:$LOCAL_PORT"; else echo "Tunnel: closed"; fi
    if [ -f "$STATE_FILE" ]; then sed 's/^/State: /' "$STATE_FILE"; fi
}

case "${1:-}" in
    gpus) cmd_gpus ;;
    start) cmd_start "${2:-}" "${3:-}" ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    *) echo "Usage: $0 {gpus|start <gpu> [--force]|status|stop}" >&2; exit 2 ;;
esac
