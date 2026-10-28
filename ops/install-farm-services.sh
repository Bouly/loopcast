#!/bin/zsh
# Installe les 3 services de la ferme sur le Mac (lancés au démarrage, relancés s'ils tombent) :
#   tunneld (root), Appium, Loopcast (API + dashboard + supervision).
# À lancer depuis la racine du dépôt, après avoir suivi docs/ferme-iphone.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PMD3="$(command -v pymobiledevice3 || true)"
APPIUM="$(command -v appium || true)"
[[ -n "$PMD3" ]] || { echo "pymobiledevice3 introuvable (pipx install pymobiledevice3)"; exit 1; }
[[ -n "$APPIUM" ]] || { echo "appium introuvable (npm install -g appium)"; exit 1; }
[[ -x "$ROOT/engine/.venv/bin/python" ]] || { echo "créer engine/.venv d'abord (voir docs/ferme-iphone.md)"; exit 1; }
mkdir -p "$ROOT/data/logs" "$HOME/Library/LaunchAgents"

render() {
  sed -e "s|__ROOT__|$ROOT|g" -e "s|__PATH__|$PATH|g" -e "s|__APPIUM__|$APPIUM|g" \
      -e "s|__PYMOBILEDEVICE3__|$PMD3|g" "$ROOT/ops/$1"
}

for name in com.loopcast.appium com.loopcast.serve; do
  dest="$HOME/Library/LaunchAgents/$name.plist"
  launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
  render "$name.plist" > "$dest"
  launchctl bootstrap "gui/$(id -u)" "$dest"
  echo "✓ $name"
done

dest="/Library/LaunchDaemons/com.loopcast.tunneld.plist"
sudo launchctl bootout system/com.loopcast.tunneld 2>/dev/null || true
render com.loopcast.tunneld.plist | sudo tee "$dest" >/dev/null
sudo chown root:wheel "$dest"
sudo launchctl bootstrap system "$dest"
echo "✓ com.loopcast.tunneld (root)"

echo "Empêcher la mise en veille : sudo pmset -a sleep 0 disablesleep 1"
