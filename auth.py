"""Authentication for Multimodal Studio Hub.

Accounts use a user ID, password, and self-selected role (student or instructor).
No email address, SMTP server, verification code, or email-based password reset is
used. Account records are stored in a local SQLite database.

Use from the main Streamlit app:

    import auth
    user = auth.require_login()
    auth.render_account_sidebar(user)
    # Render the rest of the app here.

Set DATABASE_URL to use a persistent PostgreSQL database. Without it, the app
uses data/users.db as a local SQLite fallback.

IMPORTANT: Never commit database files or DATABASE_URL to Git. Passwords are
stored as salted scrypt hashes, never as plain text. Streamlit Community Cloud
does not guarantee persistence for its local SQLite files.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("AUTH_DB_PATH", str(Path(__file__).resolve().parent / "data" / "users.db")))

def database_url():
    """Read the optional PostgreSQL URL from the environment or Streamlit secrets."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    try:
        return str(st.secrets.get("DATABASE_URL", "")).strip() or None
    except Exception:
        return None


def using_postgres():
    return bool(database_url())


def sql(statement):
    """Translate this module's SQLite-style placeholders for psycopg."""
    return statement.replace("?", "%s") if using_postgres() else statement
ROLES = {"student": "Student", "instructor": "Instructor"}

MIN_USER_ID_LENGTH = 3
MAX_USER_ID_LENGTH = 32
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60

# scrypt parameters. Values are stored in each hash to allow later upgrades.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1

COMMON_PASSWORDS = {
    "password", "password123", "123456789012", "qwerty123456", "letmein12345",
    "welcome12345", "admin123456", "changeme1234", "iloveyou1234",
}

log = logging.getLogger("auth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def md_escape(text):
    """Escape user-provided text before inserting it into Markdown."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$-])", r"\\\1", str(text))


def clean_text(text, limit=80):
    """Remove control characters, collapse whitespace, and cap a display value."""
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def normalize_user_id(user_id):
    """User IDs are case-insensitive and stored in lowercase."""
    return str(user_id or "").strip().lower()


def validate_user_id(user_id):
    """Return an error string, or None when the user ID is acceptable."""
    if not MIN_USER_ID_LENGTH <= len(user_id) <= MAX_USER_ID_LENGTH:
        return f"Choose a user ID between {MIN_USER_ID_LENGTH} and {MAX_USER_ID_LENGTH} characters."
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", user_id):
        return "Use letters, numbers, periods, underscores, or hyphens; start with a letter or number."
    return None


def validate_password(password, user_id=""):
    """Return password problems; an empty list means it is acceptable."""
    errors = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Use at least {MIN_PASSWORD_LENGTH} characters. A passphrase is a good option.")
    if len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"Use no more than {MAX_PASSWORD_LENGTH} characters.")
    if password.lower() in COMMON_PASSWORDS:
        errors.append("That password is too common. Choose a less predictable passphrase.")
    if len(user_id) >= 4 and user_id in password.lower():
        errors.append("Do not include your user ID in your password.")
    return errors


# ---------------------------------------------------------------------------
# Local SQLite database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'instructor')),
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_login REAL
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'instructor')),
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    last_login DOUBLE PRECISION
)
"""


@contextmanager
def db():
    """Open a PostgreSQL connection when configured, otherwise local SQLite."""
    url = database_url()
    if url:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create the account table in the selected database."""
    with db() as conn:
        if database_url():
            conn.execute(POSTGRES_SCHEMA)
        else:
            conn.executescript(SCHEMA)
    if not database_url():
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass


def get_user_by_user_id(user_id):
    with db() as conn:
        return conn.execute(
            sql("SELECT * FROM users WHERE user_id = ?"), (normalize_user_id(user_id),)
        ).fetchone()


def get_user(user_pk):
    with db() as conn:
        return conn.execute(sql("SELECT * FROM users WHERE id = ?"), (user_pk,)).fetchone()


def create_user(user_id, password_hash, role):
    """Create an account; only a salted password hash is stored."""
    try:
        with db() as conn:
            params = (normalize_user_id(user_id), password_hash, role, time.time())
            if database_url():
                row = conn.execute(
                    "INSERT INTO users (user_id, password_hash, role, created_at) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    params,
                ).fetchone()
                return row["id"], None
            cur = conn.execute(
                "INSERT INTO users (user_id, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                params,
            )
            return cur.lastrowid, None
    except Exception as exc:
        integrity_errors = [sqlite3.IntegrityError]
        if database_url():
            try:
                import psycopg
                integrity_errors.append(psycopg.IntegrityError)
            except ImportError:
                pass
        if isinstance(exc, tuple(integrity_errors)):
            return None, "That user ID is already in use. Please choose another."
        raise


def update_user(user_pk, **fields):
    """Update only the account fields used by this module."""
    allowed = {"onboarding_done", "failed_attempts", "locked_until", "last_login", "password_hash"}
    if not fields or not set(fields) <= allowed:
        raise ValueError("Unexpected or empty user update.")
    assignments = ", ".join(f"{column} = ?" for column in fields)
    with db() as conn:
        conn.execute(
            sql(f"UPDATE users SET {assignments} WHERE id = ?"), (*fields.values(), user_pk)
        )


def record_failed_login(user_pk):
    with db() as conn:
        row = conn.execute(
            sql("SELECT failed_attempts FROM users WHERE id = ?"), (user_pk,)
        ).fetchone()
        if not row:
            return
        failures = row["failed_attempts"] + 1
        if failures >= MAX_LOGIN_FAILURES:
            conn.execute(
                sql("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?"),
                (time.time() + LOCKOUT_SECONDS, user_pk),
            )
        else:
            conn.execute(sql("UPDATE users SET failed_attempts = ? WHERE id = ?"), (failures, user_pk))


# ---------------------------------------------------------------------------
# Password hashing and login
# ---------------------------------------------------------------------------
def hash_password(password):
    """Create a salted scrypt hash; the plain-text password is never stored."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        maxmem=256 * 1024 * 1024, dklen=32,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    """Verify a scrypt hash using a constant-time comparison."""
    try:
        _, n, r, p, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p),
            maxmem=256 * 1024 * 1024, dklen=len(hash_hex) // 2,
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError, AttributeError):
        return False


_DUMMY_HASH = None


def _dummy_hash():
    """Do comparable hash work for an unknown user ID during login."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password")
    return _DUMMY_HASH


