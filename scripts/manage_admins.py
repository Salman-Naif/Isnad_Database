"""
Manage admin accounts from the command line.

    python scripts/manage_admins.py create <username>     # prompts for the password
    python scripts/manage_admins.py password <username>   # reset a password (signs out everywhere)
    python scripts/manage_admins.py delete <username>
    python scripts/manage_admins.py list

On Railway, run these from the service shell (railway ssh) so they use the
database on the Volume. Admins can also add each other from the dashboard.
"""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from any folder
# Windows consoles default to a legacy code page that cannot print Arabic.
sys.stdout.reconfigure(encoding="utf-8")

from app.db.sqlite import init_db  # noqa: E402
from app.services import auth  # noqa: E402


def ask_password() -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Isnad admin accounts")
    parser.add_argument("action", choices=["create", "password", "delete", "list"])
    parser.add_argument("username", nargs="?")
    args = parser.parse_args()

    init_db()

    if args.action == "list":
        for admin in auth.list_admins():
            print(f"{admin.id:>4}  {admin.username:<32} {admin.created_at}")
        return

    if not args.username:
        parser.error(f"'{args.action}' needs a username")

    try:
        if args.action == "create":
            auth.create_admin(args.username, ask_password())
            print(f"Created admin {args.username!r}")
        elif args.action == "password":
            if not auth.set_password(args.username, ask_password()):
                sys.exit(f"No admin named {args.username!r}")
            print(f"Password changed for {args.username!r}")
        elif args.action == "delete":
            admin = next((a for a in auth.list_admins() if a.username == args.username), None)
            if admin is None:
                sys.exit(f"No admin named {args.username!r}")
            auth.delete_admin(admin.id)
            print(f"Deleted admin {args.username!r}")
    except auth.AuthError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
