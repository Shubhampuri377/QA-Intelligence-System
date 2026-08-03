"""
Dark console theme — shared CSS, icon set, and reusable UI-building helpers
for every page in the app.
"""

import re
import streamlit as st

# ===========================================================================
# ICON SET — hand-drawn line icons (24x24, stroke-based), no emoji
# ===========================================================================

ICONS = {
    "compass": '<circle cx="12" cy="12" r="9"/><path d="M14.8 9.2L10.8 10.8L9.2 14.8L13.2 13.2L14.8 9.2Z"/>',
    "document": '<path d="M7 3H14L18 7V21H7V3Z"/><path d="M14 3V7H18"/><path d="M9.5 12H15.5"/><path d="M9.5 15.5H15.5"/>',
    "layers": '<path d="M12 3L21 8L12 13L3 8L12 3Z"/><path d="M3 13.5L12 18.5L21 13.5"/>',
    "database": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6V18C5 19.66 8.13 21 12 21C15.87 21 19 19.66 19 18V6"/><path d="M5 12C5 13.66 8.13 15 12 15C15.87 15 19 13.66 19 12"/>',
    "shield": '<path d="M12 3L19 6V11C19 15.5 16 19 12 21C8 19 5 15.5 5 11V6L12 3Z"/><path d="M9 12L11 14L15.5 9"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M19 19L15.2 15.2"/>',
    "flask": '<path d="M9.5 3H14.5"/><path d="M10.3 3V9.2L4.8 18.1C4.3 19 5 20 6 20H18C19 20 19.7 19 19.2 18.1L13.7 9.2V3"/><path d="M7.5 14.5H16.5"/>',
    "chart": '<path d="M4 20V11"/><path d="M12 20V4"/><path d="M20 20V14"/>',
    "upload": '<path d="M12 3V14"/><path d="M8 7L12 3L16 7"/><path d="M4 15V18.5C4 19.6 4.9 20.5 6 20.5H18C19.1 20.5 20 19.6 20 18.5V15"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5L10.5 15L16 9"/>',
    "alert-triangle": '<path d="M12 3L22 20H2L12 3Z"/><path d="M12 9.5V14"/><circle cx="12" cy="17.2" r="0.9" fill="currentColor" stroke="none"/>',
    "sliders": '<path d="M4 7H14"/><circle cx="17" cy="7" r="2.1"/><path d="M20 12H10"/><circle cx="7" cy="12" r="2.1"/><path d="M4 17H14"/><circle cx="17" cy="17" r="2.1"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12L20 3"/><path d="M16.2 6.8L18.7 9.3"/><path d="M13 10L15.3 12.3"/>',
    "folder": '<path d="M3 6.5H10L12 9H21V18C21 19 20.3 19.7 19.3 19.7H4.7C3.7 19.7 3 19 3 18V6.5Z"/>',
    "map": '<path d="M3 5L9 3L15 5L21 3V19L15 21L9 19L3 21V5Z"/><path d="M9 3V19"/><path d="M15 5V21"/>',
    "arrow-right": '<path d="M4 12H20"/><path d="M14 6L20 12L14 18"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7V12L15.5 14.5"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3 20C3 16.5 5.5 14 9 14C12.5 14 15 16.5 15 20"/><circle cx="17" cy="9" r="2.3"/><path d="M15.3 14.3C17.9 14.8 19.8 16.9 19.8 19.5"/>',
    "cpu": '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M9.5 3V6.5"/><path d="M14.5 3V6.5"/><path d="M9.5 17.5V21"/><path d="M14.5 17.5V21"/><path d="M3 9.5H6.5"/><path d="M3 14.5H6.5"/><path d="M17.5 9.5H21"/><path d="M17.5 14.5H21"/>',
    "zap": '<path d="M13 2L4 14H11L10 22L20 9H13L13 2Z" fill="currentColor" stroke="none"/>',
    "grid": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 10H21"/><path d="M3 15H21"/><path d="M9 4V20"/>',
    "code": '<path d="M8 6L3 12L8 18"/><path d="M16 6L21 12L16 18"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><circle cx="8.5" cy="9.5" r="1.7"/><path d="M3 16L8 11L12 15L16 11L21 16"/>',
}


def icon(name: str, size: int = 18, color: str = "currentColor", stroke_width: float = 1.75, cls: str = "") -> str:
    body = ICONS.get(name, ICONS["folder"])
    return (f'<svg class="icon {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="{stroke_width}" '
            f'stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">{body}</svg>')


# ===========================================================================
# CSS
# ===========================================================================

