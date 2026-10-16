"""Generate local secrets without printing them or putting passwords in arguments."""
import getpass
import re
import secrets
from pathlib import Path
from werkzeug.security import generate_password_hash


def main():
    username=input('Administrator username [admin]: ').strip() or 'admin'
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,80}',username):
        raise SystemExit('Use1–80 letters, digits, or _.@- for the username.')
    password=getpass.getpass('New password (at least12 characters): ')
    if len(password)<12 or len(password)>1024:
        raise SystemExit('Password must contain12–1024 characters.')
    if password!=getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords do not match.')
    path=Path(__file__).resolve().parents[1]/'instance/admin-credentials.env'
    path.parent.mkdir(exist_ok=True)
    try:
        with path.open('x') as output:
            path.chmod(0o600)
            output.write("ADMIN_USERNAME='"+username+"'\n")
            output.write("ADMIN_PASSWORD_HASH='"+generate_password_hash(password,method='scrypt')+"'\n")
            output.write("SECRET_KEY='"+secrets.token_urlsafe(48)+"'\n")
    except FileExistsError:
        raise SystemExit('instance/admin-credentials.env already exists; preserve it or move it privately before generating replacements.')
    print('Secrets saved privately to instance/admin-credentials.env. Enter those values in Vercel; never commit or paste them into chat.')

if __name__=='__main__':main()
