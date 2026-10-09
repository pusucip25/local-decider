#!/usr/bin/env bash
# local-decider — one-shot runner.
#
# Brings up the whole stack, runs the browser loop with a LOCAL decider, then
# verifies the result in the DOM (not from the agent's report) and tears
# everything down again.
#
#   ./run.sh --url tests/form.html --goal "Fill the booking form: ..."
#   ./run.sh --help
#
# The decider is chosen in this order:
#   1. TYPESAFE_BASE_URL if already exported
#   2. a local Ollaya daemon on 127.0.0.1:11435, if it answers
#   3. the System One shim in front of a local Ollama model (--model)
set -uo pipefail

HERE="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
cd "$HERE"

URL="tests/form.html"
GOAL="Fill the booking form: full name Maria Ionescu, email maria@example.com, country Romania, accept the terms, then submit the booking."
MODEL="${LO_DECIDER_MODEL:-}"
SHIM_BASE_URL="${LO_DECIDER_BASE_URL:-}"
TEXT_MODEL="${LO_TEXT_MODEL:-}"
MAX_STEPS=14
CDP_PORT="${LO_CDP_PORT:-9222}"
SHIM_PORT="${LO_SHIM_PORT:-11888}"
CHROME="${LO_CHROME:-chromium}"
HEADLESS="${LO_HEADLESS:-0}"
KEEP=0
VERIFY=1

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; cat <<'EOF'

Options:
  --url PATH|URL      page to run against (default: the bundled test form)
  --goal "TEXT"       the goal, natural language
  --model NAME        Ollama model behind the shim (else: use Ollaya if running)
  --text-model NAME   small model used only to TYPE_TEXT / SELECT
  --max-steps N       step ceiling (default 14)
  --cdp-port N        Chrome CDP port (default 9222)
  --shim-port N       System One shim port (default 11888)
  --headless          run Chrome headless (CI / no window)
  --no-verify         skip the DOM verification step
  --keep              leave Chrome / the shim running afterwards
  -h, --help          this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL="$2"; shift 2;;
    --goal) GOAL="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --text-model) TEXT_MODEL="$2"; shift 2;;
    --max-steps) MAX_STEPS="$2"; shift 2;;
    --cdp-port) CDP_PORT="$2"; shift 2;;
    --shim-port) SHIM_PORT="$2"; shift 2;;
    --headless) HEADLESS=1; shift;;
    --no-verify) VERIFY=0; shift;;
    --keep) KEEP=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown option: $1" >&2; usage; exit 2;;
  esac
done

PY="$HERE/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
say() { printf '\033[36m▸\033[0m %s\n' "$*"; }
die() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

pids=()
cleanup() {
  if [ "$KEEP" = 1 ]; then
    say "left running: pids ${pids[*]:-none}"
    return
  fi
  for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
}
trap cleanup EXIT

# ── 1. dependency ────────────────────────────────────────────────────
"$PY" -c "import websocket" 2>/dev/null || die \
  "websocket-client missing. Create the venv:  python3 -m venv .venv && .venv/bin/pip install websocket-client"

# ── 2. Chrome with CDP ───────────────────────────────────────────────
if curl -s --max-time 2 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1; then
  say "CDP already listening on :$CDP_PORT"
else
  say "starting $CHROME with CDP on :$CDP_PORT${HEADLESS:+ (headless)}"
  chrome_args=(--remote-debugging-port="$CDP_PORT"
               --user-data-dir="$HERE/.chrome-jev"
               --no-first-run --no-default-browser-check)
  [ "$HEADLESS" = 1 ] && chrome_args+=(--headless=new --no-sandbox --disable-gpu)
  "$CHROME" "${chrome_args[@]}" about:blank >/dev/null 2>&1 &
  pids+=($!)
  for _ in $(seq 1 25); do
    curl -s --max-time 1 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1 && break
    sleep 0.4
  done
  curl -s --max-time 2 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1 \
    || die "Chrome did not open CDP on :$CDP_PORT"
fi

