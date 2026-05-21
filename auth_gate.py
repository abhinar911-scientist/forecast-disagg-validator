"""
Authentication gate for the Forecast Disaggregation Validator.

Design
------
- Users defined in `.streamlit/secrets.toml` as username → bcrypt hash.
- On every Streamlit run, `require_login()` checks session state.
  If not authenticated, it renders a login form and calls `st.stop()`.
- Bcrypt is used for password verification (industry standard, slow-by-design,
  automatic salt).
- Session-scoped lockout: after N failed attempts from the same browser session,
  the form locks for a cooldown period. This is best-effort defense in depth —
  on a public ngrok URL we can't reliably tie attempts to a real IP, so this
  is per-session.

What this gate intentionally does NOT do:
- It does not implement true OAuth flows (Google sign-in, etc).
- It does not persist login across browser tabs / restarts.
- It does not implement role-based access (all authenticated users have full app).
- It does not implement password reset (you regenerate hashes via add_user.py).

These omissions are documented in README.md.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Defaults — overridable from secrets.toml [auth] section
# ---------------------------------------------------------------------------
DEFAULT_SESSION_HOURS = 8
DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_MINUTES = 15


# ---------------------------------------------------------------------------
# Secrets access — graceful when secrets.toml is missing or malformed
# ---------------------------------------------------------------------------
def _get_auth_config() -> dict:
    """Read the [auth] section from secrets. Returns an empty config if
    secrets aren't available (which causes login to fail closed — no one
    can sign in until secrets.toml is set up)."""
    try:
        # st.secrets raises if secrets.toml is missing entirely
        auth = st.secrets.get("auth", {})
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError) as e:  # type: ignore
        return {"_error": f"secrets.toml not found: {e}"}
    except Exception as e:
        return {"_error": f"could not read secrets.toml: {e}"}

    if not auth:
        return {"_error": "secrets.toml is missing the [auth] section"}

    users = auth.get("users", {})
    if not users:
        return {"_error": "secrets.toml [auth.users] is empty — no users defined"}

    return {
        "users": dict(users),  # cast away the MappingProxy-like wrapper
        "session_hours": int(auth.get("session_hours", DEFAULT_SESSION_HOURS)),
        "max_failed_attempts": int(auth.get("max_failed_attempts",
                                            DEFAULT_MAX_FAILED_ATTEMPTS)),
        "lockout_minutes": int(auth.get("lockout_minutes",
                                        DEFAULT_LOCKOUT_MINUTES)),
    }


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def _init_auth_state():
    """Make sure all the auth keys exist in session state with sensible defaults."""
    defaults = {
        "authenticated": False,
        "auth_username": None,
        "auth_login_time": None,
        "auth_failed_attempts": 0,
        "auth_lockout_until": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def is_authenticated() -> bool:
    """True if the current session is authenticated AND the session hasn't
    expired."""
    _init_auth_state()
    if not st.session_state.authenticated:
        return False

    # Check session age
    cfg = _get_auth_config()
    if "_error" in cfg:
        # Can't check age, fail closed
        return False

    login_time = st.session_state.auth_login_time
    if login_time is None:
        return False
    age = datetime.now() - login_time
    if age > timedelta(hours=cfg["session_hours"]):
        # Session expired — clear state
        _clear_session()
        return False

    return True


def _clear_session():
    """Reset auth state. Used on logout and on session expiry."""
    st.session_state.authenticated = False
    st.session_state.auth_username = None
    st.session_state.auth_login_time = None
    # Note: we intentionally do NOT clear failed_attempts/lockout here.
    # Those persist across logout to make repeated probing harder.


# ---------------------------------------------------------------------------
# Password verification
# ---------------------------------------------------------------------------
def _verify_password(password: str, stored_hash: str) -> bool:
    """Return True iff bcrypt confirms the password matches the hash.
    Always returns False on any error (fail closed)."""
    if not BCRYPT_AVAILABLE:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              stored_hash.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Lockout logic
# ---------------------------------------------------------------------------
def _is_locked_out() -> tuple[bool, Optional[datetime]]:
    """Return (locked, unlock_time)."""
    lockout_until = st.session_state.get("auth_lockout_until")
    if lockout_until is None:
        return False, None
    if datetime.now() >= lockout_until:
        # Lockout expired — reset attempts so user can try again with a clean slate
        st.session_state.auth_lockout_until = None
        st.session_state.auth_failed_attempts = 0
        return False, None
    return True, lockout_until


def _record_failed_attempt(cfg: dict):
    """Bump failed-attempt counter. If we hit the limit, set a lockout."""
    st.session_state.auth_failed_attempts += 1
    if st.session_state.auth_failed_attempts >= cfg["max_failed_attempts"]:
        st.session_state.auth_lockout_until = (
            datetime.now() + timedelta(minutes=cfg["lockout_minutes"]))


def _record_successful_login(username: str):
    st.session_state.authenticated = True
    st.session_state.auth_username = username
    st.session_state.auth_login_time = datetime.now()
    st.session_state.auth_failed_attempts = 0
    st.session_state.auth_lockout_until = None


# ---------------------------------------------------------------------------
# UI — login form
# ---------------------------------------------------------------------------
def _render_login_form(cfg: dict):
    """Render the login form. Sets session state on success and triggers
    a rerun. Otherwise displays an inline error."""
    # Page heading
    st.markdown("""
    <div style='text-align:center; padding:40px 0 20px 0;'>
      <h1 style='color:#1F3864; margin-bottom:8px;'>📊 Forecast Disaggregation Validator</h1>
      <p style='color:#595959; font-style:italic; margin:0;'>Please sign in to continue.</p>
    </div>
    """, unsafe_allow_html=True)

    # If locked, show that and skip the form
    locked, unlock_time = _is_locked_out()
    if locked:
        remaining = unlock_time - datetime.now()
        mins = int(remaining.total_seconds() // 60) + 1
        # Center column for the lockout message too
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            st.error(f"🔒 Too many failed attempts. Try again in **{mins} minute(s)**.")
        st.stop()

    # Center the login form using columns
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", key="auth_form_username",
                                     autocomplete="username")
            password = st.text_input("Password", type="password",
                                     key="auth_form_password",
                                     autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary",
                                              use_container_width=True)

        if submitted:
            # Always sleep a small amount to throttle attempts and reduce
            # timing-attack surface area
            time.sleep(0.3)

            if not username or not password:
                st.error("Enter both username and password.")
                st.stop()

            users = cfg["users"]
            stored_hash = users.get(username)

            # Use a constant-time-ish flow: always run verify even if the user
            # doesn't exist, to avoid leaking which usernames are valid via
            # response timing.
            if stored_hash is None:
                # Run a dummy verify so the timing is similar
                _verify_password(password,
                                 "$2b$12$abcdefghijklmnopqrstuv0123456789012345678901234567890")
                ok = False
            else:
                ok = _verify_password(password, stored_hash)

            if ok:
                _record_successful_login(username)
                st.rerun()
            else:
                _record_failed_attempt(cfg)
                remaining = cfg["max_failed_attempts"] - st.session_state.auth_failed_attempts
                if remaining > 0:
                    st.error(f"Invalid username or password. "
                             f"{remaining} attempt(s) remaining before lockout.")
                else:
                    st.error(f"🔒 Too many failed attempts. "
                             f"Locked out for {cfg['lockout_minutes']} minute(s).")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def require_login():
    """Call this at the very top of app.py, BEFORE rendering anything else.
    If the session is not authenticated, this renders the login form and
    halts the rest of the script via st.stop().

    If secrets.toml is missing or misconfigured, shows a clear configuration
    error to the operator and halts.
    """
    _init_auth_state()

    if is_authenticated():
        return  # already logged in — proceed with the app

    cfg = _get_auth_config()
    if "_error" in cfg:
        st.error(
            f"🔒 **Authentication is not configured.**\n\n"
            f"`{cfg['_error']}`\n\n"
            "An administrator needs to set up `.streamlit/secrets.toml`. "
            "See `README.md → Authentication setup` for the format. "
            "You can generate a password hash with `python add_user.py <username>`.")
        st.stop()

    if not BCRYPT_AVAILABLE:
        st.error("🔒 **Authentication library missing.**\n\n"
                 "The `bcrypt` package is not installed. Install it with "
                 "`pip install bcrypt>=4.0.0` and restart the app.")
        st.stop()

    _render_login_form(cfg)
    # If we got here without st.rerun(), the form is rendered. Halt the rest
    # of the script.
    st.stop()


def render_user_sidebar():
    """Render 'Signed in as X' + Logout button in the sidebar. Call this after
    require_login() succeeds, somewhere at the top of the sidebar block.
    """
    if not is_authenticated():
        return
    user = st.session_state.auth_username
    cfg = _get_auth_config()
    if "_error" not in cfg:
        # Show session expiry as a small caption
        login_time = st.session_state.auth_login_time
        if login_time:
            expires_at = login_time + timedelta(hours=cfg["session_hours"])
            mins_left = int((expires_at - datetime.now()).total_seconds() // 60)
            expiry_caption = f"Session expires in ~{mins_left} min"
        else:
            expiry_caption = ""
    else:
        expiry_caption = ""

    with st.sidebar:
        st.markdown(f"**👤 Signed in as:** `{user}`")
        if expiry_caption:
            st.caption(expiry_caption)
        if st.button("Sign out", key="auth_logout_btn",
                     help="End your session and return to the login screen"):
            _clear_session()
            st.rerun()
        st.markdown("---")
