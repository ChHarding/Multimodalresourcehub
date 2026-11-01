"""
projects.py: Project Spaces for Multimodal Studio Hub (v1 skeleton)

What it does
  - Teams build a multimodal page from "blocks" (heading, text, image, video, chart), asynchronously
  - Four permission levels: View, Comment, Edit, Manage
  - Share Project dialog: revocable invite links (role + expiry) and one public read-only link
  - Viewer mode: a View or public link opens only the finished page, with no login and no editing tools
  - Overwrite protection: opening a block to edit marks it "in use" for 5 minutes, and saves check a version number
  - Comments, an activity log, and per-member contribution totals

It reuses auth.py for accounts and for the database connection (auth.db()), so it needs no new packages.

How to use it in your main file
    import projects
    projects.handle_shared_link()          # before auth.require_login(): View links render and stop here
    user = auth.require_login()
    projects.redeem_pending_share(user)    # after login: Comment/Edit links add the user to the project
    ...
    projects.render_projects_page(user)    # the body of your "Project Space" sidebar page

Before launch
  - Use persistent storage (see auth.py): free hosting wipes local files, which would delete every project.
  - Set [app] base_url in .streamlit/secrets.toml so share links include your site address.
  - Images and videos are web links only in v1 (no file hosting).

File layout
  1. Settings        2. Database          3. Small helpers      4. Projects and members
  5. Blocks          6. Comments, activity, contributions       7. Share links
  8. Rendering       9. Screens           10. Public entry points
"""

import io
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

import auth

# ---------------------------------------------------------------------------
# 1. SETTINGS
# ---------------------------------------------------------------------------
ROLES = ["view", "comment", "edit", "manage"]  # lowest to highest
ROLE_LABELS = {"view": "View", "comment": "Comment", "edit": "Edit", "manage": "Manage"}
ROLE_HELP = {
    "view": "You can read the page, comments, and activity.",
    "comment": "You can also leave comments.",
    "edit": "You can also add, edit, move, and delete blocks.",
    "manage": "You can also share the project and manage the team.",
}
LINK_ROLES = ["view", "comment", "edit"]  # links never grant Manage; managers assign that in the Team tab
BLOCK_KINDS = {"heading": "Heading", "text": "Text", "image": "Image", "video": "Video", "chart": "Chart"}
ACTION_LABELS = {
    "created_project": "Created the project", "added_block": "Added a block", "edited_block": "Edited a block",
    "deleted_block": "Deleted a block", "moved_block": "Moved a block", "commented": "Posted a comment",
    "created_link": "Created an invite link", "enabled_public_link": "Turned on the public link",
    "revoked_link": "Revoked a link", "added_member": "Added a member", "changed_role": "Changed a role",
    "removed_member": "Removed a member", "joined_via_link": "Joined through a link",
}

LOCK_SECONDS = 5 * 60       # how long a block stays "in use" after someone opens it
LIVE_SECONDS = 10           # refresh interval for live updates
MAX_TITLE, MAX_TEXT, MAX_COMMENT, MAX_CSV, MAX_ROWS, MAX_COLS = 100, 5000, 1000, 100_000, 500, 8


