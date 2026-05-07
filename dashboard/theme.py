"""Visual language for Drift Triage Co-Pilot.

Design philosophy: this is an *incident timeline UI*, not a control panel.
Everything renders as either a card, a pill, or a timeline event.
"""
from __future__ import annotations

import streamlit as st

# ── Tokens ────────────────────────────────────────────────────────────────────

C = {
    "bg":      "#0a0e1a",
    "surface": "#111827",
    "surface_hi": "#1a2235",
    "border":  "#1f2937",
    "border_hi": "#374151",
    "text":    "#f3f4f6",
    "muted":   "#94a3b8",
    "subtle":  "#64748b",
    "brand":   "#6366f1",
    "brand_hi": "#a5b4fc",
    "ok":      "#10b981",
    "warn":    "#f59e0b",
    "crit":    "#ef4444",
    "active":  "#fb923c",
    "ai":      "#8b5cf6",
    "human":   "#0ea5e9",
    "tool":    "#14b8a6",
}

SEV_TONE = {"ok": "ok", "warn": "warn", "critical": "crit"}
STATUS_TONE = {
    "open": "live", "awaiting_approval": "warn",
    "resolved": "ok", "escalated": "crit", "rejected": "muted",
}
STATUS_LABEL = {
    "open": "Investigating",
    "awaiting_approval": "Awaiting Approval",
    "resolved": "Resolved",
    "escalated": "Escalated",
    "rejected": "Rejected",
}


# ── Global CSS ────────────────────────────────────────────────────────────────

