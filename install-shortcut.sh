#!/usr/bin/env bash
# Install a shortcut for local-decider:
#   * a launcher on PATH      -> ~/.local/bin/local-decider
#   * a desktop entry         -> ~/.local/share/applications/local-decider.desktop
#   * optionally on Desktop   -> ~/Desktop/local-decider.desktop   (--desktop)
#   * optionally an Hyprland keybind hint (it just prints one, it edits nothing)
#
#   ./install-shortcut.sh [--desktop] [--uninstall]
set -uo pipefail

HERE="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
DESKTOP_DIR="${HOME}/Desktop"
TERMINAL="${LO_TERMINAL:-foot}"

WANT_DESKTOP=0
UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --desktop) WANT_DESKTOP=1;;
    --uninstall) UNINSTALL=1;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $a" >&2; exit 2;;
  esac
done

LINK="$BIN_DIR/local-decider"
ENTRY="$APP_DIR/local-decider.desktop"

if [ "$UNINSTALL" = 1 ]; then
  rm -f "$LINK" "$ENTRY" "$DESKTOP_DIR/local-decider.desktop"
  command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" 2>/dev/null
  echo "removed: $LINK, $ENTRY${WANT_DESKTOP:+, $DESKTOP_DIR/local-decider.desktop}"
  exit 0
fi

mkdir -p "$BIN_DIR" "$APP_DIR"
chmod +x "$HERE/run.sh" "$HERE/jev-browser/jev-browser"

ln -sfn "$HERE/run.sh" "$LINK"
echo "launcher : $LINK  ->  run.sh"

cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=local-decider
Comment=Browser agent with a local decision model — rules before weights
Exec=${TERMINAL} -e ${HERE}/run.sh --help
Icon=utilities-terminal
Terminal=false
Categories=Development;Utility;
Keywords=agent;browser;llm;cdp;
Path=${HERE}
EOF
echo "entry    : $ENTRY"

if [ "$WANT_DESKTOP" = 1 ]; then
  cp "$ENTRY" "$DESKTOP_DIR/local-decider.desktop"
  chmod +x "$DESKTOP_DIR/local-decider.desktop"
  echo "desktop  : $DESKTOP_DIR/local-decider.desktop"
fi

command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" 2>/dev/null

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo
     echo "note: $BIN_DIR is not on your PATH. Add it, e.g. in ~/.bashrc:"
     echo "      export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo
echo "usage:"
echo "  local-decider --help"
echo "  local-decider --model gemma2:2b          # any Ollama model behind the shim"
echo
echo "Hyprland keybind (add to ~/.config/hypr/bindings.conf if you want one):"
echo "  bind = SUPER, D, exec, ${TERMINAL} -e ${HERE}/run.sh --help"
