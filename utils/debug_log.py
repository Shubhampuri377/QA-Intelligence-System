"""Shared debug logger used by every workflow page to trace extraction, LLM calls, and parsing."""

import time
import streamlit as st


class DebugLog:
    def __init__(self):
        self.steps = []
        self.start_time = time.time()

    def add(self, level, stage, message, detail=""):
        self.steps.append({
            "level": level, "stage": stage, "message": message,
            "detail": detail, "ts": f"{time.time() - self.start_time:.2f}s"
        })

    def render(self):
        if not self.steps:
            return
        rows = ""
        for s in self.steps:
            bc = {"ok": "badge-ok", "warn": "badge-warn", "err": "badge-err", "info": "badge-info"}.get(s["level"], "badge-info")
            ic = {"ok": "✓", "warn": "⚠", "err": "✕", "info": "→"}.get(s["level"], "→")
            dh = f'<div class="dbg-sub">{s["detail"][:800]}</div>' if s["detail"] else ""
            rows += f"""<div class="dbg-step"><span class="dbg-badge {bc}">{ic} {s["stage"]}</span>
              <div><div class="dbg-msg">{s["message"]} <span style="color:#4b5563;font-size:0.65rem;">+{s["ts"]}</span></div>{dh}</div></div>"""
        ov = "dbg-err" if any(s["level"] == "err" for s in self.steps) else \
             "dbg-warn" if any(s["level"] == "warn" for s in self.steps) else "dbg-ok"
        lb = "FAILED" if "err" in ov else "WARNINGS" if "warn" in ov else "SUCCESS"
        st.markdown(f"""<div class="dbg-panel"><div class="dbg-header {ov}">◆ Debug Log &nbsp;·&nbsp; <span>{lb}</span>
          <span style="margin-left:auto;color:#4b5563;font-size:0.6rem;">{len(self.steps)} steps · {self.steps[-1]["ts"] if self.steps else "—"} total</span>
          </div>{rows}</div>""", unsafe_allow_html=True)
