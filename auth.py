"""
auth.py: accounts for Multimodal Studio Hub

Features
  - Sign up with an institutional or personal email, then verify it with a 6-digit code
  - Log in, log out, and reset a forgotten password
  - Two roles (student, instructor); instructors on personal emails stay "pending review"
  - Guided onboarding tutorial, shown once and replayable
  - Passwords stored only as salted scrypt hashes; SQLite storage with parameterized queries

How to use it in your main file
    import auth
    user = auth.require_login()        # shows sign up / log in / tutorial until the user is in
    auth.render_account_sidebar(user)  # name, role, replay tutorial, log out
    # ...the rest of your app runs only for signed-in users

IMPORTANT before launch
  - Streamlit Community Cloud wipes local files on restart, so a SQLite file there will lose accounts.
    Point DB_PATH at persistent storage, or swap the functions in section 3 for a hosted database.
  - Put email (SMTP) settings in .streamlit/secrets.toml, never in this file or in GitHub.
  - Keep the auth_data/ folder and secrets.toml out of GitHub (.gitignore).

File layout
  1. Settings          2. Small helpers        3. Database          4. Passwords and validation
  5. Verification codes and email              6. Account actions   7. Onboarding content
  8. Screens (Streamlit)                       9. Public entry points
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# 1. SETTINGS
# ---------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("AUTH_DB_PATH", "auth_data/users.db"))

ROLES = {"student": "Student", "instructor": "Instructor"}

# Email endings treated as institutional. Edit this list for the schools you expect.
INSTITUTIONAL_SUFFIXES = (".edu", ".ac.uk", ".edu.au", ".ac.nz", ".edu.sg")

MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 20
MAX_LOGIN_FAILURES = 5            # wrong passwords allowed before a temporary lock
LOCKOUT_SECONDS = 15 * 60
CODE_TTL_SECONDS = 15 * 60        # how long an emailed code stays valid
CODE_MAX_ATTEMPTS = 5             # wrong guesses allowed per code
RESEND_COOLDOWN_SECONDS = 60

# scrypt cost settings (stored inside each hash, so you can raise them later)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1

# A tiny starter list; production sites should check a larger breached-password list
COMMON_PASSWORDS = {
    "password", "password1", "password123", "1234567890", "12345678910", "qwertyuiop", "qwerty12345",
    "letmein123", "iloveyou123", "welcome123", "admin12345", "changeme123", "abc1234567",
}

log = logging.getLogger("auth")


# ---------------------------------------------------------------------------
# 2. SMALL HELPERS
# ---------------------------------------------------------------------------
def md_escape(text):
    """Escape characters that Streamlit's markdown would treat as formatting (for user-supplied text)."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$-])", r"\\\1", str(text))


def clean_text(text, limit):
    """Trim, drop control characters, collapse spaces, and cap the length."""
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def normalize_email(email):
    """Emails are compared in lowercase with no surrounding spaces."""
    return str(email or "").strip().lower()


def _setting(section, key, default=None):
    """Read a value from .streamlit/secrets.toml, or return the default if it is not set."""
    try:
        return st.secrets[section][key]
    except Exception:
        return default


def dev_mode():
    """Developer mode shows verification codes on screen. Never turn it on for a public site."""
    return bool(_setting("auth", "dev_mode", False)) or os.environ.get("AUTH_DEV_MODE") == "1"


# ---------------------------------------------------------------------------
# 3. DATABASE (SQLite). Everything that touches storage lives in this section,
#    so it is the only part to replace if you move to a hosted database.
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'instructor')),
    institution TEXT NOT NULL DEFAULT '',
    email_kind TEXT NOT NULL CHECK (email_kind IN ('institutional', 'personal')),
    instructor_status TEXT NOT NULL DEFAULT 'not_applicable'
        CHECK (instructor_status IN ('not_applicable', 'verified', 'pending')),
    verified INTEGER NOT NULL DEFAULT 0,
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_login REAL
);
CREATE TABLE IF NOT EXISTS codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify', 'reset')),
    code_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0
);
"""


@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create the tables if they do not exist yet and restrict the file to its owner."""
    with db() as conn:
        conn.executescript(SCHEMA)
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def get_user_by_email(email):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()


