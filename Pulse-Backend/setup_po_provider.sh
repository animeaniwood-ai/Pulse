#!/usr/bin/env bash
set -euo pipefail

# Voroa Build Command should be: bash setup_po_provider.sh
# Installs Python requirements, Node.js 22, and the matching bgutil provider
# inside this SAME service's build image. No extra service is created.

ROOT="$HOME"
NODE_VERSION="22.20.0"
PROVIDER_VERSION="2.0.2"
NODE_DIR="$ROOT/.local/node-v22"
PROVIDER_DIR="$ROOT/bgutil-ytdlp-pot-provider"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) NODE_ARCH="x64" ;;
  aarch64|arm64) NODE_ARCH="arm64" ;;
  *) echo "Unsupported CPU architecture for bundled Node.js: $ARCH" >&2; exit 1 ;;
esac

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p "$ROOT/.local"
if [ ! -x "$NODE_DIR/bin/node" ]; then
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  NODE_TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
  curl -fL --retry 3 "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}" -o "$TMP_DIR/$NODE_TARBALL"
  mkdir -p "$NODE_DIR"
  tar -xJf "$TMP_DIR/$NODE_TARBALL" -C "$TMP_DIR"
  cp -a "$TMP_DIR/node-v${NODE_VERSION}-linux-${NODE_ARCH}/." "$NODE_DIR/"
fi
export PATH="$NODE_DIR/bin:$PATH"
node --version
npm --version

if [ ! -f "$PROVIDER_DIR/server/build/generate_once.js" ] && [ ! -f "$PROVIDER_DIR/server/build/main.js" ]; then
  rm -rf "$PROVIDER_DIR"
  git clone --depth 1 --single-branch --branch "$PROVIDER_VERSION" \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$PROVIDER_DIR"
fi
cd "$PROVIDER_DIR/server"
npm ci --no-audit --no-fund
npx tsc

# Confirm expected script output exists before allowing deployment to continue.
if [ ! -d "$PROVIDER_DIR/server/build" ]; then
  echo "bgutil provider build output was not created." >&2
  exit 1
fi
python - <<'PY'
import importlib.metadata
print("bgutil-ytdlp-pot-provider:", importlib.metadata.version("bgutil-ytdlp-pot-provider"))
PY
printf '\nPO-token provider setup completed in this Pulse service.\n'
