#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
# Put a supported arm64 Node 24 installation first on PATH.
npm ci --ignore-scripts --include-workspace-root=false \
  --workspace=packages/sync-core --workspace=packages/shared-schema \
  --workspace=packages/super-sync-server --no-audit --no-fund
npm run sync-core:build
npm run shared-schema:build
npm exec --workspace=packages/super-sync-server -- prisma generate
npm run build --workspace=packages/super-sync-server
