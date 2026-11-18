#!/usr/bin/env python3
"""Initial, single-user native deployment. Run after build.sh; never overwrites a setup."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import pwd
import secrets
import shutil
import subprocess
import time
from urllib.parse import urlparse


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--node', required=True, type=Path)
    parser.add_argument('--postgres-bin', required=True, type=Path)
    parser.add_argument('--coreutils-bin', required=True, type=Path)
    parser.add_argument('--public-url', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--port', type=int, default=1900)
    parser.add_argument('--pg-port', type=int, default=5437)
    args = parser.parse_args()
    os.umask(0o077)
    state = args.state_dir.resolve()
    repo = Path(__file__).resolve().parents[2]
    node = args.node.resolve()
    pg = args.postgres_bin.resolve()
    coreutils = args.coreutils_bin.resolve()
    url = urlparse(args.public_url)
    if url.scheme != 'https' or not url.hostname or url.path not in ('', '/'):
        parser.error('--public-url must be an HTTPS origin')
    if any(c in args.email for c in '\n\r\x00') or '@' not in args.email:
        parser.error('invalid email')
    if (state / 'server.env').exists() or (state / 'postgres').exists():
        parser.error('existing setup found; use its runbook instead of reinitializing')
    if not (repo / 'packages/super-sync-server/dist/src/index.js').exists():
        parser.error('build the server first')
    if not (coreutils / 'timeout').exists():
        parser.error('--coreutils-bin must contain GNU timeout')
    for directory in ('run', 'logs', 'backups', 'data', 'releases'):
        (state / directory).mkdir(parents=True, exist_ok=True, mode=0o700)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    release = state / 'releases' / revision
    release.mkdir()
    shutil.copytree(repo / 'node_modules', release / 'node_modules', symlinks=True)
    for name in ('sync-core', 'shared-schema', 'super-sync-server'):
        shutil.copytree(repo / 'packages' / name, release / 'packages' / name,
                        symlinks=True, ignore=shutil.ignore_patterns('tests', '.env', 'data'))
    package = release / 'packages/super-sync-server'
    username = pwd.getpwuid(os.getuid()).pw_name
    run([pg / 'initdb', '-D', state / 'postgres', '-U', username,
         '--auth-local=peer', '--auth-host=scram-sha-256', '-E', 'UTF8', '--locale=C'])
    (state / 'postgres/postgresql.auto.conf').write_text(
        "listen_addresses = '127.0.0.1'\n"
        f"port = {args.pg_port}\n"
        f"unix_socket_directories = '{str(state / 'run').replace(chr(39), chr(39)*2)}'\n"
        "max_connections = 30\nshared_buffers = '64MB'\n"
        "max_wal_size = '256MB'\nmin_wal_size = '64MB'\n")
    agents = Path.home() / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)

    def agent(suffix, argv, cwd=None, calendar=None):
        label = 'com.koji.supersync' + suffix
        doc = {'Label': label, 'ProgramArguments': [str(a) for a in argv],
               'StandardOutPath': str(state / 'logs' / (label + '.log')),
               'StandardErrorPath': str(state / 'logs' / (label + '.error.log')),
               'EnvironmentVariables': {'LC_ALL': 'C'},
               'Umask': 0o077, 'ProcessType': 'Background'}
        if cwd:
            doc['WorkingDirectory'] = str(cwd)
        if calendar:
            doc['StartCalendarInterval'] = calendar
        else:
            doc.update(RunAtLoad=True, KeepAlive=True, ThrottleInterval=10, ExitTimeOut=60)
        path = agents / (label + '.plist')
        if path.exists():
            raise RuntimeError(f'Existing launch agent: {path}')
        path.write_bytes(plistlib.dumps(doc))
        run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', path])

    agent('.postgres', [pg / 'postgres', '-D', state / 'postgres'])
    for _ in range(40):
        if subprocess.run([str(pg / 'pg_isready'), '-h', str(state / 'run'), '-p',
                           str(args.pg_port)], stdout=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError('PostgreSQL did not start; inspect private logs')
    password = secrets.token_urlsafe(36)
    run([pg / 'psql', '-h', state / 'run', '-p', args.pg_port, '-d', 'postgres',
         '-v', 'ON_ERROR_STOP=1'], input=f"CREATE ROLE supersync LOGIN PASSWORD '{password}';\n",
        text=True, stdout=subprocess.DEVNULL)
    run([pg / 'createdb', '-h', state / 'run', '-p', args.pg_port,
         '-O', 'supersync', 'supersync'])
    values = {
        'NODE_ENV': 'production', 'HOST': '127.0.0.1', 'PORT': str(args.port),
        'DATABASE_URL': f'postgresql://supersync:{password}@127.0.0.1:{args.pg_port}/supersync?connection_limit=5&pool_timeout=10',
        'JWT_SECRET': secrets.token_urlsafe(48), 'DATA_DIR': str(state / 'data'),
        'PUBLIC_URL': args.public_url.rstrip('/'), 'WEBAUTHN_RP_ID': url.hostname,
        'WEBAUTHN_ORIGIN': args.public_url.rstrip('/'), 'WEBAUTHN_RP_NAME': 'Personal tasks',
        'ALLOWED_EMAILS': args.email, 'TRUST_PROXY': 'loopback',
        'CORS_ORIGINS': args.public_url.rstrip('/'),
        'CAPTURE_CONNECTOR_ENABLED': 'false', 'SUPERSYNC_REVISION': revision,
        'NODE_OPTIONS': '--max-old-space-size=576',
    }
    env_file = state / 'server.env'
    env_file.write_text(''.join(f'{key}={json.dumps(value)}\n' for key, value in values.items()))
    (state / 'install.json').write_text(json.dumps({
        'revision': revision, 'repo': str(repo), 'release': str(release),
        'node': str(node), 'postgres_bin': str(pg), 'port': args.port,
        'pg_port': args.pg_port, 'public_url': args.public_url.rstrip('/'),
        'email': args.email, 'smtp_configured': False,
    }, indent=2) + '\n')
    env = dict(os.environ, **values)
    env['PATH'] = str(node.parent) + ':' + str(pg) + ':' + str(coreutils) + ':' + env['PATH']
    with (state / 'logs/migrations.log').open('w') as log:
        run(['sh', 'scripts/migrate-deploy.sh'], cwd=package, env=env,
            stdout=log, stderr=subprocess.STDOUT)
    agent('', [node, '--env-file=' + str(env_file), 'dist/src/index.js'], package)
    shutil.copy2(repo / 'deploy/macos/backup.py', state / 'backup.py')
    agent('.backup', ['/usr/bin/python3', state / 'backup.py', state],
          calendar={'Hour': 3, 'Minute': 20})
    print('Native server installed. SMTP remains unconfigured. Endpoint:', args.public_url)


if __name__ == '__main__':
    main()