def get_user(user_id):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def save_unverified_user(email, password_hash, name, role, institution, email_kind, instructor_status):
    """
    Create an account, or overwrite an UNVERIFIED one for the same email. Overwriting means someone who
    pre-registers another person's address cannot keep control of it: the real owner signs up, verifies,
    and replaces the details.
    """
    now = time.time()
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ? AND verified = 0", (email,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_hash=?, display_name=?, role=?, institution=?, email_kind=?, "
                "instructor_status=?, failed_attempts=0, locked_until=0, created_at=? WHERE id=?",
                (password_hash, name, role, institution, email_kind, instructor_status, now, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, display_name, role, institution, email_kind, "
            "instructor_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (email, password_hash, name, role, institution, email_kind, instructor_status, now),
        )
        return cur.lastrowid


def update_user(user_id, **fields):
    """Update a few known columns (names come from this file, values are parameterized)."""
    allowed = {"verified", "onboarding_done", "failed_attempts", "locked_until", "last_login", "password_hash"}
    assert set(fields) <= allowed, "unexpected column"
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))


def record_failed_login(user_id):
    """Count a wrong password; after MAX_LOGIN_FAILURES, lock the account for a while."""
    with db() as conn:
        n = conn.execute("SELECT failed_attempts FROM users WHERE id = ?", (user_id,)).fetchone()["failed_attempts"] + 1
        if n >= MAX_LOGIN_FAILURES:
            conn.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                         (time.time() + LOCKOUT_SECONDS, user_id))
        else:
            conn.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (n, user_id))


# ---------------------------------------------------------------------------
# 4. PASSWORDS AND VALIDATION
# ---------------------------------------------------------------------------
def hash_password(password):
    """Salted scrypt hash, stored as 'scrypt$n$r$p$salt$hash'. The plain password is never saved."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=256 * 1024 * 1024, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    """Recompute the hash with the stored settings and compare in constant time."""
    try:
        _, n, r, p, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p),
                                maxmem=256 * 1024 * 1024, dklen=len(hash_hex) // 2)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = None


def _dummy_hash():
    """A throwaway hash, checked when an email is unknown so the response time does not give it away."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password")
    return _DUMMY_HASH


def validate_email(email):
    """Return an error message, or None if the address looks valid."""
    if not email or len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return "Please enter a valid email address."
    return None


def validate_password(password, email, confirm=None):
    """Return a list of problems (empty if the password is acceptable). Length matters more than symbols."""
    errors = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Use at least {MIN_PASSWORD_LENGTH} characters. A long passphrase works well.")
    if len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"Use no more than {MAX_PASSWORD_LENGTH} characters.")
    if password.lower() in COMMON_PASSWORDS:
        errors.append("That password is too common. Choose something harder to guess.")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        errors.append("Do not include your email name in your password.")
    if confirm is not None and password != confirm:
        errors.append("The two passwords do not match.")
    return errors


def classify_email(email):
    """'institutional' if the domain ends with one of INSTITUTIONAL_SUFFIXES, otherwise 'personal'."""
    domain = email.rsplit("@", 1)[-1]
    return "institutional" if domain.endswith(INSTITUTIONAL_SUFFIXES) else "personal"


# ---------------------------------------------------------------------------
# 5. VERIFICATION CODES AND EMAIL
# ---------------------------------------------------------------------------
def _hash_code(code, salt):
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def issue_code(user_id, purpose):
    """Make a new 6-digit code (older unused codes stop working) and return it. Only a hash is stored."""
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    now = time.time()
    with db() as conn:
        conn.execute("UPDATE codes SET used = 1 WHERE user_id = ? AND purpose = ?", (user_id, purpose))
        conn.execute(
            "INSERT INTO codes (user_id, purpose, code_hash, salt, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, purpose, _hash_code(code, salt), salt, now, now + CODE_TTL_SECONDS),
        )
    return code


def seconds_until_resend(user_id, purpose):
    """How long the user must wait before another code can be sent (0 if they can ask now)."""
    with db() as conn:
        row = conn.execute("SELECT created_at FROM codes WHERE user_id = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
                           (user_id, purpose)).fetchone()
    return max(0, int(RESEND_COOLDOWN_SECONDS - (time.time() - row["created_at"]))) if row else 0