CSS = """
<style>

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@500;600;700&display=swap');

/* ── LIGHT (default) ──────────────────────────────────────────────
   One blue ramp, shared with the generated documents (#1F3A5F) so the
   screen and the downloaded PDF/DOCX/XLSX read as the same product.
   Gold survives only as the brand mark — a logo may be warm; chrome
   should not be. Everything else earns its colour by meaning. */
:root{
  --bg:#F7F8FA;
  --surface:#FFFFFF;
  --surface-2:#F1F3F7;
  --border:#E3E7EE;
  --border-strong:#CBD2DD;

  --text:#131720;
  --text-light:#4A5364;
  --text-faint:#8A93A3;

  --primary:#1F3A5F;
  --primary-dark:#162C48;
  --primary-soft:rgba(31,58,95,.08);
  --accent:#2E6BA8;
  --secondary:#3748A6;

  --gold:#AE8438;
  --gold-dark:#8C6A2C;
  --gold-soft:rgba(174,132,56,.13);

  --success:#15803D;
  --success-bg:rgba(21,128,61,.10);
  --warning:#B45309;
  --warning-bg:rgba(180,83,9,.10);
  --danger:#B42318;
  --danger-bg:rgba(180,35,24,.10);
  --info:#3748A6;
  --info-bg:rgba(55,72,166,.10);

  --shadow-sm:0 1px 2px rgba(19,23,32,.04);
  --shadow:0 2px 10px rgba(19,23,32,.06);
  --shadow-lg:0 12px 30px rgba(19,23,32,.10);

  --radius-sm:8px;
  --radius:11px;
  --radius-lg:14px;
  --transition:all .16s cubic-bezier(.4,0,.2,1);
}

html, body, [class*="css"]{
  font-family:'Inter',sans-serif;
  background:var(--bg);
  color:var(--text);
}

#MainMenu{display:none;}
footer{display:none;}
header{background:transparent !important;}

.block-container{
  padding-top:1.1rem;
  padding-bottom:3rem;
  max-width:1320px;
}

::-webkit-scrollbar{width:9px;height:9px;}
::-webkit-scrollbar-track{background:var(--bg);}
::-webkit-scrollbar-thumb{background:var(--border-strong);border-radius:20px;}
::-webkit-scrollbar-thumb:hover{background:#9AA3B5;}

h1,h2,h3,h4{color:var(--text);font-weight:700;}
h1{font-size:2.2rem;margin:0;}
h2{font-size:1.6rem;}
h3{font-size:1.2rem;}
p{color:var(--text-light);}
code{font-family:'JetBrains Mono',monospace !important;}

.icon{display:inline-block;vertical-align:-4px;flex-shrink:0;}

/* Streamlit sets font-family on its own markdown container via an emotion class,
   so anything rendered through st.markdown inherits Source Sans regardless of
   the html/body rule above. Rather than fight that cascade, the font is declared
   on the classes this file owns — guaranteed to apply, and it keeps the mono
   classes (.tbox-val, .stat-value, .fr-id) free to opt out below. */
.hero-title,.hero-sub,.hero-eyebrow,.app-title,.app-desc,.app-tag,.section-label,
.page-heading,.page-subheading,.ph-title,.ph-tag,.ph-sub,.upload-label,.upload-hint,
.file-pill,.tbox-label,.pipe-label,.agent-name,.agent-desc,.agent-status,.stat-label,
.chip,.fr-feature,.fr-desc,.fr-tag,.data-caption,.t-io,.t-rule,.t-val,.t-calc,
.req-text,.req-vtype,.vc-cat,.vc-sev,.vc-status,.vc-source,.vc-req,.vc-label,.vc-text,
.vc-detail,.evidence-item,.reviewer-title,.reviewer-desc,.export-title,.footer-note,
.sb-brand-text,.sb-brand-sub,.sb-section,.sb-item,.format-pill,.badge-soon{
  font-family:'Inter',sans-serif;
}

/* Streamlit renders widget labels (selectbox/text_input/slider/toggle/etc.)
   as <p> tags internally — the generic `p{color:var(--text-light)}` rule
   above was catching them and making "AI Provider", "Model" etc. read as
   dim secondary text. Force those back to strong, legible dark text. */
[data-testid="stWidgetLabel"] p{
  color:var(--text) !important;
  font-weight:600 !important;
  font-size:.86rem !important;
}

/* ===========================================================
   TOGGLE SWITCH
   Streamlit's default track is rgba(ink,.2) with a #F1F3F7 thumb — on a white
   surface that is a pale grey pill holding a near-white dot, which reads as
   nothing at all. Repainted here with real contrast in both themes.
   Targeted structurally (label containing input[role=switch] -> first div is
   the track, its child is the thumb) rather than by emotion class, since those
   hashes change between Streamlit versions.
=========================================================== */

label:has(input[role="switch"]) > div:first-of-type{
  background:#8A93A3 !important;          /* 3.1:1 on white — clearly a control */
  width:38px !important;height:20px !important;
  border-radius:999px !important;
  transition:background .18s ease !important;
}
label:has(input[role="switch"]) > div:first-of-type > div{
  background:#FFFFFF !important;
  width:15px !important;height:15px !important;
  box-shadow:0 1px 3px rgba(19,23,32,.32) !important;
}
label:has(input[role="switch"][aria-checked="true"]) > div:first-of-type,
label:has(input[role="switch"]:checked) > div:first-of-type{
  background:#1F3A5F !important;          /* navy = on */
}

/* ===========================================================
   SIDEBAR NAVIGATION
=========================================================== */

[data-testid="stSidebar"]{
  background:var(--surface);
  border-right:1px solid var(--border);
  box-shadow:var(--shadow-sm);
}
[data-testid="stSidebar"] > div{padding-top:1.4rem;}

.sb-brand{display:flex;align-items:center;gap:11px;padding:0 1.1rem 1.1rem;}
.sb-brand-mark{
  width:34px;height:34px;border-radius:9px;background:linear-gradient(155deg, var(--gold) 0%, var(--gold-dark) 100%);
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
  box-shadow:0 1px 3px rgba(140,106,44,.35);
}
.sb-brand-text{font-size:1rem;font-weight:700;color:var(--text);letter-spacing:-.01em;}
.sb-brand-sub{font-size:.68rem;color:var(--text-faint);margin-top:1px;text-transform:uppercase;letter-spacing:.05em;}

.sb-section{
  font-size:.66rem;font-weight:700;color:var(--text-faint);text-transform:uppercase;
  letter-spacing:.09em;padding:0 1.1rem;margin:.4rem 0 .6rem;
}

.sb-nav{display:flex;flex-direction:column;gap:2px;padding:0 .7rem;}
/* Nav labels are page names, and one of them is a full sentence, so items must
   survive wrapping: the icon stays beside the FIRST line rather than floating to
   the vertical centre of a two-line block. */
.sb-item{
  display:flex;align-items:flex-start;gap:11px;padding:9px 14px;border-radius:var(--radius-sm);
  color:var(--text-light);text-decoration:none !important;font-size:.87rem;font-weight:500;
  transition:var(--transition);
}
.sb-item:hover{background:var(--surface-2);color:var(--text);}
.sb-item-active{background:var(--primary-soft);color:var(--primary) !important;font-weight:700;}
.sb-item-active .icon{stroke:var(--primary);}
.sb-item-icon{display:flex;align-items:center;height:1.45em;}
.sb-item-label{line-height:1.45;}

/* ===========================================================
   HERO
=========================================================== */

.hero{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--radius-lg);
  padding:34px 34px 30px;
  position:relative;
  overflow:hidden;
  margin-bottom:20px;
  box-shadow:var(--shadow-sm);
}
.hero:after{
  content:"";position:absolute;right:0;top:0;width:340px;height:100%;
  background:radial-gradient(ellipse at top right, rgba(31,58,95,.05), transparent 68%);
  pointer-events:none;
}
.hero-eyebrow{
  display:inline-flex;align-items:center;gap:8px;
  padding:7px 14px;border-radius:999px;
  background:var(--primary-soft);color:var(--primary);
  font-size:.74rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  margin-bottom:20px;position:relative;z-index:1;
}
.hero-title{
  font-size:2.05rem;font-weight:700;line-height:1.2;margin-bottom:14px;
  color:var(--text);position:relative;z-index:1;letter-spacing:-.01em;
}
.hero-title .grad{color:var(--primary);}

.hero-simple{padding:28px 34px;text-align:center;}
.hero-simple .hero-eyebrow{margin-bottom:14px;}
.hero-simple .hero-title{font-size:1.75rem;margin-bottom:0;}
.hero-sub{
  font-size:1rem;line-height:1.75;color:var(--text-light);max-width:740px;
  position:relative;z-index:1;
}

/* ===========================================================
   SECTION LABEL / PAGE HEADING
=========================================================== */

.section-label{
  display:inline-flex;align-items:center;padding:6px 13px;
  background:var(--surface-2);color:var(--text-light);border-radius:999px;
  font-size:.72rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  margin-bottom:12px;border:1px solid var(--border);
}

.page-heading{font-size:1.4rem;font-weight:800;color:var(--text) !important;margin-bottom:6px;letter-spacing:-.01em;}
.page-subheading{font-size:.88rem;color:var(--text-light);margin-bottom:20px;}

.page-header-row{
  display:flex;align-items:center;gap:16px;position:relative;overflow:hidden;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 18px;margin-bottom:16px;box-shadow:var(--shadow-sm);
  border-left:3px solid var(--primary);
}
.ph-icon{
  width:38px;height:38px;border-radius:var(--radius-sm);flex-shrink:0;
  background:var(--primary-soft);
  display:flex;align-items:center;justify-content:center;
}
.ph-icon .icon{stroke:var(--primary);}
.ph-title{font-size:1.15rem;font-weight:800;color:var(--text) !important;line-height:1.2;}
.ph-tag{font-size:.68rem;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.06em;}
.ph-sub{font-size:.78rem;color:var(--text-faint);margin-top:2px;}

/* ===========================================================
   WORKFLOW / APP CARDS
=========================================================== */

.app-card{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:20px;position:relative;overflow:hidden;transition:var(--transition);height:100%;
  box-shadow:var(--shadow-sm);
}
.app-card:hover{border-color:var(--border-strong);transform:translateY(-3px);box-shadow:var(--shadow-lg);}

.app-icon{
  width:46px;height:46px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;
  margin-bottom:18px;background:var(--primary-soft);
}
.app-icon .icon{stroke:var(--primary);}
.ic-teal .icon{stroke:var(--info);}
.ic-teal{background:var(--info-bg);}
.ic-amber .icon{stroke:var(--gold-dark);}
.ic-amber{background:var(--gold-soft);}

.app-title{font-size:1.15rem;font-weight:700;margin-bottom:11px;color:var(--text) !important;}
.app-desc{font-size:.87rem;line-height:1.7;color:var(--text-light);margin-bottom:18px;}
.app-tags{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px;}
.app-tag{
  padding:5px 12px;border-radius:999px;background:var(--surface-2);
  border:1px solid var(--border);font-size:.7rem;font-weight:600;color:var(--text-light);
}

.app-card-simple{
  text-align:center;display:flex;flex-direction:column;align-items:center;
  padding:28px 22px 22px;
  /* Card and its button read as one panel, so the corners meet. */
  border-bottom-left-radius:0;border-bottom-right-radius:0;border-bottom:none;
  margin-bottom:0;
}
.app-card-simple .app-icon{width:46px;height:46px;margin:0 0 14px;border-radius:var(--radius);}
.app-card-simple .app-title{
  margin-bottom:0;display:flex;align-items:center;justify-content:center;line-height:1.35;
}

/* One page name is a full phrase and wraps to three lines; the others fit on
   one. Rather than reserve a guessed number of lines, let every card stretch to
   the tallest in the row — each wrapper between the column and the card has to
   pass the height down, hence the chain. Keyed off .app-card-simple so no other
   markdown block in the app is affected. */
[data-testid="stHorizontalBlock"]:has(.app-card-simple){align-items:stretch;}
[data-testid="stHorizontalBlock"]:has(.app-card-simple) [data-testid="stColumn"]{display:flex;}
[data-testid="stVerticalBlock"]:has(.app-card-simple){align-items:stretch;}
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-home_"]){flex:1 1 auto;display:flex;}
[class*="st-key-home_"]{flex:1 1 auto;}
[data-testid="stElementContainer"]:has(.app-card-simple),
[data-testid="stMarkdown"]:has(.app-card-simple),
[data-testid="stMarkdown"] > div:has(.app-card-simple),
[data-testid="stMarkdownContainer"]:has(> .app-card-simple){
  flex:1 1 auto;display:flex;flex-direction:column;
}
/* Top-aligned, not centred: the icons then form a row across the three cards
   and the longest title grows downward into the shared height. */
.app-card-simple{flex:1 1 auto;justify-content:flex-start;}
.app-card-simple .app-desc{margin-bottom:0;font-size:.85rem;}

/* The home-page launch buttons. st.container(key=...) emits a
   .st-key-<key> class, which is what lets these be styled without touching
   every other button in the app: squared at the top to sit flush under their
   card, taller than a form button so they read as the primary action. */
.st-key-home_docs .stButton>button,
.st-key-home_data .stButton>button,
.st-key-home_quality .stButton>button{
  border-radius:0 0 var(--radius-lg) var(--radius-lg);
  padding:15px 18px;font-size:.95rem;letter-spacing:.02em;
}
.st-key-home_docs .stButton>button:hover,
.st-key-home_data .stButton>button:hover,
.st-key-home_quality .stButton>button:hover{transform:none;box-shadow:var(--shadow-lg);}

.footer-note{
  margin-top:24px;text-align:center;font-size:.78rem;color:var(--text-faint);
  padding:16px;border-top:1px solid var(--border);
}

/* ===========================================================
   UPLOAD ZONES
=========================================================== */

.upload-label{
  display:flex;align-items:center;gap:7px;
  font-size:.78rem;font-weight:700;color:var(--text);margin-bottom:6px;
  text-transform:uppercase;letter-spacing:.03em;
}
.upload-label .icon{stroke:var(--text-light);}
.upload-hint{font-size:.72rem;color:var(--text-faint);margin-top:4px;margin-bottom:2px;}
.file-pill{
  display:inline-flex;align-items:center;gap:6px;margin-top:8px;
  padding:5px 12px;border-radius:999px;background:var(--success-bg);
  color:var(--success);font-size:.74rem;font-weight:600;
}

[data-testid="stFileUploaderDropzone"]{
  border-radius:var(--radius) !important;
  background:var(--surface) !important;
  border:1.5px dashed var(--border-strong) !important;
}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--primary) !important;}

/* ===========================================================
   BUTTONS
=========================================================== */

.stButton>button{
  background:linear-gradient(180deg, var(--primary) 0%, var(--primary-dark) 100%);
  color:#FFFFFF;border:none;border-radius:var(--radius-sm);
  padding:11px 18px;font-size:.9rem;font-weight:700;transition:var(--transition);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.14), 0 1px 2px rgba(16,19,28,.06), 0 0 0 1px rgba(11,79,108,.06);
}
.stButton>button:hover{background:linear-gradient(180deg, var(--primary-dark) 0%, var(--primary-dark) 100%);box-shadow:var(--shadow);transform:translateY(-1px);}
.stButton>button:disabled{background:var(--surface-2);color:var(--text-faint);box-shadow:none;}

/* Streamlit wraps button labels in an inner <p> (stMarkdownContainer) that
   carries its own explicit color — the button's own `color` never reaches
   the text node, so the global `p{color:var(--text-light)}` rule silently
   wins and renders labels like "Generate FRS" as faint gray-on-dark. */
.stButton>button p{color:#FFFFFF !important;font-weight:700 !important;}
.stButton>button:disabled p{color:var(--text-faint) !important;}

.stDownloadButton>button{
  background:var(--surface);color:var(--primary);border:1.5px solid var(--primary);
  border-radius:var(--radius-sm);font-weight:700;transition:var(--transition);
}
.stDownloadButton>button:hover{background:var(--primary-soft);}
.stDownloadButton>button p{color:var(--primary) !important;font-weight:700 !important;}

/* ===========================================================
   TOKEN / STAT MINI-BOXES (tbox)
=========================================================== */

.tbox{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:9px 12px;text-align:center;box-shadow:var(--shadow-sm);
}
.tbox-val{font-family:'JetBrains Mono',monospace;font-size:1rem;font-weight:700;color:var(--text);}
.tbox-label{font-size:.63rem;font-weight:700;color:var(--text-faint);text-transform:uppercase;letter-spacing:.05em;margin-top:2px;}
.tbox-green .tbox-val{color:var(--success);}

/* ===========================================================
   PIPELINE STEPPER (horizontal)
=========================================================== */

.pipeline{display:flex;justify-content:space-between;align-items:flex-start;margin:24px 0 8px;gap:4px;}
.pipe-step{display:flex;flex-direction:column;align-items:center;gap:8px;flex:1;position:relative;}
.pipe-connector{flex:0.6;height:1px;background:var(--border);margin-top:22px;}
.pipe-connector.pc-done{background:var(--success);}
.pipe-circle{
  width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  background:var(--surface-2);transition:var(--transition);border:1.5px solid var(--border);color:var(--text-faint);
}
.pipe-circle .icon{stroke:var(--text-faint);}
.pipe-active{background:var(--primary-soft);border-color:var(--primary);}
.pipe-active .icon{stroke:var(--primary);}
.pipe-done{background:var(--success-bg);border-color:var(--success);color:var(--success);}
.pipe-done .icon{stroke:var(--success);}
.pipe-label{font-size:.76rem;font-weight:600;color:var(--text-light);text-align:center;}

/* ===========================================================
   AGENT STEPPER (vertical — QA Validation pipeline)
=========================================================== */

.agent-flow{display:flex;flex-direction:column;gap:0;margin:16px 0;}
.agent-row{display:flex;align-items:flex-start;gap:13px;padding:10px 4px;position:relative;}
.agent-row .agent-line{position:absolute;left:23px;top:50px;bottom:-14px;width:1px;background:var(--border);}
.agent-row:last-child .agent-line{display:none;}
.agent-row.ar-done .agent-line{background:var(--success);}
.agent-icon{
  width:46px;height:46px;border-radius:var(--radius-sm);flex-shrink:0;display:flex;align-items:center;justify-content:center;
  background:var(--surface-2);border:1.5px solid var(--border);transition:var(--transition);position:relative;z-index:1;
}
.agent-icon .icon{stroke:var(--text-faint);}
.agent-row.ar-running .agent-icon{background:var(--primary-soft);border-color:var(--primary);}
.agent-row.ar-running .agent-icon .icon{stroke:var(--primary);}
.agent-row.ar-done .agent-icon{background:var(--success-bg);border-color:var(--success);}
.agent-row.ar-done .agent-icon .icon{stroke:var(--success);}
.agent-row.ar-failed .agent-icon{background:var(--danger-bg);border-color:var(--danger);}
.agent-row.ar-failed .agent-icon .icon{stroke:var(--danger);}

.agent-body{flex:1;padding-top:4px;}
.agent-name{font-size:.92rem;font-weight:700;color:var(--text);}
.agent-desc{font-size:.78rem;color:var(--text-light);margin-top:2px;line-height:1.5;}
.agent-status{
  display:inline-flex;align-items:center;gap:6px;margin-top:7px;padding:3px 10px;border-radius:999px;
  font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
}
.as-idle{background:var(--surface-2);color:var(--text-faint);}
.as-running{background:var(--primary-soft);color:var(--primary);}
.as-done{background:var(--success-bg);color:var(--success);}
.as-failed{background:var(--danger-bg);color:var(--danger);}

/* ===========================================================
   STAT CARDS
=========================================================== */

.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin:10px 0 16px;}
.stat-card{
  background:var(--surface);border-radius:var(--radius);padding:12px 14px;border:1px solid var(--border);
  transition:var(--transition);display:flex;align-items:center;gap:11px;box-shadow:var(--shadow-sm);
}
.stat-card:hover{border-color:var(--border-strong);box-shadow:var(--shadow);}
.stat-badge{
  width:38px;height:38px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;flex-shrink:0;
}
.sb-purple{background:var(--primary-soft);}
.sb-purple .icon{stroke:var(--primary);}
.sb-green{background:var(--success-bg);}
.sb-green .icon{stroke:var(--success);}
.sb-red{background:var(--danger-bg);}
.sb-red .icon{stroke:var(--danger);}
.sb-amber{background:var(--warning-bg);}
.sb-amber .icon{stroke:var(--warning);}
.sb-blue{background:var(--info-bg);}
.sb-blue .icon{stroke:var(--info);}
.stat-value{font-size:1.35rem;font-weight:700;line-height:1;font-family:'JetBrains Mono',monospace;color:var(--text);}
.sv-purple{color:var(--primary);}
.sv-green{color:var(--success);}
.sv-red{color:var(--danger);}
.sv-amber{color:var(--warning);}
.sv-blue{color:var(--info);}
.stat-label{font-size:.73rem;color:var(--text-light);margin-top:2px;font-weight:500;}

/* ===========================================================
   CHIPS
=========================================================== */

.chips-row{display:flex;gap:9px;flex-wrap:wrap;margin:16px 0;}
.chip{
  display:flex;align-items:center;gap:8px;padding:6px 13px;border-radius:999px;
  background:var(--surface);border:1px solid var(--border);font-size:.78rem;font-weight:600;color:var(--text-light);
}
.chip-count{background:var(--primary);color:#FFFFFF;padding:1px 8px;border-radius:999px;font-size:.68rem;font-weight:700;}

/* ===========================================================
   FR / REQUIREMENT CARD CONTENT
=========================================================== */

.fr-id{
  font-family:'JetBrains Mono',monospace;font-size:.72rem;font-weight:700;color:var(--primary);
  background:var(--primary-soft);border-radius:6px;padding:3px 8px;
}
.fr-feature{font-size:.94rem;font-weight:700;color:var(--text);}
.fr-desc{font-size:.83rem;color:var(--text-light);line-height:1.6;margin:8px 0;}
.fr-tags{display:flex;gap:6px;flex-wrap:wrap;}
.fr-tag{font-size:.66rem;font-weight:700;padding:3px 9px;border-radius:999px;background:var(--surface-2);color:var(--text-light);}
.data-caption{font-size:.68rem;font-weight:700;color:var(--text-faint);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;}
.t-io,.t-rule,.t-val,.t-calc{font-size:.8rem;color:var(--text-light);margin-bottom:5px;line-height:1.5;}

/* ===========================================================
   REQUIREMENT STORE CARD
=========================================================== */

.req-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;margin-bottom:8px;box-shadow:var(--shadow-sm);}
.req-top{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}
.req-vtype{
  margin-left:auto;font-size:.66rem;font-weight:700;padding:3px 10px;border-radius:999px;
  background:var(--info-bg);color:var(--info);text-transform:uppercase;letter-spacing:.03em;
}
.req-text{font-size:.9rem;font-weight:600;color:var(--text);margin-bottom:8px;line-height:1.5;}
.req-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;}

/* ===========================================================
   VALIDATION / EVIDENCE CARDS
=========================================================== */

.vc-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;margin-bottom:8px;box-shadow:var(--shadow-sm);}
.vc-top{display:flex;align-items:center;gap:9px;margin-bottom:8px;flex-wrap:wrap;}
.vc-id{
  font-size:.66rem;font-weight:700;color:var(--primary);font-family:'JetBrains Mono',monospace;
  text-transform:uppercase;letter-spacing:.03em;background:var(--primary-soft);border-radius:6px;padding:3px 8px;
}
.vc-cat{font-size:.64rem;font-weight:700;padding:3px 9px;border-radius:999px;background:var(--surface-2);color:var(--text-light);}
.vc-sev{font-size:.62rem;font-weight:700;padding:3px 8px;border-radius:6px;}
.sev-critical{background:var(--danger-bg);color:var(--danger);}
.sev-major{background:var(--warning-bg);color:var(--warning);}
.sev-minor{background:var(--info-bg);color:var(--info);}
.sev-info{background:var(--surface-2);color:var(--text-faint);}
.vc-status{
  font-size:.66rem;font-weight:800;padding:3px 11px;border-radius:999px;text-transform:uppercase;
  letter-spacing:.04em;margin-left:auto;
}
.st-pass{background:var(--success-bg);color:var(--success);}
.st-fail{background:var(--danger-bg);color:var(--danger);}
.st-warn{background:var(--warning-bg);color:var(--warning);}
.st-na{background:var(--surface-2);color:var(--text-faint);}
.vc-source{font-size:.64rem;font-weight:700;padding:3px 9px;border-radius:999px;white-space:nowrap;}
.vc-source-det{background:var(--success-bg);color:var(--success);}
.vc-source-ai{background:var(--primary-soft);color:var(--primary);}
.vc-req{font-size:.9rem;font-weight:700;color:var(--text);margin-bottom:6px;}
.vc-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:8px;}
.vc-label{font-size:.64rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-faint);margin-bottom:3px;}
.vc-text{font-size:.82rem;color:var(--text-light);line-height:1.55;}
.vc-detail{font-size:.8rem;color:var(--text-light);line-height:1.6;margin-top:6px;padding-top:8px;border-top:1px dashed var(--border);}

.confidence-wrap{display:flex;align-items:center;gap:8px;margin-top:8px;}
.confidence-track{flex:1;height:6px;border-radius:99px;background:var(--surface-2);overflow:hidden;}
.confidence-fill{height:100%;border-radius:99px;background:var(--primary);}
.confidence-fill.cf-high{background:var(--success);}
.confidence-fill.cf-med{background:var(--warning);}
.confidence-fill.cf-low{background:var(--danger);}
.confidence-num{font-size:.7rem;font-weight:700;color:var(--text-light);font-family:'JetBrains Mono',monospace;min-width:34px;text-align:right;}

.evidence-box{margin-top:10px;padding:11px 13px;background:var(--surface-2);border-radius:var(--radius-sm);border:1px solid var(--border);}
.evidence-item{font-size:.76rem;color:var(--text-light);line-height:1.6;margin-bottom:4px;}
.evidence-item b{color:var(--text);}

.reviewer-card{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:13px 16px;
  margin-bottom:8px;border-left:3px solid var(--warning);box-shadow:var(--shadow-sm);
}
.reviewer-card.rc-info{border-left-color:var(--info);}
.reviewer-card.rc-critical{border-left-color:var(--danger);}
.reviewer-title{font-size:.83rem;font-weight:700;color:var(--text);}
.reviewer-desc{font-size:.77rem;color:var(--text-light);margin-top:3px;line-height:1.5;}

/* ===========================================================
   EXPORT BOX
=========================================================== */

.export-box{margin-top:16px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow-sm);}
.export-title{font-size:.85rem;font-weight:700;color:var(--text);margin-bottom:13px;text-transform:uppercase;letter-spacing:.04em;}

/* ===========================================================
   DEBUG LOG
=========================================================== */

.dbg-panel{background:#05070B;border:1px solid var(--border);border-radius:var(--radius);padding:15px 17px;margin-top:10px;font-family:'JetBrains Mono',monospace;}
.dbg-header{
  display:flex;align-items:center;gap:8px;color:var(--text-light);font-size:.76rem;font-weight:700;
  padding-bottom:9px;margin-bottom:9px;border-bottom:1px solid var(--border);text-transform:uppercase;letter-spacing:.04em;
}
.dbg-header.dbg-ok span{color:var(--success);}
.dbg-header.dbg-warn span{color:var(--warning);}
.dbg-header.dbg-err span{color:var(--danger);}
.dbg-step{display:flex;gap:10px;padding:5px 0;align-items:flex-start;}
.dbg-badge{font-size:.64rem;font-weight:700;padding:2px 7px;border-radius:6px;white-space:nowrap;flex-shrink:0;margin-top:1px;}
.badge-ok{background:var(--success-bg);color:var(--success);}
.badge-warn{background:var(--warning-bg);color:var(--warning);}
.badge-err{background:var(--danger-bg);color:var(--danger);}
.badge-info{background:var(--info-bg);color:var(--info);}
.dbg-msg{color:var(--text-light);font-size:.74rem;}
.dbg-sub{color:var(--text-faint);font-size:.68rem;margin-top:2px;white-space:pre-wrap;word-break:break-word;}

/* ===========================================================
   MISC
=========================================================== */

.divider-soft{border:none;border-top:1px solid var(--border);margin:18px 0;}
.badge-soon{
  font-size:.6rem;font-weight:700;padding:2px 7px;border-radius:999px;background:var(--surface-2);
  color:var(--text-faint);text-transform:uppercase;letter-spacing:.04em;margin-left:6px;
}
.format-pill{
  display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:var(--radius-sm);
  border:1px solid var(--border);background:var(--surface);font-size:.76rem;font-weight:600;margin:3px 6px 3px 0;color:var(--text-light);
}
.format-pill .icon{stroke:var(--text-faint);}
.format-pill.fp-ready{border-color:var(--primary);color:var(--primary);background:var(--primary-soft);}
.format-pill.fp-ready .icon{stroke:var(--primary);}

</style>
"""