def authenticate(user_id, password):
    """Return (row, status), with status 'ok', 'invalid', or 'locked'."""
    user = get_user_by_user_id(user_id)
    if not user:
        verify_password(password, _dummy_hash())
        return None, "invalid"
    if user["locked_until"] > time.time():
        return user, "locked"
    if not verify_password(password, user["password_hash"]):
        record_failed_login(user["id"])
        return None, "invalid"
    update_user(user["id"], failed_attempts=0, locked_until=0, last_login=time.time())
    return get_user(user["id"]), "ok"


def public_user(row):
    """Return the account fields needed by the app; never expose password hashes."""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "display_name": row["user_id"],  # Keeps compatibility with existing app/sidebar code.
        "role": row["role"],
        "onboarding_done": bool(row["onboarding_done"]),
    }


def log_in(user_pk):
    """Start an app session for an account and clear signup/login UI state."""
    row = get_user(user_pk)
    for key in ("auth_view", "tutorial_step"):
        st.session_state.pop(key, None)
    st.session_state["user"] = public_user(row)


def logout():
    """Clear the session, return to sign-in, and show a goodbye message."""
    st.session_state.clear()
    # Skip the welcome splash so require_login() can display the goodbye message.
    st.session_state["welcome_splash_shown"] = True
    st.session_state["logout_notice"] = "See you later! 🖖"


def complete_onboarding():
    user = st.session_state["user"]
    update_user(user["id"], onboarding_done=1)
    st.session_state["user"]["onboarding_done"] = True
    st.session_state.pop("tutorial_step", None)


def replay_tutorial():
    """Replay the tutorial in this session without changing the saved completion flag."""
    st.session_state["user"]["onboarding_done"] = False
    st.session_state["tutorial_step"] = 0


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------
def tutorial_steps(user):
    first = md_escape(user["display_name"].split()[0])
    welcome = {
        "title": f"Welcome, {first}", "where": None, "points": [],
        "body": "Multimodal Studio Hub is a library of resources, exemplars, lesson plans, and rubrics "
                "for projects that combine writing, images, sound, and video. This short tour shows you around.",
    }
    resources = {
        "title": "Find multimodal resources", "where": "Search Resources",
        "body": "Search by keyword and narrow the results by genre, such as podcast, infographic, or video essay.",
        "points": ["Try a suggested keyword to get started", "Open View details to see what is included and how to use it"],
    }
    exemplars = {
        "title": "Learn from exemplar projects", "where": "Browse Exemplars",
        "body": "Exemplars are sample projects that show what strong work looks like in each genre.",
        "points": ["Filter by genre and sort the results", "Read the learning objectives before you open a project"],
    }
    lessons = {
        "title": "Plan with lesson plans", "where": "Lesson Plans",
        "body": "Filter ready-to-adapt plans by genre, course level, and class time, then download them.",
        "points": ["Preview objectives, timeline, and materials", "Download one plan or everything you filtered as text files"],
    }
    rubrics = {
        "title": "Grade with rubrics", "where": "Rubrics",
        "body": "Preview a rubric for each genre and download it as a PDF or editable Word document.",
        "points": ["Every rubric totals 100 points", "Edit the Word version to match your assignment"],
    }
    spaces = {
        "title": "Your project space", "where": None,
        "body": "Project spaces are where you will plan, draft, and keep your multimodal projects.",
        "points": ["Start from a genre and a rubric", "Come back to your work any time you log in"],
    }
    done = {
        "title": "You are ready to begin", "where": None, "points": [],
        "body": "You can replay this tour any time from the account section of the sidebar.",
    }
    if user["role"] == "instructor":
        return [welcome, resources, lessons, rubrics, exemplars, spaces, done]
    return [welcome, resources, exemplars, spaces, done]


