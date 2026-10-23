"""Create an account (or reset a password) from the command line.

    python -m scripts.create_user guru            # new account
    python -m scripts.create_user guru --reset    # new password for an existing account

The password is typed at a hidden prompt; it is never taken from a file, an argument or the environment.
In Docker:  docker compose exec app python -m scripts.create_user guru
"""

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from app.auth.service import AuthError, create_user, set_password
from app.config import load_settings
from app.db import connect


def main(argv: Sequence[str] | None = None, ask: Callable[[str], str] = getpass.getpass) -> int:
    """Run the tool; returns the exit code (0 on success)."""
    parser = argparse.ArgumentParser(description="Create an account or reset a password.")
    parser.add_argument("username")
    parser.add_argument("--reset", action="store_true", help="set a new password for an existing account")
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
            user = create_user(conn, args.username, password)
            sys.stdout.write(f"Account '{user.username}' created. You can sign in now.\n")
    except AuthError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
