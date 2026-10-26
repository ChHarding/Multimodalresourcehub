"""
auth_demo.py: the smallest app that uses auth.py.
Run with:  streamlit run auth_demo.py
"""

import streamlit as st

import auth

st.set_page_config(page_title="Multimodal Studio Hub", page_icon="📚")

# Everything below this line runs only for signed-in users who finished the tutorial
user = auth.require_login()
auth.render_account_sidebar(user)

st.title(f"Welcome back, {auth.md_escape(user['display_name'])}")
st.write(f"You are signed in as **{auth.role_label(user)}** with user ID **{auth.md_escape(user['user_id'])}**.")

# Role-based content: swap these messages for your real pages and tools
if auth.has_instructor_access(user):
    st.success("Instructor tools are unlocked: lesson plan and rubric downloads.")
else:
    st.info("Student view: resource library, exemplars, and your project space.")
