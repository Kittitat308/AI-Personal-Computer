#!/bin/sh
set -u

echo '=== SERVICE ==='
systemctl is-active aipc-auth.service
systemctl show aipc-auth.service \
    -p User -p Group -p ProtectSystem -p ProtectHome -p NoNewPrivileges

echo '=== SOCKET/DB ==='
stat -c '%U %G %a %n' \
    /run/ai-personal-computer/auth.sock \
    /var/lib/ai-personal-computer \
    /var/lib/ai-personal-computer/database \
    /var/lib/ai-personal-computer/database/auth.db

echo '=== DATABASE COUNTS ==='
/opt/ai-personal-computer/.venv/bin/python - <<'PY'
import sqlite3
connection = sqlite3.connect('/var/lib/ai-personal-computer/database/auth.db')
print('users', connection.execute('SELECT COUNT(*) FROM users').fetchone()[0])
print('faces', connection.execute('SELECT COUNT(*) FROM face_profiles').fetchone()[0])
PY

echo '=== FORBIDDEN OLD DATA IN NEW SYSTEM ==='
find /opt/ai-personal-computer /var/lib/ai-personal-computer \
    -type f \
    \( -name gmail_token.json \
       -o -name calendar_token.json \
       -o -path '*/browser_data/*' \) \
    -print

echo '=== HEALTH AS CURRENT USER ==='
/opt/ai-personal-computer/.venv/bin/python - <<'PY'
from aipc_system.auth_client import AuthClient
print(AuthClient().health())
PY