def render_onboarding(user):
    """Show a short guided tutorial with Back, Next, and Skip controls."""
    steps = tutorial_steps(user)
    index = max(0, min(st.session_state.get("tutorial_step", 0), len(steps) - 1))
    step = steps[index]
    st.progress((index + 1) / len(steps), text=f"Step {index + 1} of {len(steps)}")
    with st.container(border=True):
        st.header(step["title"])
        st.write(step["body"])
        for point in step["points"]:
            st.markdown(f"- {point}")
        if step["where"]:
            st.caption(f"Find it in the sidebar under {step['where']}.")

    def change(delta):
        st.session_state["tutorial_step"] = index + delta

    c1, c2, c3 = st.columns([1, 1, 2])
    c1.button("Back", key="tut_back", on_click=change, args=(-1,), disabled=index == 0)
    if index < len(steps) - 1:
        c2.button("Next", key="tut_next", type="primary", on_click=change, args=(1,))
    else:
        c2.button("Start exploring", key="tut_finish", type="primary", on_click=complete_onboarding)
    c3.button("Skip tutorial", key="tut_skip", on_click=complete_onboarding)
    render_copyright_footer()


def render_copyright_footer():
    """Show the same copyright notice on authentication and onboarding screens."""
    st.markdown(
        '<footer class="site-footer">Copyright &copy; 2026 The Multimodal Studio Hub. All Rights Reserved</footer>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Signup and login screens
# ---------------------------------------------------------------------------
def render_signup_form():
    with st.form("signup_form"):
        user_id = st.text_input(
            "Choose a user ID", key="su_user_id", autocomplete="username",
            help=f"{MIN_USER_ID_LENGTH}–{MAX_USER_ID_LENGTH} characters: letters, numbers, periods, underscores, or hyphens.",
        )
        password = st.text_input("Password", type="password", key="su_password", autocomplete="new-password")
        role_label = st.radio("I am a", list(ROLES.values()), horizontal=True, key="su_role")
        submitted = st.form_submit_button("Create account", type="primary")
    if not submitted:
        return

    user_id = normalize_user_id(user_id)
    errors = []
    user_id_error = validate_user_id(user_id)
    if user_id_error:
        errors.append(user_id_error)
    errors.extend(validate_password(password, user_id))
    if errors:
        for error in errors:
            st.error(error)
        return

    role = "instructor" if role_label == "Instructor" else "student"
    try:
        user_pk, error = create_user(user_id, hash_password(password), role)
    except Exception:
        log.exception("Could not save a new account")
        st.error("We couldn't save your account right now. Please try again later or contact the site administrator.")
        return
    if error:
        st.error(error)
        return
    log_in(user_pk)
    st.rerun()


def render_login_form():
    with st.form("login_form"):
        user_id = st.text_input("User ID", key="li_user_id", autocomplete="username")
        password = st.text_input("Password", type="password", key="li_password", autocomplete="current-password")
        login_col, forgot_col = st.columns(2)
        with login_col:
            submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)
        with forgot_col:
            forgot_clicked = st.form_submit_button("🔑 Forgot Password?", use_container_width=True)

    if forgot_clicked:
        st.session_state["forgot_password_open"] = True
        return
    if not submitted:
        return

    st.session_state["forgot_password_open"] = False
    user, status = authenticate(user_id, password)
    if status == "ok":
        log_in(user["id"])
        st.session_state["login_notice"] = "Welcome Back! 👍"
        st.rerun()
    elif status == "locked":
        minutes = max(1, int((user["locked_until"] - time.time()) // 60) + 1)
        st.error(f"Too many failed attempts. Please try again in about {minutes} minutes. 👎")
    else:
        st.error("Incorrect user ID or password. 👎")


def render_auth_page():
    """Show signup and login tabs with music for signed-out visitors."""
    title = "Let's Get Started with the Multimodal Studio Hub"
    description = (
        "Create an account or log in to reach the resource library, lesson plans, "
        "exemplars, and project spaces."
    )
    account_note = (
        "Accounts use a user ID and password. If you forget your password, "
        "contact the site administrator."
    )

    def typewriter(text):
        """Yield short text chunks for Streamlit's native typewriter rendering."""
        for character in text:
            yield character
            time.sleep(0.012)

    with st.container(key="auth_hero"):
        st.write_stream(typewriter(f"# {title}"))
        st.write_stream(typewriter(description))
        st.write_stream(typewriter(account_note))


    if not database_url():
        st.warning(
            "Account storage is currently local and may reset when the hosted app restarts. "
            "The site administrator must configure DATABASE_URL in Streamlit Secrets for persistent accounts."
        )

    music_path = Path(__file__).resolve().parent / "assets" / "login-signup-music.mp3"
    if music_path.is_file():
        audio_data = base64.b64encode(music_path.read_bytes()).decode("ascii")
        music_html = """
        <div style="display:flex;align-items:center;gap:14px;padding:10px 14px;
                    border:1px solid #ded8eb;border-radius:14px;background:#f8f6fc;
                    font-family:system-ui,sans-serif;color:#24183d;">
          <button id="musicButton" type="button" aria-label="Play welcome music"
                  style="width:48px;height:48px;flex:none;border:0;border-radius:50%;
                         background:#2D1E4F;color:white;font-size:21px;cursor:pointer;
                         box-shadow:0 2px 8px #2d1e4f44;">▶</button>
          <div>
            <div id="musicLabel" style="font-weight:700;">Welcome music</div>
            <div style="font-size:13px;color:#5A5170;">Press play to start · loops while you sign in</div>
          </div>
          <audio id="welcomeAudio" preload="metadata" loop
                 src="data:audio/mpeg;base64,__AUDIO_DATA__"></audio>
        </div>
        <script>
          const audio = document.getElementById("welcomeAudio");
          const button = document.getElementById("musicButton");
          const label = document.getElementById("musicLabel");
          audio.volume = 0.45;
          button.addEventListener("click", async () => {
            if (audio.paused) {
              try {
                await audio.play();
                button.textContent = "Ⅱ";
                button.setAttribute("aria-label", "Pause welcome music");
                label.textContent = "Welcome music is playing";
              } catch (error) {
                label.textContent = "Could not play audio — try again";
              }
            } else {
              audio.pause();
              button.textContent = "▶";
              button.setAttribute("aria-label", "Play welcome music");
              label.textContent = "Welcome music";
            }
          });
        </script>
        """.replace("__AUDIO_DATA__", audio_data)
        components.html(music_html, height=78, scrolling=False)
    else:
        st.warning("Welcome music is unavailable right now.")

    tab_login, tab_signup = st.tabs(["Log in", "Sign up"])
    with tab_login:
        render_login_form()
        if st.session_state.get("forgot_password_open", False):
            st.info(
                "Password resets are handled by the site administrator. "
                "Use the contact button below to request a reset."
            )
            st.link_button(
                "✉️ Contact the Site Administrator",
                "mailto:ewuoso@iastate.edu?subject=Multimodal%20Studio%20Hub%20password%20reset",
                help="Email ewuoso@iastate.edu for account or password help.",
            )
    with tab_signup:
        render_signup_form()

    render_copyright_footer()


# ---------------------------------------------------------------------------
# Public entry points used by the main app
# ---------------------------------------------------------------------------
def current_user():
    """Return the signed-in user's safe account details, or None."""
    return st.session_state.get("user")


def is_instructor(user):
    """Return whether the account selected the instructor role."""
    return bool(user) and user.get("role") == "instructor"


def has_instructor_access(user):
    """Role check for instructor-only features; instructor status is self-selected at signup."""
    return is_instructor(user)


def role_label(user):
    return ROLES.get(user.get("role"), "Unknown role")


def require_login():
    """Require an account and finish the first-login tutorial before returning the user."""
    try:
        init_db()
    except Exception:
        log.exception("Could not initialize the account database")
        st.error("Account storage is unavailable. Please try again later or contact the site administrator.")
        st.stop()
    user = current_user()
    notice = st.session_state.pop("login_notice", None)
    if notice:
        st.success(notice)
    logout_notice = st.session_state.pop("logout_notice", None)
    if logout_notice:
        st.success(logout_notice)
    if not user:
        render_auth_page()
        st.stop()
    if not user["onboarding_done"]:
        render_onboarding(user)
        st.stop()
    return user


def render_account_sidebar(user):
    """Show the signed-in user, tutorial replay, and logout controls in the sidebar."""
    with st.sidebar:
        st.divider()
        st.markdown(f"**{md_escape(user['display_name'])}**")
        st.caption(role_label(user))
        st.button("Replay tutorial", key="acct_replay", on_click=replay_tutorial)
        st.button("Log out", key="acct_logout", on_click=logout)