_CSS = f"""
<style>
:root {{
  --bg: {C["bg"]}; --surface: {C["surface"]}; --surface-hi: {C["surface_hi"]};
  --border: {C["border"]}; --border-hi: {C["border_hi"]};
  --text: {C["text"]}; --muted: {C["muted"]}; --subtle: {C["subtle"]};
  --brand: {C["brand"]}; --brand-hi: {C["brand_hi"]};
  --ok: {C["ok"]}; --warn: {C["warn"]}; --crit: {C["crit"]}; --active: {C["active"]};
  --ai: {C["ai"]}; --human: {C["human"]}; --tool: {C["tool"]};
}}

.stApp {{
  background:
    radial-gradient(1400px 700px at 10% -20%, rgba(99,102,241,0.16), transparent 55%),
    radial-gradient(800px 400px at 100% 0%, rgba(251,146,60,0.08), transparent 50%),
    var(--bg) !important;
  color: var(--text);
}}
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #060912 0%, var(--bg) 100%);
  border-right: 1px solid var(--border);
}}
section[data-testid="stSidebar"] * {{ color: var(--text) !important; }}

h1, h2, h3, h4, h5 {{ color: var(--text); letter-spacing: -0.015em; }}
.stMarkdown p, [data-testid="stCaptionContainer"] p {{ color: var(--muted); }}
hr {{ border-color: var(--border) !important; opacity: 0.6; }}

/* ── Hero ──────────────────────────────────────────────────────────────── */
.hero {{
  background:
    linear-gradient(120deg,
      rgba(99,102,241,0.18) 0%,
      rgba(139,92,246,0.10) 40%,
      rgba(14,165,233,0.06) 100%),
    var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px 28px;
  margin-bottom: 20px;
  position: relative;
  overflow: hidden;
}}
.hero::before {{
  content: "";
  position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  background: linear-gradient(180deg, var(--brand) 0%, var(--ai) 100%);
}}
.hero h1 {{ margin: 0; font-size: 26px; font-weight: 700; }}
.hero .sub {{ margin-top: 6px; color: var(--muted); font-size: 14px; }}
.hero .pills {{ margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }}

/* ── Pills ─────────────────────────────────────────────────────────────── */
.pill {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 11px; border-radius: 999px;
  font-size: 11.5px; font-weight: 600;
  border: 1px solid transparent;
  white-space: nowrap;
}}
.pill .dot {{ width: 6px; height: 6px; border-radius: 50%; background: currentColor; }}
.pill.live  {{ background: rgba(99,102,241,0.14); color: var(--brand-hi); border-color: rgba(99,102,241,0.4); }}
.pill.live  .dot {{ animation: pulse 1.4s ease-in-out infinite; }}
.pill.ok    {{ background: rgba(16,185,129,0.12); color: var(--ok);   border-color: rgba(16,185,129,0.35); }}
.pill.warn  {{ background: rgba(245,158,11,0.13); color: var(--warn); border-color: rgba(245,158,11,0.4); }}
.pill.crit  {{ background: rgba(239,68,68,0.15);  color: var(--crit); border-color: rgba(239,68,68,0.45); }}
.pill.muted {{ background: rgba(100,116,139,0.18); color: var(--muted); border-color: var(--border-hi); }}
.pill.brand {{ background: rgba(99,102,241,0.18); color: var(--brand-hi); border-color: rgba(99,102,241,0.5); }}

@keyframes pulse {{ 0%,100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.45; transform: scale(1.7); }} }}

/* ── Stat cards (replaces Streamlit metrics) ───────────────────────────── */
.stats {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}}
.stat {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  position: relative;
}}
.stat .lbl {{ font-size: 11px; color: var(--subtle); text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600; }}
.stat .val {{ font-size: 26px; font-weight: 700; color: var(--text); margin-top: 4px; line-height: 1.1; }}
.stat .sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
.stat.ok   {{ border-color: rgba(16,185,129,0.4); }}
.stat.warn {{ border-color: rgba(245,158,11,0.45); }}
.stat.crit {{ border-color: rgba(239,68,68,0.5); }}
.stat.ok   .val {{ color: var(--ok); }}
.stat.warn .val {{ color: var(--warn); }}
.stat.crit .val {{ color: var(--crit); }}

/* ── Storyline phases ──────────────────────────────────────────────────── */
.phase {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 14px;
  position: relative;
}}
.phase .ph-head {{
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 10px;
}}
.phase .ph-num {{
  width: 30px; height: 30px; border-radius: 8px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700;
  background: var(--surface-hi); color: var(--muted);
  border: 1px solid var(--border-hi);
}}
.phase .ph-title {{ font-size: 16px; font-weight: 600; color: var(--text); }}
.phase .ph-sub   {{ font-size: 12px; color: var(--muted); margin-left: auto; }}
.phase.done   {{ border-color: rgba(16,185,129,0.4); }}
.phase.done   .ph-num {{ background: rgba(16,185,129,0.15); color: var(--ok); border-color: rgba(16,185,129,0.5); }}
.phase.active {{ border-color: rgba(251,146,60,0.55); }}
.phase.active .ph-num {{ background: rgba(251,146,60,0.18); color: var(--active); border-color: rgba(251,146,60,0.6); }}
.phase.active::after {{
  content: ""; position: absolute; inset: 0; border-radius: 14px; pointer-events: none;
  border: 1px solid rgba(251,146,60,0.35);
  animation: glow 1.8s ease-in-out infinite;
}}
@keyframes glow {{
  0%,100% {{ box-shadow: 0 0 0 0 rgba(251,146,60,0.0); }}
  50%     {{ box-shadow: 0 0 22px 0 rgba(251,146,60,0.35); }}
}}

/* ── Timeline events (the heart of Investigation page) ─────────────────── */
.timeline {{ position: relative; padding-left: 32px; margin-top: 8px; }}
.timeline::before {{
  content: ""; position: absolute; left: 14px; top: 8px; bottom: 8px;
  width: 2px; background: linear-gradient(180deg, var(--border-hi), var(--border));
}}
.event {{
  position: relative; margin-bottom: 14px;
}}
.event::before {{
  content: ""; position: absolute; left: -25px; top: 14px;
  width: 12px; height: 12px; border-radius: 50%;
  background: var(--surface);
  border: 2px solid var(--border-hi);
  box-shadow: 0 0 0 4px var(--bg);
}}
.event.ok::before     {{ border-color: var(--ok); background: var(--ok); }}
.event.active::before {{ border-color: var(--active); background: var(--active); animation: ringPulse 1.4s ease-in-out infinite; }}
.event.crit::before   {{ border-color: var(--crit); background: var(--crit); }}
.event.brand::before  {{ border-color: var(--brand); background: var(--brand); }}
@keyframes ringPulse {{
  0%,100% {{ box-shadow: 0 0 0 4px var(--bg), 0 0 0 0 rgba(251,146,60,0.6); }}
  50%     {{ box-shadow: 0 0 0 4px var(--bg), 0 0 0 8px rgba(251,146,60,0); }}
}}
.event .ev-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
}}
.event.active .ev-card {{ border-color: rgba(251,146,60,0.5); }}
.event.ok .ev-card     {{ border-color: rgba(16,185,129,0.3); }}
.event .ev-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
.event .ev-title {{ font-weight: 600; color: var(--text); font-size: 14px; }}
.event .ev-time {{ margin-left: auto; font-size: 11px; color: var(--subtle); font-family: ui-monospace, monospace; }}
.event .ev-body {{ color: var(--muted); font-size: 13px; line-height: 1.55; }}
.event .ev-body code {{ background: var(--surface-hi); padding: 1px 6px; border-radius: 4px; color: var(--brand-hi); font-size: 12px; }}

/* ── Trajectory message bubbles ────────────────────────────────────────── */
.msg {{
  border-radius: 10px;
  padding: 10px 12px;
  margin: 6px 0;
  border-left: 3px solid var(--border-hi);
  background: var(--surface);
  font-size: 13px;
  color: var(--text);
}}
.msg.human {{ border-left-color: var(--human); }}
.msg.ai    {{ border-left-color: var(--ai); }}
.msg.tool  {{ border-left-color: var(--tool); }}
.msg .role {{
  display: inline-block;
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; margin-bottom: 4px; color: var(--muted);
}}
.msg.human .role {{ color: var(--human); }}
.msg.ai    .role {{ color: var(--ai); }}
.msg.tool  .role {{ color: var(--tool); }}

/* ── Buttons ───────────────────────────────────────────────────────────── */
.stButton > button {{
  border-radius: 10px;
  border: 1px solid var(--border-hi);
  background: var(--surface-hi);
  color: var(--text);
  font-weight: 600;
  transition: all 0.15s ease;
}}
.stButton > button:hover {{
  border-color: var(--brand-hi);
  background: var(--surface-hi);
  transform: translateY(-1px);
}}
.stButton > button[kind="primary"] {{
  background: linear-gradient(135deg, var(--brand) 0%, #7c3aed 100%);
  border: 1px solid rgba(165,180,252,0.5);
  color: white;
}}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.1); }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{
  background: transparent; padding: 8px 16px; color: var(--muted);
  border-radius: 8px 8px 0 0;
}}
.stTabs [aria-selected="true"] {{ color: var(--text); background: var(--surface); }}

/* Misc */
[data-testid="stMetric"] {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px;
}}
.stExpander {{ border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }}
.stAlert {{ border-radius: 10px; }}
#MainMenu {{ visibility: hidden; }}
footer    {{ visibility: hidden; }}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# ── Render helpers ────────────────────────────────────────────────────────────

def hero(title: str, sub: str, pills: list[tuple[str, str]] | None = None) -> None:
    pills = pills or []
    pill_html = "".join(
        f'<span class="pill {tone}"><span class="dot"></span>{txt}</span>'
        for txt, tone in pills
    )
    st.markdown(
        f'<div class="hero"><h1>{title}</h1><div class="sub">{sub}</div>'
        f'<div class="pills">{pill_html}</div></div>',
        unsafe_allow_html=True,
    )


def stats(items: list[dict]) -> None:
    """items = [{label, value, sub, tone}], tone in {'', 'ok', 'warn', 'crit'}."""
    cards = "".join(
        f'<div class="stat {it.get("tone","")}"><div class="lbl">{it["label"]}</div>'
        f'<div class="val">{it["value"]}</div>'
        f'<div class="sub">{it.get("sub","")}</div></div>'
        for it in items
    )
    st.markdown(f'<div class="stats">{cards}</div>', unsafe_allow_html=True)


def pill(text: str, tone: str = "muted") -> str:
    return f'<span class="pill {tone}"><span class="dot"></span>{text}</span>'


def severity_pill(sev: str) -> str:
    return pill(sev.upper(), SEV_TONE.get(sev, "muted"))


def status_pill(status: str) -> str:
    return pill(STATUS_LABEL.get(status, status), STATUS_TONE.get(status, "muted"))


def phase_open(num: int, title: str, state: str, sub: str = "") -> None:
    """state in {'idle','active','done'}. Caller writes content, then calls phase_close()."""
    st.markdown(
        f'<div class="phase {state}"><div class="ph-head">'
        f'<span class="ph-num">{num}</span>'
        f'<span class="ph-title">{title}</span>'
        f'<span class="ph-sub">{sub}</span></div>',
        unsafe_allow_html=True,
    )


def phase_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def event(title: str, body: str, tone: str = "brand", time_str: str = "") -> None:
    """Single timeline event. tone in {'ok','active','crit','brand'}."""
    st.markdown(
        f'<div class="event {tone}"><div class="ev-card">'
        f'<div class="ev-head"><span class="ev-title">{title}</span>'
        f'<span class="ev-time">{time_str}</span></div>'
        f'<div class="ev-body">{body}</div></div></div>',
        unsafe_allow_html=True,
    )


def message_bubble(role: str, content: str) -> None:
    role_class = role if role in ("human", "ai", "tool") else "ai"
    safe = content.replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f'<div class="msg {role_class}"><div class="role">{role}</div>'
        f'<pre style="white-space:pre-wrap;margin:0;font-family:ui-monospace,monospace;'
        f'color:inherit;font-size:12.5px;">{safe}</pre></div>',
        unsafe_allow_html=True,
    )