# ── 3. decider ───────────────────────────────────────────────────────
# Readiness must be a cheap TCP check. Probing /v1/systemone with a POST makes
# the shim call the model for real (slow, and it burns a generation per check).
tcp_open() {   # host port
  (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null || return 1
  exec 3<&- 3>&- 2>/dev/null
  return 0
}

url_parts() {  # http://host:port/path -> "host port"
  local u="${1#*://}" hp
  hp="${u%%/*}"
  if [ "$hp" != "${hp%:*}" ]; then printf '%s %s\n' "${hp%%:*}" "${hp##*:}"
  else printf '%s 80\n' "$hp"; fi
}

decider_up() {  # $1 = base url
  set -- $(url_parts "$1"); tcp_open "$1" "$2"
}

HOSTED=0
if [ "${TYPESAFE_API_KEY:-}" != "" ] && [ "${TYPESAFE_API_KEY:-}" != "local" ]; then
  HOSTED=1
fi

if [ "$HOSTED" = 1 ]; then
  say "decider: hosted arm (TYPESAFE_API_KEY is set, no local swap)"
  unset TYPESAFE_BASE_URL
elif [ -n "${TYPESAFE_BASE_URL:-}" ] && decider_up "$TYPESAFE_BASE_URL"; then
  say "decider: TYPESAFE_BASE_URL=$TYPESAFE_BASE_URL (listening)"
elif [ -n "${TYPESAFE_BASE_URL:-}" ]; then
  say "decider: TYPESAFE_BASE_URL=$TYPESAFE_BASE_URL is NOT listening — falling back to a local one"
elif tcp_open 127.0.0.1 11435; then
  export TYPESAFE_BASE_URL="http://127.0.0.1:11435"
  say "decider: local Ollaya daemon on :11435"
elif tcp_open 127.0.0.1 "$SHIM_PORT"; then
  export TYPESAFE_BASE_URL="http://127.0.0.1:$SHIM_PORT"
  say "decider: a System One shim is already listening on :$SHIM_PORT"
else
  [ -n "$MODEL" ] || die "no decider: Ollaya is not running and --model was not given"
  say "decider: System One shim (:${SHIM_PORT}) in front of '$MODEL'${SHIM_BASE_URL:+ @ $SHIM_BASE_URL}"
  shim_args=(--model "$MODEL" --port "$SHIM_PORT")
  [ -n "$SHIM_BASE_URL" ] && shim_args+=(--base-url "$SHIM_BASE_URL")
  "$PY" -u jev-browser/scripts/hammer_systemone.py "${shim_args[@]}" >/dev/null 2>&1 &
  pids+=($!)
  export TYPESAFE_BASE_URL="http://127.0.0.1:$SHIM_PORT"
  for _ in $(seq 1 30); do
    tcp_open 127.0.0.1 "$SHIM_PORT" && break
    sleep 0.3
  done
  tcp_open 127.0.0.1 "$SHIM_PORT" || die "the shim did not come up on :$SHIM_PORT"
fi

export TYPESAFE_API_KEY="${TYPESAFE_API_KEY:-local}"
export TYPESAFE_MODEL="${TYPESAFE_MODEL:-${MODEL:-winnow:e4b}}"
export JEV_TEXT_PROVIDER="${JEV_TEXT_PROVIDER:-ollama}"
[ -n "$TEXT_MODEL" ] && export JEV_TEXT_MODEL="$TEXT_MODEL"

# ── 4. run ───────────────────────────────────────────────────────────
case "$URL" in
  http*|file://*) RUN_URL="$URL";;
  /*) RUN_URL="file://$URL";;
  *)  RUN_URL="file://$HERE/jev-browser/$URL";;
esac

say "goal: $GOAL"
say "model: $TYPESAFE_MODEL   url: $RUN_URL"
echo
cd "$HERE/jev-browser"
./jev-browser doctor
echo
./jev-browser run --url "$RUN_URL" --goal "$GOAL" --max-steps "$MAX_STEPS" -v
RUN_STATUS=$?

# ── 5. proof: the page, not the agent ────────────────────────────────
if [ "$VERIFY" = 1 ]; then
  echo
  say "DOM verification (the page decides, not the agent):"
  "$PY" scripts/state.py || true
fi
exit $RUN_STATUS