# ===========================================================================
# DARK THEME
# ===========================================================================
# Injected AFTER the base sheet, so it wins on cascade order alone — no
# data-attribute juggling and no JS. Because every colour in the base sheet is
# a custom property, redeclaring :root swaps the whole app.
#
# Not pure black: a desaturated navy-slate reads calmer over long sessions and
# keeps the same hue family as the light theme. Depth comes from surface steps
# and 1px borders rather than shadows, which mostly vanish on dark anyway.
#
# The second half re-skins Streamlit's own widget chrome. Those elements are
# painted from config.toml (base="light") and cannot be reached any other way,
# so without these overrides the inputs, dataframes and expanders would stay
# white while everything around them went dark.

CSS_DARK = """
<style>
:root{
  --bg:#0E1218;
  --surface:#161B23;
  --surface-2:#1E252F;
  --border:#28313D;
  --border-strong:#3A4553;

  --text:#E8ECF3;
  --text-light:#A4AEBE;
  --text-faint:#6D7889;

  --primary:#4E96CF;
  --primary-dark:#3B7EB4;
  --primary-soft:rgba(78,150,207,.15);
  --accent:#6FB0E0;

  --gold:#C9A057;
  --gold-dark:#A8823F;
  --gold-soft:rgba(201,160,87,.16);

  --success:#4ADE80;
  --success-bg:rgba(74,222,128,.13);
  --warning:#FBBF24;
  --warning-bg:rgba(251,191,36,.13);
  --danger:#F87171;
  --danger-bg:rgba(248,113,113,.13);
  --info:#93AFEA;
  --info-bg:rgba(147,175,234,.13);

  --shadow-sm:0 1px 2px rgba(0,0,0,.30);
  --shadow:0 3px 12px rgba(0,0,0,.36);
  --shadow-lg:0 14px 34px rgba(0,0,0,.46);
}

html, body, [class*="css"], .stApp, [data-testid="stAppViewContainer"]{
  background:var(--bg) !important;
  color:var(--text);
}

/* Streamlit's header overlays the first 60px of the page while content begins
   around y=50, so an OPAQUE header clips the top — rounded corners included —
   off whichever box comes first. The light sheet keeps it transparent; dark must
   too, or every page looks like its first card is cut off at the top. */
[data-testid="stHeader"]{background:transparent !important;}
::-webkit-scrollbar-thumb:hover{background:var(--border-strong);}

/* ── Streamlit widget chrome ──
   config.toml carries a single static palette with no dark variant, so every
   native widget surface (selectbox, text input, number input) keeps painting
   itself with secondaryBackgroundColor — light — no matter what the app around
   it does. These rules are the only thing that makes them follow dark mode.

   Two hard-won details:
   * Streamlit 1.60 emits NO data-baseweb attributes, so selectors written
     against them match nothing. Targeting is by data-testid instead.
   * The element carrying the background is the input's direct parent, at a
     wrapper depth that changes between versions — `div:has(> input)` finds it
     without depending on that depth.
   Literal hex, not var(), because these must resolve identically regardless of
   which sheet order the browser settles on. */
[data-testid="stSidebar"]{background:var(--surface) !important;}

/* Sidebar collapse control — dark ink at 60% on a dark sidebar is invisible. */
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapseButton"] *,
[data-testid="stSidebarHeader"] button, [data-testid="stSidebarHeader"] button *{
  color:#A4AEBE !important;
}
[data-testid="stSidebarCollapseButton"]:hover *{color:#E8ECF3 !important;}

[data-testid="stSelectbox"] div:has(> input),
[data-testid="stTextInput"] div:has(> input),
[data-testid="stNumberInput"] div:has(> input),
[data-testid="stDateInput"] div:has(> input),
[data-testid="stTextArea"] div:has(> textarea){
  background:#1E252F !important;
  border-color:#28313D !important;
}
[data-testid="stSelectbox"] input, [data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input, [data-testid="stTextArea"] textarea{
  color:#E8ECF3 !important;
  -webkit-text-fill-color:#E8ECF3 !important;   /* password fields ignore `color` */
}
input::placeholder, textarea::placeholder{color:#6D7889 !important;}

/* Dropdown chevrons, password reveal, and the help "?" icons. */
[data-testid="stSelectbox"] svg, [data-testid="stTextInput"] svg,
[data-testid="stSelectbox"] button, [data-testid="stTextInput"] button,
[data-testid="stTooltipIcon"], [data-testid="stTooltipIcon"] *{
  color:#A4AEBE !important; fill:#A4AEBE !important;
}

/* The open dropdown list is portalled outside the widget, so it needs its own rules. */
[role="listbox"]{background:#1E252F !important;border:1px solid #28313D !important;}
[role="option"]{background:#1E252F !important;color:#E8ECF3 !important;}
[role="option"]:hover, [role="option"][aria-selected="true"]{
  background:rgba(78,150,207,.20) !important;
}
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] *{color:#E8ECF3 !important;}

[data-testid="stFileUploaderDropzone"]{
  background:var(--surface-2) !important;
  border-color:var(--border-strong) !important;
}
[data-testid="stFileUploaderDropzone"] *{color:var(--text-light) !important;}

[data-testid="stExpander"]{
  background:var(--surface) !important;
  border-color:var(--border) !important;
}
[data-testid="stExpander"] summary{color:var(--text) !important;}
[data-testid="stExpander"] summary p{color:var(--text) !important;}

/* Dataframes carry the 645-row detail tables — the part read longest. */
[data-testid="stDataFrame"], [data-testid="stTable"]{
  background:var(--surface) !important;
  border:1px solid var(--border) !important;
  border-radius:var(--radius-sm);
}
[data-testid="stDataFrame"] [role="columnheader"]{
  background:var(--surface-2) !important;color:var(--text) !important;
}
[data-testid="stDataFrame"] [role="gridcell"]{
  background:var(--surface) !important;color:var(--text-light) !important;
  border-color:var(--border) !important;
}

[data-testid="stMetric"], [data-testid="stNotification"]{
  background:var(--surface) !important;color:var(--text) !important;
}
[data-testid="stAlertContainer"]{border-color:var(--border) !important;}
[data-testid="stProgress"] > div > div{background:var(--surface-2) !important;}
hr, [data-testid="stDivider"]{border-color:var(--border) !important;}
.stTabs button{color:var(--text-light) !important;}
.stTabs button[aria-selected="true"]{color:var(--primary) !important;}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p{
  color:var(--text-faint) !important;
}
.stDownloadButton>button{background:var(--surface-2) !important;}
.dbg-panel{background:#080B10;}

/* Toggle: on dark the thumb must stay light and the off-track must lift off the
   surface, otherwise the switch disappears the other way round. */
/* The toggle's ON state always means "dark theme is active", so only two
   combinations ever occur: light+off and dark+on. The track colour set in the
   base sheet (#8A93A3) is deliberately a neutral that clears 3:1 on white AND
   5.6:1 on the dark surface, so it stays legible in both. State is signalled by
   the thumb, which is the one part of this widget whose styling reliably
   applies from the dark sheet. */
label:has(input[role="switch"]) > div:first-of-type > div{
  background:#0E1218 !important;
  box-shadow:0 1px 3px rgba(0,0,0,.55) !important;
}
</style>
"""