def check_code(user_id, purpose, code):
    """Check a submitted code. Returns (ok, message). Limits guesses and respects the expiry time."""
    code = re.sub(r"\D", "", str(code or ""))
    with db() as conn:
        row = conn.execute("SELECT * FROM codes WHERE user_id = ? AND purpose = ? AND used = 0 ORDER BY id DESC LIMIT 1",
                           (user_id, purpose)).fetchone()
        if not row:
            return False, "That code is no longer valid. Please request a new one."
        if row["expires_at"] < time.time():
            return False, "That code has expired. Please request a new one."
        if row["attempts"] >= CODE_MAX_ATTEMPTS:
            return False, "Too many incorrect tries. Please request a new code."
        if not hmac.compare_digest(_hash_code(code, row["salt"]), row["code_hash"]):
            conn.execute("UPDATE codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
            return False, "That code is not correct. Check your email and try again."
        conn.execute("UPDATE codes SET used = 1 WHERE id = ?", (row["id"],))
    return True, ""


def send_email(to_addr, subject, body):
    """Send a plain-text email through the SMTP server in secrets.toml. Returns True if it was sent."""
    host = _setting("smtp", "host")
    if not host:
        return False
    try:
        msg = EmailMessage()
        msg["From"] = _setting("smtp", "sender", _setting("smtp", "username", ""))
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(_setting("smtp", "port", 587)), timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(_setting("smtp", "username", ""), _setting("smtp", "password", ""))
            server.send_message(msg)
        return True
    except Exception:
        log.exception("Could not send email")  # details go to the server log, never to the user
        return False


def send_verification(user, purpose):
    """Issue a code and deliver it. Returns True if a code is on its way (or was sent a moment ago)."""
    if seconds_until_resend(user["id"], purpose) > 0:
        return True
    code = issue_code(user["id"], purpose)
    what = "verify your email" if purpose == "verify" else "reset your password"
    body = (f"Hello {user['display_name']},\n\nYour Multimodal Studio Hub code to {what} is: {code}\n\n"
            f"It expires in {CODE_TTL_SECONDS // 60} minutes. If you did not ask for this, you can ignore this email.")
    if send_email(user["email"], f"Your Multimodal Studio Hub code: {code}", body):
        return True
    if dev_mode():
        st.session_state["dev_code"] = code  # shown on screen only in developer mode
        return True
    return False


# ---------------------------------------------------------------------------
# 6. ACCOUNT ACTIONS (log in, session, log out, onboarding flags)
# ---------------------------------------------------------------------------
def public_user(row):
    """The safe subset of a user record kept in the session (never the password hash)."""
    keys = ("id", "email", "display_name", "role", "institution", "email_kind", "instructor_status")
    data = {k: row[k] for k in keys}
    data["onboarding_done"] = bool(row["onboarding_done"])
    return data


def authenticate(email, password):
    """
    Check credentials. Returns (user_row, status), where status is 'ok', 'invalid', 'locked', or 'unverified'.
    Unknown emails and wrong passwords both return 'invalid' so the form does not reveal which accounts exist.
    """
    user = get_user_by_email(email)
    if not user:
        verify_password(password, _dummy_hash())
        return None, "invalid"
    if user["locked_until"] > time.time():
        return user, "locked"
    if not verify_password(password, user["password_hash"]):
        record_failed_login(user["id"])
        return None, "invalid"
    update_user(user["id"], failed_attempts=0, locked_until=0, last_login=time.time())
    return user, ("ok" if user["verified"] else "unverified")


def log_in(user_id):
    """Start a session for this user and clear any sign-up screens."""
    row = get_user(user_id)
    for key in ("auth_view", "auth_email", "dev_code", "tutorial_step"):
        st.session_state.pop(key, None)
    st.session_state["user"] = public_user(row)


def logout():
    """Button callback: wipe everything held in this browser session."""
    st.session_state.clear()


def complete_onboarding():
    user = st.session_state["user"]
    update_user(user["id"], onboarding_done=1)
    st.session_state["user"]["onboarding_done"] = True
    st.session_state.pop("tutorial_step", None)


def replay_tutorial():
    """Show the tour again for this session only; the saved 'finished' flag stays, so it will not reappear at next login."""
    st.session_state["user"]["onboarding_done"] = False
    st.session_state["tutorial_step"] = 0


def go(view, email=None):
    """Switch which account screen is showing: None (tabs), 'verify', 'reset_request', or 'reset_confirm'."""
    st.session_state["auth_view"] = view
    st.session_state["auth_email"] = email


# ---------------------------------------------------------------------------
# 7. ONBOARDING CONTENT. Edit the wording as your features are built.
# ---------------------------------------------------------------------------
def tutorial_steps(user):
    """Return the tutorial steps for this user's role."""
    first = md_escape(user["display_name"].split()[0])
    welcome = {"title": f"Welcome, {first}", "where": None, "points": [],
               "body": "Multimodal Studio Hub is a library of resources, exemplars, lesson plans, and rubrics for projects "
                       "that combine writing, images, sound, and video. This short tour shows you around."}
    resources = {"title": "Find multimodal resources", "where": "Search Resources",
                 "body": "Search by keyword and narrow the results by genre, such as podcast, infographic, or video essay.",
                 "points": ["Try a suggested keyword to get started", "Open View details to see what is included and how to use it"]}
    exemplars = {"title": "Learn from exemplar projects", "where": "Browse Exemplars",
                 "body": "Exemplars are sample projects that show what strong work looks like in each genre.",
                 "points": ["Filter by genre and sort the results", "Read the learning objectives before you open a project"]}
    lessons = {"title": "Plan with lesson plans", "where": "Lesson Plans",
               "body": "Filter ready-to-adapt plans by genre, course level, and class time, then download them.",
               "points": ["Preview objectives, timeline, and materials", "Download one plan, or everything you filtered, as text files"]}
    rubrics = {"title": "Grade with rubrics", "where": "Rubrics",
               "body": "Preview a rubric for each genre and download it as a PDF or an editable Word document.",
               "points": ["Every rubric totals 100 points", "Edit the Word version to match your assignment"]}
    spaces = {"title": "Your project space", "where": None,
              "body": "Project spaces are where you will plan, draft, and keep your multimodal projects.",
              "points": ["Start from a genre and a rubric", "Come back to your work any time you log in"]}
    done = {"title": "You are ready to begin", "where": None, "points": [],
            "body": "You can replay this tour any time from the account section of the sidebar."}
    if user["role"] == "instructor":
        if user["instructor_status"] == "pending":
            done["points"] = ["Your instructor access is pending review because you registered with a personal email. "
                              "Signing up with your institutional email lets us confirm it faster."]
        return [welcome, resources, lessons, rubrics, exemplars, spaces, done]
    return [welcome, resources, exemplars, spaces, done]


# ---------------------------------------------------------------------------
# 8. SCREENS (Streamlit)
# ---------------------------------------------------------------------------
def _show_dev_code():
    """In developer mode only: show the code that would have been emailed."""
    if dev_mode() and st.session_state.get("dev_code"):
        st.info(f"Developer mode: your code is {st.session_state['dev_code']}. "
                "This appears only because developer mode is on; turn it off before launch.")


def render_signup_form():
    with st.form("signup_form"):
        name = st.text_input("Full name", key="su_name", autocomplete="name")
        email = st.text_input("Email address", key="su_email", autocomplete="email",
                              help="Use your institutional or your personal email.")
        role_label = st.radio("I am a", list(ROLES.values()), horizontal=True, key="su_role")
        institution = st.text_input("Institution (optional)", key="su_institution", autocomplete="organization")
        password = st.text_input("Password", type="password", key="su_password", autocomplete="new-password",
                                 help=f"At least {MIN_PASSWORD_LENGTH} characters. A long passphrase works well.")
        confirm = st.text_input("Confirm password", type="password", key="su_confirm", autocomplete="new-password")
        # Replace this sentence with links to your real privacy notice and terms.
        agreed = st.checkbox("I have read the privacy notice and agree to the terms of use.", key="su_agree")
        submitted = st.form_submit_button("Create account", type="primary")
    if not submitted:
        return

    name, institution, email = clean_text(name, 60), clean_text(institution, 100), normalize_email(email)
    errors = []
    if len(name) < 2:
        errors.append("Please enter your full name.")
    if validate_email(email):
        errors.append(validate_email(email))
    errors += validate_password(password, email, confirm)
    if not agreed:
        errors.append("Please accept the privacy notice and terms to continue.")
    if errors:
        for message in errors:
            st.error(message)
        return

    existing = get_user_by_email(email)
    if existing and existing["verified"]:
        st.error("An account with this email already exists. Please log in instead.")
        return

    role = "instructor" if role_label == "Instructor" else "student"
    email_kind = classify_email(email)
    status = "not_applicable" if role == "student" else ("verified" if email_kind == "institutional" else "pending")
    user_id = save_unverified_user(email, hash_password(password), name, role, institution, email_kind, status)
    if send_verification(get_user(user_id), "verify"):
        go("verify", email)
        st.rerun()
    st.error("We could not send the verification email. Please try again later.")


def render_login_form():
    with st.form("login_form"):
        email = st.text_input("Email address", key="li_email", autocomplete="email")
        password = st.text_input("Password", type="password", key="li_password", autocomplete="current-password")
        submitted = st.form_submit_button("Log in", type="primary")
    st.button("Forgot your password?", key="li_forgot", on_click=go, args=("reset_request",))
    if not submitted:
        return

    user, status = authenticate(email, password)
    if status == "ok":
        log_in(user["id"])
        st.rerun()
    elif status == "unverified":
        # Correct password but the email was never confirmed: send a fresh code and continue verification
        if send_verification(user, "verify"):
            go("verify", user["email"])
            st.rerun()
        st.error("We could not send the verification email. Please try again later.")
    elif status == "locked":
        minutes = max(1, int((user["locked_until"] - time.time()) // 60) + 1)
        st.error(f"Too many failed attempts. Please try again in about {minutes} minutes, or reset your password.")
    else:
        st.error("Incorrect email or password.")  # same message whether the email exists or not


def render_verify_view():
    email = st.session_state.get("auth_email")
    user = get_user_by_email(email) if email else None
    if not user:
        go(None)
        st.rerun()
    st.subheader("Check your email")
    st.write(f"We sent a 6-digit code to **{md_escape(email)}**. It expires in {CODE_TTL_SECONDS // 60} minutes.")
    _show_dev_code()
    with st.form("verify_form"):
        code = st.text_input("Verification code", key="vf_code", max_chars=6, autocomplete="one-time-code")
        submitted = st.form_submit_button("Verify and continue", type="primary")
    if submitted:
        ok, message = check_code(user["id"], "verify", code)
        if ok:
            update_user(user["id"], verified=1)
            log_in(user["id"])  # verified accounts go straight in (and on to the tutorial)
            st.rerun()
        st.error(message)
    c1, c2 = st.columns(2)
    if c1.button("Resend code", key="vf_resend"):
        wait = seconds_until_resend(user["id"], "verify")
        if wait > 0:
            st.info(f"Please wait {wait} seconds before asking for another code.")
        elif send_verification(user, "verify"):
            st.success("A new code is on its way.")
            _show_dev_code()
        else:
            st.error("We could not send the email. Please try again later.")
    if c2.button("Use a different email", key="vf_back"):
        go(None)
        st.rerun()


def render_reset_request():
    st.subheader("Reset your password")
    with st.form("reset_request_form"):
        email = normalize_email(st.text_input("Email address", key="rr_email", autocomplete="email"))
        submitted = st.form_submit_button("Send reset code", type="primary")
    if st.button("Back to log in", key="rr_back"):
        go(None)
        st.rerun()
    if submitted:
        if validate_email(email):
            st.error(validate_email(email))
            return
        user = get_user_by_email(email)
        if user and user["verified"]:
            send_verification(user, "reset")
        go("reset_confirm", email)  # same next screen whether or not the account exists
        st.rerun()


def render_reset_confirm():
    email = st.session_state.get("auth_email", "")
    st.subheader("Choose a new password")
    st.write(f"If an account exists for **{md_escape(email)}**, we sent a 6-digit code to it.")
    _show_dev_code()
    with st.form("reset_confirm_form"):
        code = st.text_input("Code from the email", key="rs_code", max_chars=6, autocomplete="one-time-code")
        new = st.text_input("New password", type="password", key="rs_new", autocomplete="new-password")
        confirm = st.text_input("Confirm new password", type="password", key="rs_confirm", autocomplete="new-password")
        submitted = st.form_submit_button("Update password", type="primary")
    if st.button("Back to log in", key="rc_back"):
        go(None)
        st.rerun()
    if not submitted:
        return
    errors = validate_password(new, email, confirm)
    if errors:
        for message in errors:
            st.error(message)
        return
    user = get_user_by_email(email)
    ok, message = (False, "That code is not valid. Please request a new one.") if not (user and user["verified"]) \
        else check_code(user["id"], "reset", code)
    if not ok:
        st.error(message)
        return
    update_user(user["id"], password_hash=hash_password(new), failed_attempts=0, locked_until=0)
    st.session_state["auth_flash"] = ("success", "Your password was updated. Please log in.")
    st.session_state.pop("dev_code", None)
    go(None)
    st.rerun()


def render_auth_page():
    """Everything a signed-out visitor sees: tabs for log in and sign up, plus the verify and reset screens."""
    st.title("Welcome to Multimodal Studio Hub")
    st.write("Create a free account or log in to reach the resource library, lesson plans, exemplars, and project spaces.")
    if dev_mode():
        st.warning("Developer mode is on: verification codes are shown on screen. Turn it off before launch.")
    flash = st.session_state.pop("auth_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    view = st.session_state.get("auth_view")
    if view == "verify":
        render_verify_view()
    elif view == "reset_request":
        render_reset_request()
    elif view == "reset_confirm":
        render_reset_confirm()
    else:
        tab_login, tab_signup = st.tabs(["Log in", "Sign up"])
        with tab_login:
            render_login_form()
        with tab_signup:
            render_signup_form()


def render_onboarding(user):
    """Guided tutorial: one step at a time, with Back, Next, and Skip."""
    steps = tutorial_steps(user)
    i = max(0, min(st.session_state.get("tutorial_step", 0), len(steps) - 1))
    step = steps[i]
    st.progress((i + 1) / len(steps), text=f"Step {i + 1} of {len(steps)}")
    with st.container(border=True):
        st.header(step["title"])
        st.write(step["body"])
        for point in step["points"]:
            st.markdown(f"- {point}")
        if step["where"]:
            st.caption(f"Find it in the sidebar under {step['where']}.")

    def change(delta):
        st.session_state["tutorial_step"] = i + delta

    c1, c2, c3 = st.columns([1, 1, 2])
    c1.button("Back", key="tut_back", on_click=change, args=(-1,), disabled=(i == 0))
    if i < len(steps) - 1:
        c2.button("Next", key="tut_next", type="primary", on_click=change, args=(1,))
    else:
        c2.button("Start exploring", key="tut_finish", type="primary", on_click=complete_onboarding)
    c3.button("Skip tutorial", key="tut_skip", on_click=complete_onboarding)


# ---------------------------------------------------------------------------
# 9. PUBLIC ENTRY POINTS (what your main file calls)
# ---------------------------------------------------------------------------
def current_user():
    """The signed-in user's details, or None."""
    return st.session_state.get("user")


def is_instructor(user):
    return bool(user) and user["role"] == "instructor"


def has_instructor_access(user):
    """
    True only for instructors whose institutional email was confirmed (use this to gate instructor tools).
    Caution: students also have institutional emails, so this proves affiliation, not that someone teaches.
    Before unlocking anything sensitive (for example, answer keys), add an approval step: an admin screen that
    sets instructor_status, or single sign-on from your institution.
    """
    return is_instructor(user) and user["instructor_status"] == "verified"


def role_label(user):
    if user["role"] == "student":
        return "Student"
    return "Instructor" if user["instructor_status"] == "verified" else "Instructor (pending review)"


def require_login():
    """
    Call this near the top of your app. Signed-out visitors see the sign up / log in screens, new users see the
    tutorial, and the script stops until they are done. Returns the user once they can use the app.
    """
    init_db()
    user = current_user()
    if not user:
        render_auth_page()
        st.stop()
    if not user["onboarding_done"]:
        render_onboarding(user)
        st.stop()
    return user


def render_account_sidebar(user):
    """Account block for the sidebar: name, role, replay tutorial, log out."""
    with st.sidebar:
        st.divider()
        st.markdown(f"**{md_escape(user['display_name'])}**")
        st.caption(role_label(user))
        st.button("Replay tutorial", key="acct_replay", on_click=replay_tutorial)
        st.button("Log out", key="acct_logout", on_click=logout)
