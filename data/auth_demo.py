"""
auth_demo.py: the smallest app that uses auth.py.
Run with:  streamlit run auth_demo.py
For local testing only, add this to .streamlit/secrets.toml so codes appear on screen:
    [auth]
    dev_mode = true
"""

import streamlit as st

import auth

st.set_page_config(page_title="Multimodal Studio Hub", page_icon="📚")

# Everything below this line runs only for signed-in users who finished the tutorial
user = auth.require_login()
auth.render_account_sidebar(user)

st.title(f"Welcome back, {auth.md_escape(user['display_name'])}")
st.write(f"You are signed in as **{auth.role_label(user)}** ({auth.md_escape(user['email'])}).")

# Role-based content: swap these messages for your real pages and tools
if auth.has_instructor_access(user):
    st.success("Instructor tools are unlocked: lesson plan and rubric downloads.")
elif auth.is_instructor(user):
    st.warning("Your instructor access is pending review. You can use the resource library in the meantime.")
else:
    st.info("Student view: resource library, exemplars, and your project space.")