def is_dark() -> bool:
    """The active theme.

    Stored in the URL (?theme=dark), not just session state: the sidebar nav
    uses plain <a href> links, so moving between pages is a full page load that
    resets session state. A query param survives that, and survives a bookmark
    or a hard refresh too."""
    theme = st.query_params.get("theme")
    if theme in ("dark", "light"):
        return theme == "dark"
    return bool(st.session_state.get("ui_dark_mode", False))


def inject_theme(dark: bool | None = None):
    """Injects the base sheet, then the dark overrides when dark mode is on."""
    if dark is None:
        dark = is_dark()
    st.markdown(CSS, unsafe_allow_html=True)
    if dark:
        st.markdown(CSS_DARK, unsafe_allow_html=True)


# ===========================================================================
# SIDEBAR NAVIGATION
# ===========================================================================

_NAV_ITEMS = [
    ("home", "compass", "Home", "app.py"),
    ("docs", "layers", "Document Generation", "pages/1_Document_Generation.py"),
    ("data", "database", "Data Generation", "pages/2_Data_Generation.py"),
    ("quality", "shield", "Quality Intelligence", "pages/3_Quality_Intelligence.py"),
]


def _page_href(target: str, dark: bool = False) -> str:
    base = "/" if target == "app.py" else re.sub(
        r"^\d+_", "", target.split("/")[-1].replace(".py", ""))
    # Carry the theme through the link — these are full page loads.
    return f"{base}?theme=dark" if dark else base


