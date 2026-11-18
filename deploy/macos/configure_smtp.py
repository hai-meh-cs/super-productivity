#!/usr/bin/env python3
"""Enter SMTP credentials locally, verify them, then restart only SuperSync."""
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys

os.umask(0o077)
state = Path(sys.argv[1]).resolve()
config = json.loads((state / 'install.json').read_text())
path = state / 'server.env'
values = {k: json.loads(v) for k, v in
          (line.split('=', 1) for line in path.read_text().splitlines())}
host = input('SMTP host [smtp.gmail.com]: ').strip() or 'smtp.gmail.com'
port = int(input('SMTP port [465]: ').strip() or '465')
user = input(f'SMTP username [{config["email"]}]: ').strip() or config['email']
password = getpass.getpass('SMTP password / app password (hidden): ')
sender = input(f'From address [{user}]: ').strip() or user
if not password or any('\n' in s or '\r' in s for s in (host, user, password, sender)):
    raise SystemExit('Invalid settings; nothing saved.')
values.update(SMTP_HOST=host, SMTP_PORT=str(port), SMTP_SECURE=str(port == 465).lower(),
              SMTP_USER=user, SMTP_PASS=password, SMTP_FROM=sender)
env = dict(os.environ, **values)
env['SP_MAILER_PATH'] = str(Path(config['release']) / 'node_modules/nodemailer')
code = '''
const mailer = require(process.env.SP_MAILER_PATH);
const transport = mailer.createTransport({
  host: process.env.SMTP_HOST, port: Number(process.env.SMTP_PORT),
  secure: process.env.SMTP_SECURE === 'true',
  auth: {user: process.env.SMTP_USER, pass: process.env.SMTP_PASS},
  connectionTimeout: 15000, greetingTimeout: 15000, socketTimeout: 15000
});
transport.verify().then(() => { transport.close(); }).catch(() => {
  transport.close(); process.exitCode = 1;
});
'''
result = subprocess.run([config['node'], '-e', code], env=env, timeout=45,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if result.returncode:
    raise SystemExit('SMTP verification failed; nothing saved. Check host and credentials.')
temp = path.with_suffix('.pending')
temp.write_text(''.join(f'{key}={json.dumps(value)}\n' for key, value in values.items()))
temp.replace(path)
config['smtp_configured'] = True
(state / 'install.json').write_text(json.dumps(config, indent=2) + '\n')
subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/com.koji.supersync'],
               check=True)
print('SMTP authentication verified and saved privately. SuperSync restarted.')
