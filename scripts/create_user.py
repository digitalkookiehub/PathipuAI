"""Create an account (or reset a password) from the command line.

    python -m scripts.create_user guru --email guru@example.com   # new account (the first one becomes the owner)
    python -m scripts.create_user helper --admin                  # another owner (can approve sign-ups)
    python -m scripts.create_user guru --reset                    # new password for an existing account

The password is typed at a hidden prompt; it is never taken from a file, an argument or the environment.
In Docker:  docker compose exec app python -m scripts.create_user guru
"""

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from app.auth.service import EMAIL_RE, AuthError, create_user, set_password, user_count
from app.config import load_settings
from app.db import connect


def main(argv: Sequence[str] | None = None, ask: Callable[[str], str] = getpass.getpass) -> int:
    """Run the tool; returns the exit code (0 on success)."""
    parser = argparse.ArgumentParser(description="Create an account or reset a password.")
    parser.add_argument("username")
    parser.add_argument("--reset", action="store_true", help="set a new password for an existing account")
    parser.add_argument("--email", help="email address for password-reset links (default: the username, if it is one)")
    parser.add_argument("--admin", action="store_true", help="make the account an owner (the first account always is)")
    args = parser.parse_args(argv)

    password = ask("Password: ")
    if ask("Type the password again: ") != password:
        sys.stderr.write("The two passwords are not the same.\n")
        return 1
    conn = connect(load_settings().database_path)
    try:
        if args.reset:
            set_password(conn, args.username, password)
            sys.stdout.write("The password was changed and every browser was signed out.\n")
        else:
            email = args.email or (args.username if EMAIL_RE.fullmatch(args.username.strip()) else None)
            owner = args.admin or user_count(conn) == 0
            user = create_user(conn, args.username, password, email=email, is_admin=owner)
            role = "an owner" if owner else "a normal user"
            sys.stdout.write(f"Account '{user.username}' created as {role}. You can sign in now.\n")
    except AuthError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