def _sync_theme_to_url():
    """Toggle handler: writes the choice to the URL so it survives navigation."""
    st.query_params["theme"] = "dark" if st.session_state.get("ui_dark_mode") else "light"


def nav_buttons(active: str):
    dark = is_dark()
    # Seed the widget from the URL before it is created, so the switch shows the
    # state the page is actually rendering in.
    if "ui_dark_mode" not in st.session_state:
        st.session_state["ui_dark_mode"] = dark

    rows = "".join(
        f'<a href="{_page_href(target, dark)}" target="_self" class="sb-item {"sb-item-active" if key == active else ""}">'
        f'<span class="sb-item-icon">{icon(ic, size=16)}</span>'
        f'<span class="sb-item-label">{label}</span></a>'
        for key, ic, label, target in _NAV_ITEMS
    )
    with st.sidebar:
        st.markdown(f"""
        <div class="sb-brand">
          <div class="sb-brand-mark">{icon('shield', size=18, color='#2B2005')}</div>
          <div>
            <div class="sb-brand-text">Console</div>
            <div class="sb-brand-sub">Requirements &amp; QA</div>
          </div>
        </div>
        <div class="sb-section">Navigate</div>
        <div class="sb-nav">{rows}</div>
        """, unsafe_allow_html=True)

        # Appearance toggle. Setting session state triggers Streamlit's rerun,
        # and inject_theme() reads the new value at the top of that pass — so the
        # switch takes effect immediately without a manual refresh.
        st.markdown('<div class="sb-section" style="margin-top:1.2rem;">Appearance</div>',
                    unsafe_allow_html=True)
        st.toggle("Dark mode", key="ui_dark_mode", on_change=_sync_theme_to_url,
                  help="Applies across every page and survives a refresh.")


