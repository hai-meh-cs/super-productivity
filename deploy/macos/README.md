# Native macOS SuperSync

This fork starts from Super Productivity v20.0.0. The deployment runs the existing
server on Apple Silicon, with an isolated PostgreSQL 17 cluster and launch agents.
It does not require Docker. It does not change task storage, sync or authentication.

Requirements: arm64 Node 24.15 or newer in the 24.x line, PostgreSQL 17 binaries,
GNU coreutils and GNU sed (for the upstream migration runner), a logged-in macOS
account, and an HTTPS reverse proxy that supports WebSockets. Configure SMTP for
real sign-in and account recovery; production test mode stays off.

## Initial installation

Build with the supported Node installation first on `PATH`:

```sh
sh deploy/macos/build.sh
python3 deploy/macos/setup.py \
  --state-dir "$HOME/.local/state/supersync" \
  --node /absolute/path/to/node \
  --postgres-bin /opt/homebrew/opt/postgresql@17/bin \
  --coreutils-bin /opt/homebrew/opt/coreutils/libexec/gnubin \
  --gnu-sed-bin /opt/homebrew/opt/gnu-sed/libexec/gnubin \
  --public-url https://your-mini.your-tailnet.ts.net:8443 \
  --email your-own-address@example.com
```

The script refuses to overwrite an existing database or environment file. It copies
the built server, shared packages and dependencies into a release directory, creates
an isolated database on `127.0.0.1:5437`, and runs all upstream migrations. The
application binds only `127.0.0.1:1900`. Local database administration uses peer
authentication over a private Unix socket; the application uses a password and a
five-connection pool. Secrets, logs and backups remain outside the repository.

For Tailscale, first record `tailscale serve status --json`. Add only the unused
HTTPS port; do not reset existing routes:

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:1900
```

This is private tailnet access. Each client needs Tailscale connectivity. No public
Funnel, DNS change or router port forwarding is necessary. Verify `/health`, sign-in
pages, their `Referrer-Policy: no-referrer` header and authenticated sync after setup.

## Email and clients

`server.env` is private (0600). Add the chosen provider's `SMTP_HOST`, `SMTP_PORT`,
`SMTP_SECURE`, `SMTP_USER`, `SMTP_PASS` and `SMTP_FROM` through a local secret entry
flow. Do not put credentials into shell arguments, commit them or paste them into
chat. Restart only `com.koji.supersync` after changing its environment.

Sign up with the allowlisted address. In the Super Productivity client, select
SuperSync, open its advanced configuration, set this server URL, then connect via
the browser and choose an encryption password. Keep that password independently:
server backups cannot decrypt task payloads without it. Verify two-device sync,
offline reconnect and actual iPhone reminders before relying on the setup.

## Operation

Launch agents are `com.koji.supersync.postgres`, `com.koji.supersync` and
`com.koji.supersync.backup`. They run in the installing user's GUI session;
automatic startup applies at login, not before login after a reboot. The two
services restart after exit. This setup does not alter sleep or FileVault settings.

```sh
launchctl print "gui/$(id -u)/com.koji.supersync"
launchctl kickstart -k "gui/$(id -u)/com.koji.supersync"
curl --fail http://127.0.0.1:1900/health
python3 /absolute/path/to/state/backup.py /absolute/path/to/state
```

The backup agent creates a full PostgreSQL custom-format dump plus a private copy
of the service environment and install metadata at 03:20 local time. It retains
seven completed backups and rotates its own logs above 5 MiB. These are local
backups, not protection against losing the mini. Validate restores into a separate
database. Never restore over the running service as a test.

Record the source revision, dependency lockfile hash, health/access checks and a
restore check in the installation receipt. For upgrades: build a new release,
back up first, stop only the SuperSync application, run that release's upstream
migrations, repoint its launch agent and verify health and sync. Keep the prior
release and backup until verification succeeds. Schema rollback requires the
matching database backup; switching code alone is not a database rollback.

## Scope

The server supplies encrypted sync. Its optional capture connector can add tasks;
it is disabled initially. A complete task API still depends on a running desktop
client. This deployment does not yet install a task client or implement the Koji
plugin, branding or an always-on task API.
