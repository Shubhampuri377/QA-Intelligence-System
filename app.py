import streamlit as st
from styles.theme import inject_theme, nav_buttons, icon

st.set_page_config(page_title="QA Intelligence System", layout="wide",
                   page_icon="🧭", initial_sidebar_state="expanded")
inject_theme()
nav_buttons("home")

st.markdown(f"""
<div class="hero hero-simple">
  <div class="hero-eyebrow">{icon('compass', size=14)} Requirements &amp; QA Automation</div>
  <div class="hero-title">QA Intelligence System</div>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3, gap="large")

with c1:
    with st.container(key="home_docs"):
        st.markdown(f"""
        <div class="app-card app-card-simple">
          <div class="app-icon">{icon('layers', size=26)}</div>
          <div class="app-title">Document Generation</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open  →", key="go_docs", use_container_width=True):
            st.switch_page("pages/1_Document_Generation.py")

with c2:
    with st.container(key="home_data"):
        st.markdown(f"""
        <div class="app-card app-card-simple ac-amber">
          <div class="app-icon ic-amber">{icon('database', size=26)}</div>
          <div class="app-title">Data Generation</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open  →", key="go_data", use_container_width=True):
            st.switch_page("pages/2_Data_Generation.py")

with c3:
    with st.container(key="home_quality"):
        st.markdown(f"""
        <div class="app-card app-card-simple ac-teal">
          <div class="app-icon ic-teal">{icon('shield', size=26)}</div>
          <div class="app-title">Quality Intelligence</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open  →", key="go_quality", use_container_width=True):
            st.switch_page("pages/3_Quality_Intelligence.py")

st.markdown('<div class="footer-note">Bring your own API key (Gemini, Claude, or OpenAI) — used only for the current session, never stored.</div>', unsafe_allow_html=True)