# ===========================================================================
# PAGE HEADER
# ===========================================================================

def page_header(icon_name: str, title: str, tag: str, subtitle: str):
    st.markdown(f"""
    <div class="page-header-row">
      <div class="ph-icon">{icon(icon_name, size=22)}</div>
      <div>
        <div class="ph-tag">{tag}</div>
        <div class="ph-title">{title}</div>
        <div class="ph-sub">{subtitle}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ===========================================================================
# TOKEN / MINI STAT BOX
# ===========================================================================

def tbox(label: str, value: str, cls: str = "") -> str:
    return f"""<div class="tbox {cls}"><div class="tbox-val">{value}</div><div class="tbox-label">{label}</div></div>"""


# ===========================================================================
# HORIZONTAL PIPELINE STEPPER
# ===========================================================================

def pipeline_bar(steps, connector: str = "›"):
    """steps: list of (icon_name, label, status) where status in {idle, active, done}."""
    parts = ['<div class="pipeline">']
    for i, (icon_name, label, status) in enumerate(steps):
        circle_cls = {"active": "pipe-active", "done": "pipe-done"}.get(status, "")
        content = icon("check-circle", size=18) if status == "done" else icon(icon_name, size=18)
        parts.append(f"""
        <div class="pipe-step">
          <div class="pipe-circle {circle_cls}">{content}</div>
          <div class="pipe-label">{label}</div>
        </div>""")
        if i < len(steps) - 1:
            done_cls = "pc-done" if status == "done" else ""
            parts.append(f'<div class="pipe-connector {done_cls}"></div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ===========================================================================
# VERTICAL AGENT STEPPER (QA Validation live pipeline)
# ===========================================================================

def agent_stepper(agents):
    """agents: list of dicts {icon, name, desc, status} where status in
    {idle, running, done, failed}."""
    parts = ['<div class="agent-flow">']
    for a in agents:
        status = a.get("status", "idle")
        row_cls = {"running": "ar-running", "done": "ar-done", "failed": "ar-failed"}.get(status, "")
        status_cls = {"idle": "as-idle", "running": "as-running", "done": "as-done", "failed": "as-failed"}.get(status, "as-idle")
        status_label = {"idle": "Waiting", "running": "Running…", "done": "Complete", "failed": "Failed"}.get(status, "Waiting")
        icon_name = "check-circle" if status == "done" else ("alert-triangle" if status == "failed" else a.get("icon", "folder"))
        parts.append(f"""
        <div class="agent-row {row_cls}">
          <div class="agent-line"></div>
          <div class="agent-icon">{icon(icon_name, size=19)}</div>
          <div class="agent-body">
            <div class="agent-name">{a.get('name', '')}</div>
            <div class="agent-desc">{a.get('desc', '')}</div>
            <div class="agent-status {status_cls}">{status_label}</div>
          </div>
        </div>""")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ===========================================================================
# STAT CARDS ROW
# ===========================================================================

_STAT_ICONS = {"sb-purple": "layers", "sb-green": "check-circle", "sb-red": "alert-triangle",
               "sb-amber": "clock", "sb-blue": "cpu"}


def stats_row(items):
    """items: list of (badge_class, value, label, value_class)."""
    cards = "".join(f"""
      <div class="stat-card">
        <div class="stat-badge {badge}">{icon(_STAT_ICONS.get(badge, 'folder'), size=17)}</div>
        <div>
          <div class="stat-value {vcls}">{value}</div>
          <div class="stat-label">{label}</div>
        </div>
      </div>""" for badge, value, label, vcls in items)
    st.markdown(f'<div class="stats-grid">{cards}</div>', unsafe_allow_html=True)


# ===========================================================================
# CONFIDENCE BAR
# ===========================================================================

def confidence_bar(value) -> str:
    try:
        v = max(0, min(100, float(value)))
    except (TypeError, ValueError):
        v = 0
    cls = "cf-high" if v >= 75 else ("cf-med" if v >= 45 else "cf-low")
    return f"""<div class="confidence-wrap">
      <div class="confidence-track"><div class="confidence-fill {cls}" style="width:{v}%;"></div></div>
      <div class="confidence-num">{int(v)}%</div>
    </div>"""


# ===========================================================================
# EVIDENCE BLOCK
# ===========================================================================

def evidence_block(evidence: dict) -> str:
    if not evidence:
        return ""
    rows = "".join(
        f'<div class="evidence-item"><b>{k}:</b> {v}</div>'
        for k, v in evidence.items() if v
    )
    if not rows:
        return ""
    return f'<div class="evidence-box">{rows}</div>'


# ===========================================================================
# FORMAT PILL (input data format selector display)
# ===========================================================================

_FORMAT_ICONS = {
    "JSON": "code", "XML": "code", "CSV / Excel": "grid", "Print Image": "image",
    "Fixed-Length": "folder", "Multi-Length": "folder", "Symitar": "database",
}


def format_pill(label: str, ready: bool) -> str:
    cls = "fp-ready" if ready else "fp-soon"
    suffix = "" if ready else '<span class="badge-soon">Soon</span>'
    ic = icon(_FORMAT_ICONS.get(label, "folder"), size=14)
    return f'<span class="format-pill {cls}">{ic} {label}{suffix}</span>'