# ---------------------------------------------------------------------------
# 2. DATABASE (same SQLite file as accounts; swap auth.db() if you move to a hosted database)
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner_id INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('view', 'comment', 'edit', 'manage')),
    added_at REAL NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('heading', 'text', 'image', 'video', 'chart')),
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    locked_by INTEGER REFERENCES users(id),
    locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    block_id INTEGER REFERENCES blocks(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS share_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('view', 'comment', 'edit')),
    kind TEXT NOT NULL CHECK (kind IN ('invite', 'public')),
    created_by INTEGER REFERENCES users(id),
    created_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0
);
"""


def _execute(conn, statement, params=()):
    """Run SQL using the placeholder style for the configured auth database."""
    return conn.execute(auth.sql(statement), params)


def init_db():
    """Create project tables in the same SQLite or PostgreSQL database as accounts."""
    auth.init_db()
    postgres = auth.using_postgres()
    schema = SCHEMA
    if postgres:
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        schema = re.sub(r"\bINTEGER(?=(?: NOT NULL)? REFERENCES)", "BIGINT", schema)
    with auth.db() as conn:
        if not postgres:
            _execute(conn, "PRAGMA foreign_keys = ON")
        for statement in schema.split(";"):
            if statement.strip():
                _execute(conn, statement)


def _log(conn, project_id, user_id, action, detail=""):
    """Add one line to the activity log, inside the caller's transaction."""
    _execute(conn, "INSERT INTO activity (project_id, user_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                 (project_id, user_id, action, detail[:200], time.time()))


# ---------------------------------------------------------------------------
# 3. SMALL HELPERS
# ---------------------------------------------------------------------------
def fmt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""

def configured_base_url():
    """Read the app base URL from Streamlit secrets or the environment."""
    try:
        app_settings = st.secrets.get("app", {})
        value = app_settings.get("base_url", "") if hasattr(app_settings, "get") else ""
    except Exception:
        value = ""
    return str(value or os.environ.get("APP_BASE_URL", "")).rstrip("/")


def can(role, needed):
    """True if this role is at least as powerful as the one needed."""
    return role in ROLES and ROLES.index(role) >= ROLES.index(needed)


def get_role(project_id, user_id):
    with auth.db() as conn:
        row = _execute(conn, "SELECT role FROM members WHERE project_id = ? AND user_id = ?", (project_id, user_id)).fetchone()
    return row["role"] if row else None


def _require(project_id, user, needed):
    """Server-side permission check used by every action that changes data."""
    if not user or not can(get_role(project_id, user["id"]), needed):
        raise PermissionError(f"You need {ROLE_LABELS[needed]} access to do that.")


@contextmanager
def guard():
    """Show a friendly message instead of an error if a permission check fails."""
    try:
        yield
    except PermissionError as err:
        st.error(str(err))


def _multiline(text, limit):
    """Trim and cap text but keep line breaks."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text or "")).strip()[:limit]


def _valid_url(url):
    """Only web links are allowed (never file paths), so a block cannot read files from the server."""
    try:
        parts = urlparse(str(url or "").strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc) and len(str(url)) <= 500


def block_label(kind, content):
    text = content.get("text") or content.get("alt") or content.get("caption") or content.get("url") or ""
    text = re.sub(r"\s+", " ", text).strip()[:50]
    return f"{BLOCK_KINDS[kind]}: {text}" if text else BLOCK_KINDS[kind]


def chart_frame(csv_text):
    """Parse pasted or uploaded CSV into a numeric table: first column = labels, other columns = numbers."""
    df = pd.read_csv(io.StringIO(csv_text))
    if df.shape[1] < 2 or df.empty:
        raise ValueError("need at least two columns and one row")
    df = df.iloc[:MAX_ROWS, :MAX_COLS]
    labels = df.columns[0]
    nums = df.drop(columns=labels).apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    if nums.empty:
        raise ValueError("no numeric columns")
    nums.index = df[labels].astype(str)
    return nums


# ---------------------------------------------------------------------------
# 4. PROJECTS AND MEMBERS
# ---------------------------------------------------------------------------
def create_project(user, title, description):
    now = time.time()
    with auth.db() as conn:
        values = (title, description, user["id"], now)
        if auth.using_postgres():
            row = _execute(conn, "INSERT INTO projects (title, description, owner_id, created_at) VALUES (?, ?, ?, ?) RETURNING id", values).fetchone()
            pid = row["id"]
        else:
            pid = _execute(conn, "INSERT INTO projects (title, description, owner_id, created_at) VALUES (?, ?, ?, ?)", values).lastrowid
        _execute(conn, "INSERT INTO members (project_id, user_id, role, added_at) VALUES (?, ?, 'manage', ?)", (pid, user["id"], now))
        _log(conn, pid, user["id"], "created_project", title)
    return pid


def get_project(project_id):
    with auth.db() as conn:
        return _execute(conn, "SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def list_projects(user_id):
    with auth.db() as conn:
        return _execute(conn, 
            "SELECT p.*, m.role, (SELECT COUNT(*) FROM members WHERE project_id = p.id) AS member_count, "
            "(SELECT MAX(created_at) FROM activity WHERE project_id = p.id) AS last_active "
            "FROM projects p JOIN members m ON m.project_id = p.id WHERE m.user_id = ? "
            "ORDER BY COALESCE((SELECT MAX(a2.created_at) FROM activity a2 WHERE a2.project_id = p.id), p.created_at) DESC",
            (user_id,)).fetchall()


def list_members(project_id):
    with auth.db() as conn:
        return _execute(conn, 
            "SELECT m.user_id, m.role, u.user_id AS display_name, (p.owner_id = m.user_id) AS is_owner "
            "FROM members m JOIN users u ON u.id = m.user_id JOIN projects p ON p.id = m.project_id "
            "WHERE m.project_id = ? ORDER BY m.added_at", (project_id,)).fetchall()


def _manager_count(conn, project_id):
    return _execute(conn, "SELECT COUNT(*) AS manager_count FROM members WHERE project_id = ? AND role = 'manage'", (project_id,)).fetchone()["manager_count"]


def add_member_by_user_id(project_id, actor, user_id, role):
    """Add an existing account by its user ID. Returns (ok, message)."""
    _require(project_id, actor, "manage")
    user = auth.get_user_by_user_id(user_id)
    if role not in ROLES or not user:
        return False, "No account found for that user ID. Ask them to sign up first, or share an invite link."
    with auth.db() as conn:
        if _execute(conn, "SELECT 1 FROM members WHERE project_id = ? AND user_id = ?", (project_id, user["id"])).fetchone():
            return False, "That person is already on the team."
        _execute(conn, "INSERT INTO members (project_id, user_id, role, added_at) VALUES (?, ?, ?, ?)", (project_id, user["id"], role, time.time()))
        display_name = user["user_id"]
        _log(conn, project_id, actor["id"], "added_member", f"{display_name} as {ROLE_LABELS[role]}")
    return True, f"Added {display_name} with {ROLE_LABELS[role]} access."


def set_member_role(project_id, actor, user_id, role):
    _require(project_id, actor, "manage")
    with auth.db() as conn:
        row = _execute(conn, "SELECT m.role, u.user_id AS display_name FROM members m JOIN users u ON u.id = m.user_id "
                           "WHERE m.project_id = ? AND m.user_id = ?", (project_id, user_id)).fetchone()
        if not row or role not in ROLES:
            return False, "Member not found."
        if row["role"] == "manage" and role != "manage" and _manager_count(conn, project_id) <= 1:
            return False, "A project needs at least one manager."
        _execute(conn, "UPDATE members SET role = ? WHERE project_id = ? AND user_id = ?", (role, project_id, user_id))
        _log(conn, project_id, actor["id"], "changed_role", f"{row['display_name']} to {ROLE_LABELS[role]}")
    return True, "Role updated."


def remove_member(project_id, actor, user_id):
    _require(project_id, actor, "manage")
    with auth.db() as conn:
        row = _execute(conn, "SELECT m.role, u.user_id AS display_name FROM members m JOIN users u ON u.id = m.user_id "
                           "WHERE m.project_id = ? AND m.user_id = ?", (project_id, user_id)).fetchone()
        if not row:
            return False, "Member not found."
        if row["role"] == "manage" and _manager_count(conn, project_id) <= 1:
            return False, "A project needs at least one manager."
        _execute(conn, "DELETE FROM members WHERE project_id = ? AND user_id = ?", (project_id, user_id))
        _execute(conn, "UPDATE blocks SET locked_by = NULL, locked_until = 0 WHERE project_id = ? AND locked_by = ?", (project_id, user_id))
        _log(conn, project_id, actor["id"], "removed_member", row["display_name"])
    return True, "Member removed."


# ---------------------------------------------------------------------------
# 5. BLOCKS (with overwrite protection)
# ---------------------------------------------------------------------------
def list_blocks(project_id):
    with auth.db() as conn:
        return _execute(conn, "SELECT b.*, u.user_id AS locker FROM blocks b LEFT JOIN users u ON u.id = b.locked_by "
                            "WHERE b.project_id = ? ORDER BY b.position, b.id", (project_id,)).fetchall()


def add_block(project_id, user, kind, content):
    _require(project_id, user, "edit")
    now = time.time()
    with auth.db() as conn:
        pos = _execute(conn, "SELECT COALESCE(MAX(position), 0) + 1 AS next_position FROM blocks WHERE project_id = ?", (project_id,)).fetchone()["next_position"]
        _execute(conn, "INSERT INTO blocks (project_id, position, kind, content, created_by, updated_by, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (project_id, pos, kind, json.dumps(content), user["id"], user["id"], now, now))
        _log(conn, project_id, user["id"], "added_block", block_label(kind, content))


def acquire_lock(project_id, block_id, user):
    """
    Mark a block "in use" by this user. One UPDATE decides the winner, so two people clicking at the same moment
    cannot both get the lock. The lock is ours, free, or expired; otherwise this returns False.
    """
    _require(project_id, user, "edit")
    now = time.time()
    with auth.db() as conn:
        cur = _execute(conn, "UPDATE blocks SET locked_by = ?, locked_until = ? WHERE id = ? AND project_id = ? "
                           "AND (locked_by IS NULL OR locked_by = ? OR locked_until < ?)",
                           (user["id"], now + LOCK_SECONDS, block_id, project_id, user["id"], now))
        return cur.rowcount == 1


def release_lock(project_id, block_id, user):
    with auth.db() as conn:
        _execute(conn, "UPDATE blocks SET locked_by = NULL, locked_until = 0 WHERE id = ? AND project_id = ? AND locked_by = ?",
                     (block_id, project_id, user["id"]))


def _locked_by_other(row, user):
    return row["locked_by"] is not None and row["locked_by"] != user["id"] and row["locked_until"] > time.time()


def update_block(project_id, block_id, user, content, expected_version):
    """Save an edit unless someone else holds the lock or changed the block since it was opened."""
    _require(project_id, user, "edit")
    with auth.db() as conn:
        row = _execute(conn, "SELECT * FROM blocks WHERE id = ? AND project_id = ?", (block_id, project_id)).fetchone()
        if not row:
            return False, "That block no longer exists."
        if _locked_by_other(row, user):
            return False, "Someone else is editing this block right now."
        if row["version"] != expected_version:
            return False, "Someone changed this block while you were editing. Cancel, then reopen it to see the latest version."
        _execute(conn, "UPDATE blocks SET content = ?, version = version + 1, updated_by = ?, updated_at = ?, "
                     "locked_by = NULL, locked_until = 0 WHERE id = ?", (json.dumps(content), user["id"], time.time(), block_id))
        _log(conn, project_id, user["id"], "edited_block", block_label(row["kind"], content))
    return True, ""


def delete_block(project_id, block_id, user):
    _require(project_id, user, "edit")
    with auth.db() as conn:
        row = _execute(conn, "SELECT * FROM blocks WHERE id = ? AND project_id = ?", (block_id, project_id)).fetchone()
        if not row:
            return False, "That block no longer exists."
        if _locked_by_other(row, user):
            return False, "Someone else is editing this block right now."
        _execute(conn, "DELETE FROM blocks WHERE id = ?", (block_id,))
        _log(conn, project_id, user["id"], "deleted_block", block_label(row["kind"], json.loads(row["content"])))
    return True, ""


def move_block(project_id, block_id, user, direction):
    """Swap a block with its neighbor (direction -1 = up, +1 = down)."""
    _require(project_id, user, "edit")
    with auth.db() as conn:
        row = _execute(conn, "SELECT * FROM blocks WHERE id = ? AND project_id = ?", (block_id, project_id)).fetchone()
        if not row:
            return
        op, order = ("<", "DESC") if direction < 0 else (">", "ASC")
        other = _execute(conn, f"SELECT id, position FROM blocks WHERE project_id = ? AND position {op} ? ORDER BY position {order} LIMIT 1",
                             (project_id, row["position"])).fetchone()
        if other:
            _execute(conn, "UPDATE blocks SET position = ? WHERE id = ?", (other["position"], block_id))
            _execute(conn, "UPDATE blocks SET position = ? WHERE id = ?", (row["position"], other["id"]))
            _log(conn, project_id, user["id"], "moved_block", block_label(row["kind"], json.loads(row["content"])))


# ---------------------------------------------------------------------------
# 6. COMMENTS, ACTIVITY, CONTRIBUTIONS
# ---------------------------------------------------------------------------
def add_comment(project_id, user, body, block_id=None):
    _require(project_id, user, "comment")
    body = _multiline(body, MAX_COMMENT)
    if not body:
        return False
    with auth.db() as conn:
        if block_id is not None and not _execute(conn, "SELECT 1 FROM blocks WHERE id = ? AND project_id = ?", (block_id, project_id)).fetchone():
            block_id = None
        _execute(conn, "INSERT INTO comments (project_id, block_id, user_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
                     (project_id, block_id, user["id"], body, time.time()))
        _log(conn, project_id, user["id"], "commented", body[:60])
    return True


def list_comments(project_id):
    with auth.db() as conn:
        return _execute(conn, "SELECT c.*, u.user_id AS display_name, b.kind AS bkind, b.content AS bcontent FROM comments c "
                            "JOIN users u ON u.id = c.user_id LEFT JOIN blocks b ON b.id = c.block_id "
                            "WHERE c.project_id = ? ORDER BY c.created_at DESC", (project_id,)).fetchall()


def list_activity(project_id, limit=100):
    with auth.db() as conn:
        return _execute(conn, "SELECT a.*, u.user_id AS display_name FROM activity a LEFT JOIN users u ON u.id = a.user_id "
                            "WHERE a.project_id = ? ORDER BY a.created_at DESC, a.id DESC LIMIT ?", (project_id, limit)).fetchall()


def contribution_totals(project_id):
    """One row per current member: blocks added, blocks edited, comments, total logged actions, last activity."""
    with auth.db() as conn:
        return _execute(conn, 
            "SELECT u.user_id AS display_name, m.role, "
            "COALESCE(SUM(CASE WHEN a.action = 'added_block' THEN 1 ELSE 0 END), 0) AS added, "
            "COALESCE(SUM(CASE WHEN a.action = 'edited_block' THEN 1 ELSE 0 END), 0) AS edited, "
            "COALESCE(SUM(CASE WHEN a.action = 'commented' THEN 1 ELSE 0 END), 0) AS comments, "
            "COUNT(a.id) AS total, MAX(a.created_at) AS last_active "
            "FROM members m JOIN users u ON u.id = m.user_id "
            "LEFT JOIN activity a ON a.user_id = m.user_id AND a.project_id = m.project_id "
            "WHERE m.project_id = ? GROUP BY m.user_id, u.user_id, m.role ORDER BY total DESC, u.user_id", (project_id,)).fetchall()


# ---------------------------------------------------------------------------
# 7. SHARE LINKS (revocable; the token in the web address is the secret)
# ---------------------------------------------------------------------------
def create_link(project_id, user, role, expires_at=None, kind="invite"):
    """Make a share link and return its token. Public links are View-only, never expire, and replace the old one."""
    _require(project_id, user, "manage")
    if kind == "public":
        role, expires_at = "view", None
    if role not in LINK_ROLES:
        raise ValueError("Links can grant View, Comment, or Edit only.")
    token = secrets.token_urlsafe(24)
    with auth.db() as conn:
        if kind == "public":
            _execute(conn, "UPDATE share_links SET revoked = 1 WHERE project_id = ? AND kind = 'public'", (project_id,))
        _execute(conn, "INSERT INTO share_links (project_id, token, role, kind, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (project_id, token, role, kind, user["id"], time.time(), expires_at))
        _log(conn, project_id, user["id"], "enabled_public_link" if kind == "public" else "created_link",
             "" if kind == "public" else f"{ROLE_LABELS[role]} link, expires {fmt(expires_at)}")
    return token


def revoke_link(project_id, user, link_id):
    _require(project_id, user, "manage")
    with auth.db() as conn:
        cur = _execute(conn, "UPDATE share_links SET revoked = 1 WHERE id = ? AND project_id = ? AND revoked = 0", (link_id, project_id))
        if cur.rowcount:
            _log(conn, project_id, user["id"], "revoked_link")


def list_links(project_id):
    """Active links only (not revoked, not expired)."""
    with auth.db() as conn:
        return _execute(conn, "SELECT l.*, u.user_id AS display_name FROM share_links l LEFT JOIN users u ON u.id = l.created_by "
                            "WHERE l.project_id = ? AND l.revoked = 0 AND (l.expires_at IS NULL OR l.expires_at > ?) "
                            "ORDER BY l.created_at DESC", (project_id, time.time())).fetchall()


def resolve_link(token):
    """Return the link row if the token is valid right now, else None."""
    if not isinstance(token, str) or not 10 <= len(token) <= 100:
        return None
    with auth.db() as conn:
        return _execute(conn, "SELECT l.*, p.title FROM share_links l JOIN projects p ON p.id = l.project_id "
                            "WHERE l.token = ? AND l.revoked = 0 AND (l.expires_at IS NULL OR l.expires_at > ?)",
                            (token, time.time())).fetchone()


def redeem_link(user, token):
    """Comment/Edit links: add the signed-in user to the project (never lowering an existing role). Returns the project id."""
    link = resolve_link(token)
    if not link or link["role"] not in ("comment", "edit"):
        return None
    pid, now = link["project_id"], time.time()
    with auth.db() as conn:
        row = _execute(conn, "SELECT role FROM members WHERE project_id = ? AND user_id = ?", (pid, user["id"])).fetchone()
        if not row:
            _execute(conn, "INSERT INTO members (project_id, user_id, role, added_at) VALUES (?, ?, ?, ?)", (pid, user["id"], link["role"], now))
        elif not can(row["role"], link["role"]):
            _execute(conn, "UPDATE members SET role = ? WHERE project_id = ? AND user_id = ?", (link["role"], pid, user["id"]))
        else:
            return pid  # already has equal or higher access
        _log(conn, pid, user["id"], "joined_via_link", ROLE_LABELS[link["role"]])
    return pid


def share_url(token):
    base = configured_base_url()
    return f"{base}/?share={token}" if base else f"?share={token}"


# ---------------------------------------------------------------------------
# 8. RENDERING THE PAGE (the same code draws the preview and the viewer mode)
# ---------------------------------------------------------------------------
def render_block(block, h=3):
    """Draw one block. All web links are re-checked here, and text is shown as Markdown without raw HTML."""
    c, kind = json.loads(block["content"]), block["kind"]
    if kind == "heading":
        st.markdown("#" * h + " " + auth.md_escape(c.get("text", "")))
    elif kind == "text":
        st.markdown(c.get("text", ""))
    elif kind == "image" and _valid_url(c.get("url")):
        st.image(c["url"], caption=c.get("alt") or None)
    elif kind == "video" and _valid_url(c.get("url")):
        st.video(c["url"])
        if c.get("caption"):
            st.caption(c["caption"])
    elif kind == "chart":
        try:
            df = chart_frame(c.get("csv", ""))
            (st.line_chart if c.get("chart") == "line" else st.bar_chart)(df)
            if c.get("caption"):
                st.caption(c["caption"])
            with st.expander("View the chart data as a table"):  # a text alternative to the chart
                st.dataframe(df)
        except Exception:
            st.warning("This chart's data could not be displayed.")
    else:
        st.warning("This block could not be displayed.")


def render_blocks(project_id, h=3):
    blocks = list_blocks(project_id)
    if not blocks:
        st.info("This page has no content yet.")
    for b in blocks:
        render_block(b, h)


# ---------------------------------------------------------------------------
# 9. SCREENS
# ---------------------------------------------------------------------------
def _open(project_id):
    """Button callback: open a project (or go back to the list with None)."""
    st.session_state["open_project"] = project_id
    st.session_state.pop("welcome", None)


def _live(fn, live):
    """Wrap a function so it re-runs by itself every few seconds when live updates are on."""
    return st.fragment(run_every=LIVE_SECONDS if live else None)(fn)


def render_page_tab(project_id):
    project = get_project(project_id)
    if project:
        if project["description"]:
            st.write(project["description"])
        render_blocks(project_id, h=3)


def block_fields(kind, v, prefix):
    """The input fields for one block type. Returns the raw values; clean_content checks them."""
    raw = {}
    if kind == "heading":
        raw["text"] = st.text_input("Heading text", value=v.get("text", ""), max_chars=120, key=f"{prefix}_text")
    elif kind == "text":
        raw["text"] = st.text_area("Text (Markdown allowed)", value=v.get("text", ""), max_chars=MAX_TEXT, height=200, key=f"{prefix}_text")
    elif kind == "image":
        raw["url"] = st.text_input("Image web address", value=v.get("url", ""), help="A link that starts with https://", key=f"{prefix}_url")
        raw["alt"] = st.text_input("Alt text (describe the image for people who cannot see it)", value=v.get("alt", ""), max_chars=200, key=f"{prefix}_alt")
    elif kind == "video":
        raw["url"] = st.text_input("Video web address (for example a YouTube link)", value=v.get("url", ""), key=f"{prefix}_url")
        raw["caption"] = st.text_input("Caption (optional)", value=v.get("caption", ""), max_chars=200, key=f"{prefix}_caption")
    elif kind == "chart":
        raw["chart"] = st.selectbox("Chart type", ["bar", "line"], index=1 if v.get("chart") == "line" else 0, key=f"{prefix}_chart")
        raw["upload"] = st.file_uploader("Upload a CSV file (optional)", type=["csv"], key=f"{prefix}_upload")
        raw["csv"] = st.text_area("Or paste CSV data (first column = labels, other columns = numbers)", value=v.get("csv", ""), height=160, key=f"{prefix}_csv")
        raw["caption"] = st.text_input("Caption (optional)", value=v.get("caption", ""), max_chars=200, key=f"{prefix}_caption")
    return raw


def clean_content(kind, raw):
    """Validate the raw form values. Returns (content_dict, None) or (None, error_message)."""
    if kind == "heading":
        text = auth.clean_text(raw.get("text"), 120)
        return ({"text": text}, None) if text else (None, "Please enter a heading.")
    if kind == "text":
        text = _multiline(raw.get("text"), MAX_TEXT)
        return ({"text": text}, None) if text else (None, "Please enter some text.")
    if kind in ("image", "video"):
        url = str(raw.get("url") or "").strip()
        if not _valid_url(url):
            return None, "Please enter a web address that starts with http:// or https://."
        if kind == "image":
            alt = auth.clean_text(raw.get("alt"), 200)
            return ({"url": url, "alt": alt}, None) if alt else (None, "Please add alt text that describes the image.")
        return {"url": url, "caption": auth.clean_text(raw.get("caption"), 200)}, None
    if kind == "chart":
        upload = raw.get("upload")
        csv = (upload.getvalue().decode("utf-8-sig", "replace") if upload else str(raw.get("csv") or "")).strip()
        if not csv or len(csv.encode()) > MAX_CSV:
            return None, "Please paste or upload CSV data (up to 100 KB)."
        try:
            chart_frame(csv)
        except Exception:
            return None, "Could not read the chart data. Use a header row, labels in the first column, and numbers in the other columns."
        return {"csv": csv, "chart": raw.get("chart") if raw.get("chart") in ("bar", "line") else "bar",
                "caption": auth.clean_text(raw.get("caption"), 200)}, None
    return None, "Unknown block type."


def render_edit_form(project_id, user, block):
    """Edit one block. The block is marked in use while the form is open."""
    bid, ekey, vkey = block["id"], f"editing_{project_id}", f"editver_{block['id']}"
    if not acquire_lock(project_id, bid, user):
        st.warning("Someone else is now editing this block, so you cannot save changes to it.")
        st.session_state.pop(ekey, None)
        return
    st.session_state.setdefault(vkey, block["version"])  # the version we started from
    with st.form(f"edit_form_{bid}"):
        raw = block_fields(block["kind"], json.loads(block["content"]), f"edit_{bid}")
        c1, c2 = st.columns(2)
        save = c1.form_submit_button("Save changes", type="primary")
        cancel = c2.form_submit_button("Cancel")
    if cancel:
        release_lock(project_id, bid, user)
        st.session_state.pop(ekey, None)
        st.session_state.pop(vkey, None)
        st.rerun()
    if save:
        content, error = clean_content(block["kind"], raw)
        if error:
            st.error(error)
            return
        with guard():
            ok, message = update_block(project_id, bid, user, content, st.session_state[vkey])
            if ok:
                st.session_state.pop(ekey, None)
                st.session_state.pop(vkey, None)
                st.rerun()
            st.error(message)


def render_edit_tab(project, user):
    pid = project["id"]
    ekey = f"editing_{pid}"

    st.subheader("Add a block")
    n = st.session_state.setdefault(f"addn_{pid}", 0)  # changing n gives the form fresh, empty fields
    kind = st.selectbox("Block type", list(BLOCK_KINDS), format_func=BLOCK_KINDS.get, key=f"newkind_{pid}")
    with st.form(f"add_form_{pid}"):
        raw = block_fields(kind, {}, f"add_{pid}_{n}_{kind}")
        submitted = st.form_submit_button("Add block", type="primary")
    if submitted:
        content, error = clean_content(kind, raw)
        if error:
            st.error(error)
        else:
            with guard():
                add_block(pid, user, kind, content)
                st.session_state[f"addn_{pid}"] = n + 1
                st.rerun()

    st.subheader("Blocks")
    blocks = list_blocks(pid)
    if not blocks:
        st.info("No blocks yet. Add the first one above.")
    for i, b in enumerate(blocks):
        bid = b["id"]
        with st.container(border=True, key=f"card_block_{bid}"):
            st.caption(f"Block {i + 1}: {BLOCK_KINDS[b['kind']]}")
            if st.session_state.get(ekey) == bid:
                render_edit_form(pid, user, b)
                continue
            render_block(b, h=3)
            if _locked_by_other(b, user):
                st.caption(f"In use by {b['locker']} until {fmt(b['locked_until'])}. Try again in a few minutes.")
            busy = _locked_by_other(b, user)
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Edit", key=f"edit_{bid}", disabled=busy):
                with guard():
                    if acquire_lock(pid, bid, user):
                        st.session_state[ekey] = bid
                        st.session_state[f"editver_{bid}"] = b["version"]
                        st.rerun()
                    st.warning("Someone else just opened this block.")
            with guard():
                if c2.button("Move up", key=f"up_{bid}", disabled=(i == 0)):
                    move_block(pid, bid, user, -1)
                    st.rerun()
                if c3.button("Move down", key=f"down_{bid}", disabled=(i == len(blocks) - 1)):
                    move_block(pid, bid, user, 1)
                    st.rerun()
            if st.session_state.get(f"confirm_del_{bid}"):
                st.warning("Delete this block? This cannot be undone.")
                d1, d2 = st.columns(2)
                if d1.button("Yes, delete", key=f"delyes_{bid}", type="primary"):
                    with guard():
                        ok, message = delete_block(pid, bid, user)
                        st.session_state.pop(f"confirm_del_{bid}", None)
                        if not ok:
                            st.error(message)
                        else:
                            st.rerun()
                if d2.button("Keep it", key=f"delno_{bid}"):
                    st.session_state.pop(f"confirm_del_{bid}", None)
                    st.rerun()
            elif c4.button("Delete", key=f"del_{bid}", disabled=busy):
                st.session_state[f"confirm_del_{bid}"] = True
                st.rerun()


def render_comment_list(project_id):
    comments = list_comments(project_id)
    if not comments:
        st.info("No comments yet.")
    for c in comments:
        with st.container(border=True, key=f"card_comment_{c['id']}"):
            about = f" on {block_label(c['bkind'], json.loads(c['bcontent']))}" if c["bkind"] else ""
            st.caption(f"{c['display_name']}{about}, {fmt(c['created_at'])}")
            st.markdown(auth.md_escape(c["body"]))


def render_comments_tab(project, user, role):
    pid = project["id"]
    if can(role, "comment"):
        blocks = list_blocks(pid)
        with st.form(f"comment_form_{pid}", clear_on_submit=True):
            about = st.selectbox("About", [None] + [b["id"] for b in blocks], key=f"cm_about_{pid}",
                                 format_func=lambda x: "The whole project" if x is None else block_label(
                                     next(b["kind"] for b in blocks if b["id"] == x), json.loads(next(b["content"] for b in blocks if b["id"] == x))))
            body = st.text_area("Your comment", max_chars=MAX_COMMENT, key=f"cm_body_{pid}")
            sent = st.form_submit_button("Post comment", type="primary")
        if sent:
            with guard():
                if add_comment(pid, user, body, about):
                    st.rerun()
                st.error("Please write a comment first.")
    else:
        st.info("You have View access. Ask a manager for Comment access to join the discussion.")
    return render_comment_list


def render_team_tab(project, user):
    pid = project["id"]
    st.subheader("Team")
    for m in list_members(pid):
        uid = m["user_id"]
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.markdown(f"**{auth.md_escape(m['display_name'])}**" + (" (owner)" if m["is_owner"] else ""))
        new_role = c2.selectbox("Role", ROLES, index=ROLES.index(m["role"]), format_func=ROLE_LABELS.get, key=f"role_{pid}_{uid}",
                                label_visibility="collapsed")
        with guard():
            if new_role != m["role"]:
                ok, message = set_member_role(pid, user, uid, new_role)
                (st.success if ok else st.error)(message)
                if ok:
                    st.rerun()
            if c3.button("Remove", key=f"rm_{pid}_{uid}"):
                ok, message = remove_member(pid, user, uid)
                if ok:
                    st.rerun()
                st.error(message)
    with st.form(f"add_member_{pid}", clear_on_submit=True):
        member_user_id = st.text_input("Add a classmate by user ID (they need an account)", key=f"am_user_id_{pid}")
        role = st.selectbox("Role", ROLES, index=2, format_func=ROLE_LABELS.get, key=f"am_role_{pid}")
        added = st.form_submit_button("Add to team")
    if added:
        with guard():
            ok, message = add_member_by_user_id(pid, user, auth.normalize_user_id(member_user_id), role)
            (st.success if ok else st.error)(message)
            if ok:
                st.rerun()

    st.subheader("Links")
    if not configured_base_url():
        st.caption("Tip: set base_url under [app] in secrets.toml so links include your site address.")
    links = list_links(pid)
    if not links:
        st.info("No active links. Use Share Project to create one.")
    for link in links:
        what = "Public read-only link" if link["kind"] == "public" else f"{ROLE_LABELS[link['role']]} invite link"
        expiry = "no expiry" if link["expires_at"] is None else f"expires {fmt(link['expires_at'])}"
        with st.container(border=True, key=f"card_link_{link['id']}"):
            st.markdown(f"**{what}**, {expiry}")
            st.caption(f"Created by {link['display_name'] or 'unknown'} on {fmt(link['created_at'])}")
            st.code(share_url(link["token"]), language=None)
            with guard():
                if st.button("Revoke this link", key=f"revoke_{link['id']}"):
                    revoke_link(pid, user, link["id"])
                    st.rerun()


def render_activity(project_id):
    st.subheader("Contributions by member")
    totals = contribution_totals(project_id)
    st.dataframe(pd.DataFrame([{"Member": t["display_name"], "Role": ROLE_LABELS[t["role"]], "Blocks added": t["added"],
                                "Blocks edited": t["edited"], "Comments": t["comments"], "Total actions": t["total"],
                                "Last active": fmt(t["last_active"])} for t in totals]), hide_index=True)
    st.subheader("Activity log")
    log = list_activity(project_id)
    if not log:
        st.info("Nothing has happened yet.")
        return
    st.dataframe(pd.DataFrame([{"When": fmt(a["created_at"]), "Who": a["display_name"] or "Unknown",
                                "What": ACTION_LABELS.get(a["action"], a["action"]), "Detail": a["detail"]} for a in log]),
                 hide_index=True)


@st.dialog("Share project")
def share_dialog(project_id):
    """Create a revocable invite link (role + expiry) or turn on the public read-only link."""
    user = auth.current_user()
    if not user or not can(get_role(project_id, user["id"]), "manage"):
        st.error("Only managers can share a project.")
        return
    st.markdown("**Invite link**")
    role = st.selectbox("Permission", LINK_ROLES, format_func=lambda r: f"{ROLE_LABELS[r]}: {ROLE_HELP[r]}", key="sd_role")
    today = date.today()
    expiry = st.date_input("Link expires on", value=today + timedelta(days=14), min_value=today + timedelta(days=1),
                           max_value=today + timedelta(days=90), key="sd_expiry")
    if st.button("Create invite link", type="primary", key="sd_create"):
        end_of_day = datetime.combine(expiry, dtime(23, 59, 59), tzinfo=timezone.utc).timestamp()
        st.session_state["sd_last"] = create_link(project_id, user, role, end_of_day)
    if st.session_state.get("sd_last"):
        st.code(share_url(st.session_state["sd_last"]), language=None)
        st.caption("Send this link to classmates. View links open the page without an account; Comment and Edit links ask people to log in first.")
    st.divider()
    st.markdown("**Public read-only link**")
    st.caption("For people outside your class, such as community partners. Anyone with this link can view the page.")
    if st.button("Create or replace the public link", key="sd_public"):
        st.session_state["sd_public_token"] = create_link(project_id, user, "view", kind="public")
    if st.session_state.get("sd_public_token"):
        st.code(share_url(st.session_state["sd_public_token"]), language=None)


def render_project(project, role, user):
    pid = project["id"]
    st.button("Back to all projects", key=f"back_{pid}", on_click=_open, args=(None,))
    c1, c2 = st.columns([4, 1])
    c1.header(auth.md_escape(project["title"]))
    if can(role, "manage") and c2.button("Share Project", type="primary", key=f"share_{pid}"):
        st.session_state.pop("sd_last", None)
        st.session_state.pop("sd_public_token", None)
        share_dialog(pid)
    if st.session_state.get("welcome") == pid:  # onboarding for people who arrived through a link
        st.info(f"Welcome! You joined this project with {ROLE_LABELS[role]} access. {ROLE_HELP[role]} "
                "Use the tabs below: Page shows the finished site, and the other tabs are for working together.")
        st.button("Got it", key=f"welcome_ok_{pid}", on_click=lambda: st.session_state.pop("welcome", None))
    live = st.toggle("Live updates", value=True, key=f"live_{pid}", help=f"Refresh the page, comments, and activity every {LIVE_SECONDS} seconds.")

    names = [n for n, ok in [("Page", True), ("Edit", can(role, "edit")), ("Comments", True),
                             ("Team and Sharing", can(role, "manage")), ("Activity", True)] if ok]
    tabs = dict(zip(names, st.tabs(names)))
    with tabs["Page"]:
        _live(render_page_tab, live)(pid)
    if "Edit" in tabs:
        with tabs["Edit"]:
            render_edit_tab(project, user)
    with tabs["Comments"]:
        lister = render_comments_tab(project, user, role)
        _live(lister, live)(pid)
    if "Team and Sharing" in tabs:
        with tabs["Team and Sharing"]:
            render_team_tab(project, user)
    with tabs["Activity"]:
        _live(render_activity, live)(pid)


def render_project_list(user):
    projects = list_projects(user["id"])
    with st.expander("Create a new project", expanded=not projects):
        with st.form("new_project_form"):
            title = st.text_input("Project title", max_chars=MAX_TITLE, key="np_title")
            description = st.text_area("Short description (optional)", max_chars=300, key="np_desc")
            created = st.form_submit_button("Create project", type="primary")
        if created:
            title = auth.clean_text(title, MAX_TITLE)
            if len(title) < 3:
                st.error("Please enter a project title of at least 3 characters.")
            else:
                _open(create_project(user, title, _multiline(description, 300)))
                st.rerun()
    st.header("Your projects")
    if not projects:
        st.info("You are not on any project yet. Create one above, or open an invite link from a teammate.")
    for p in projects:
        with st.container(border=True, key=f"card_project_{p['id']}"):  # card_ prefix picks up the app's card styling
            st.subheader(auth.md_escape(p["title"]))
            if p["description"]:
                st.write(p["description"])
            st.caption(f"Your role: {ROLE_LABELS[p['role']]}. {p['member_count']} member(s). "
                       f"Last activity: {fmt(p['last_active'] or p['created_at'])}")
            st.button("Open project", key=f"open_{p['id']}", type="primary", on_click=_open, args=(p["id"],))


def render_viewer_mode(link):
    """What a View or public link shows: the finished page only. No login, no editing tools, no comments."""
    project = get_project(link["project_id"])
    st.title(auth.md_escape(project["title"]))
    if project["description"]:
        st.write(project["description"])
    with st.expander("How to use this shared page"):
        st.markdown("- You are viewing a shared page. You can read, watch, and explore it without an account.\n"
                    "- You cannot edit or comment from this link.\n"
                    "- To work on a project like this, ask the team for an invitation, then sign up or log in.")
    render_blocks(link["project_id"], h=2)
    st.caption("This is a view-only shared page.")


# ---------------------------------------------------------------------------
# 10. PUBLIC ENTRY POINTS (what your main file calls)
# ---------------------------------------------------------------------------
def _project_typewriter(text, delay=0.012):
    """Yield characters at the same pace as the other page hero headings."""
    for character in text:
        yield character
        time.sleep(delay)


def render_projects_page(user):
    """The body of the Project Spaces sidebar page."""
    init_db()
    with st.container(key="project-space-hero"):
        st.write_stream(_project_typewriter("# Project Space"))
        st.write_stream(_project_typewriter(
            "Build a multimodal page with your team, share it, and see who contributed what."
        ))
    pid = st.session_state.get("open_project")
    if pid:
        project, role = get_project(pid), get_role(pid, user["id"])
        if project and role:
            render_project(project, role, user)
            return
        st.session_state.pop("open_project", None)
        st.warning("That project is not available to you anymore.")
    render_project_list(user)


def _go_home():
    st.query_params.clear()


def handle_shared_link():
    """
    Call this before auth.require_login(). With ?share=TOKEN in the address:
      - an invalid, expired, or revoked link shows a friendly message and stops
      - a View or public link shows the finished page (viewer mode) and stops, with no login
      - a Comment or Edit link is remembered so redeem_pending_share can add the user after they log in
    """
    token = st.query_params.get("share")
    if not token:
        return
    init_db()
    link = resolve_link(token)
    if not link:
        st.title("This link is not available")
        st.write("It may have expired or been revoked. Ask the project team for a new link.")
        st.button("Go to Multimodal Studio Hub", on_click=_go_home)
        st.stop()
    if link["role"] == "view":
        render_viewer_mode(link)
        st.stop()
    st.session_state["pending_share"] = token


def redeem_pending_share(user):
    """Call right after auth.require_login(): joins the project from a Comment or Edit link and opens it."""
    token = st.session_state.pop("pending_share", None)
    if not token:
        return
    pid = redeem_link(user, token)
    st.query_params.clear()
    if pid:
        st.session_state["open_project"] = pid
        st.session_state["welcome"] = pid
        st.session_state["nav"] = "Project Space"