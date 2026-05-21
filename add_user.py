#!/usr/bin/env python3
"""
Generate a bcrypt password hash for a user, suitable for pasting into
`.streamlit/secrets.toml` under the `[auth.users]` section.

Usage
-----
    # Interactive (recommended — password never appears in shell history)
    python add_user.py alice

    # Output ready to paste:
    #   alice = "$2b$12$..."

Optional: generate a cookie signing key
    python add_user.py --new-cookie-key

Notes
-----
- The password is read from a hidden prompt; it does NOT appear in your
  shell history.
- The bcrypt hash always starts with "$2b$12$..." and is safe to commit
  to a private secrets file. NEVER commit it to a public repository.
- Bcrypt with cost factor 12 takes ~250ms to verify, which is the
  recommended default in 2026.
"""
import argparse
import getpass
import secrets
import sys

try:
    import bcrypt
except ImportError:
    sys.stderr.write(
        "ERROR: bcrypt is not installed.\n"
        "Install it with:  pip install bcrypt>=4.0.0\n"
    )
    sys.exit(1)


BCRYPT_COST = 12  # ~250ms per verify on a modern laptop. Industry default.


def generate_hash(password: str) -> str:
    """Generate a bcrypt hash for the given password using cost factor 12."""
    salt = bcrypt.gensalt(rounds=BCRYPT_COST)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def generate_cookie_key() -> str:
    """Generate a 32-byte cryptographically random hex string for cookie signing."""
    return secrets.token_hex(32)


def cmd_add_user(username: str) -> int:
    if not username:
        sys.stderr.write("ERROR: username is required.\n")
        return 2

    # Read password twice, hidden — never echoed to the screen
    pw1 = getpass.getpass(f"Password for '{username}': ")
    if not pw1:
        sys.stderr.write("ERROR: password is empty.\n")
        return 2
    if len(pw1) < 8:
        sys.stderr.write(
            "WARNING: passwords shorter than 8 characters are easy to brute-force "
            "over a public URL. Consider a longer one.\n"
        )
    pw2 = getpass.getpass("Confirm password: ")
    if pw1 != pw2:
        sys.stderr.write("ERROR: passwords don't match.\n")
        return 2

    h = generate_hash(pw1)

    print("\n" + "=" * 70)
    print(f"Bcrypt hash generated for user: {username}")
    print("=" * 70)
    print()
    print("Paste this line into .streamlit/secrets.toml under [auth.users]:")
    print()
    print(f'  {username} = "{h}"')
    print()
    print("=" * 70)
    return 0


def cmd_new_cookie_key() -> int:
    key = generate_cookie_key()
    print("\n" + "=" * 70)
    print("New cookie signing key (32 random bytes, hex-encoded)")
    print("=" * 70)
    print()
    print("Paste this into .streamlit/secrets.toml under [auth]:")
    print()
    print(f'  cookie_signing_key = "{key}"')
    print()
    print("=" * 70)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate bcrypt hashes for the validator app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "username", nargs="?", default=None,
        help="Username to add (will prompt for password)")
    parser.add_argument(
        "--new-cookie-key", action="store_true",
        help="Generate a fresh cookie signing key (32 random bytes, hex)")
    args = parser.parse_args(argv)

    if args.new_cookie_key:
        return cmd_new_cookie_key()
    if args.username:
        return cmd_add_user(args.username)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
