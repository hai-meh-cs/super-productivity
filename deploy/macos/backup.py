#!/usr/bin/env python3
"""Create a private full database dump and config copy; retain seven daily backups."""
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

os.umask(0o077)
state = Path(sys.argv[1]).resolve()
config = json.loads((state / 'install.json').read_text())
pg = Path(config['postgres_bin'])
with (state / 'backup.lock').open('w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    name = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    staging = state / 'backups' / (name + '.partial')
    staging.mkdir()
    subprocess.run([str(pg / 'pg_dump'), '-h', str(state / 'run'), '-p',
                    str(config['pg_port']), '-d', 'supersync', '-Fc',
                    '-f', str(staging / 'database.dump')], check=True)
    subprocess.run([str(pg / 'pg_restore'), '--list', str(staging / 'database.dump')],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy2(state / 'server.env', staging / 'server.env')
    shutil.copy2(state / 'install.json', staging / 'install.json')
    staging.rename(state / 'backups' / name)
    completed = sorted(p for p in (state / 'backups').iterdir()
                       if p.is_dir() and not p.name.endswith('.partial'))
    for old in completed[:-7]:
        shutil.rmtree(old)
    for log in (state / 'logs').glob('*.log'):
        if log.stat().st_size > 5 * 1024 * 1024:
            shutil.copy2(log, log.with_suffix(log.suffix + '.previous'))
            with log.open('w'):
                pass
    print('Local backup completed:', name)
