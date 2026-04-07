import streamlit as st
import pandas as pd
from io import StringIO
import re

st.set_page_config(page_title="EVE Fleet ISK/hr Analyzer", layout="wide")

st.title("🚀 EVE Fleet ISK/hr Analyzer")
st.caption("Paste raw EVE wallet journal rows or CSV. Built for bounty and ESS analysis.")

# ---------------- SETTINGS ----------------
st.sidebar.header("Settings")
SESSION_GAP = st.sidebar.slider("Session Gap (minutes)", 5, 60, 20)
ROLLING_WINDOW = st.sidebar.slider("Rolling ISK/hr Window (minutes)", 5, 120, 30)
PAID_PILOTS = st.sidebar.number_input("Paid Pilots in Fleet", min_value=1, value=1, step=1)
HIDE_PILOT_STATS = st.sidebar.checkbox("Hide Pilot Stats", value=False)
SHOW_DEBUG = st.sidebar.checkbox("Show parser debug info", value=False)

# ---------------- SESSION STATE ----------------
if "wallet_input" not in st.session_state:
    st.session_state["wallet_input"] = ""
if "analyze_requested" not in st.session_state:
    st.session_state["analyze_requested"] = False

# ---------------- INPUT ----------------
st.subheader("Paste Wallet Journal")

with st.form("wallet_form", clear_on_submit=False):
    raw_input_form = st.text_area(
        "Paste directly from EVE or paste CSV here",
        value=st.session_state["wallet_input"],
        height=300,
        placeholder="Paste wallet journal here..."
    )

    col1, col2, col3 = st.columns([1, 1, 4])
    analyze_clicked = col1.form_submit_button("Analyze")
    clear_clicked = col2.form_submit_button("Clear")

if clear_clicked:
    st.session_state["wallet_input"] = ""
    st.session_state["analyze_requested"] = False
    st.rerun()

if analyze_clicked:
    st.session_state["wallet_input"] = raw_input_form
    st.session_state["analyze_requested"] = True

raw_input = st.session_state["wallet_input"]

# ---------------- HELPERS ----------------
def normalize_ref_type(value):
    s = str(value).strip().lower()
    mapping = {
        "bounty prizes": "bounty_prizes",
        "bounty prize corporation tax": "bounty_prize_corporation_tax",
        "ess escrow payment": "ess_escrow_payment",
        "ess main bank": "ess_main_bank",
        "ess reserved bank": "ess_reserved_bank",
        "ess escrow transfer": "ess_escrow_transfer",
    }
    return mapping.get(s, s.replace(" ", "_"))

def parse_amount(value):
    s = str(value).replace("ISK", "").replace(",", "").strip()
    try:
        return float(s)
    except:
        return None

def detect_character(reason):
    if not isinstance(reason, str):
        return "Unknown"
    m = re.search(r"\[r\]\s+(.+?)\s+got bounty prizes", reason, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"transferred funds to\s+(.+)$", reason, re.IGNORECASE)
    if m:
        return m.group(1)
    return "Unknown"

def detect_system(reason):
    if not isinstance(reason, str):
        return "Unknown"
    m = re.search(r"\bin\s+([A-Z0-9\-]+)", reason)
    if m:
        return m.group(1)
    return "Unknown"

# ---------------- PARSE ----------------
def parse_input(text):
    lines = [l for l in text.splitlines() if l.strip()]
    rows = []

    for line in lines:
        parts = re.split(r"\t+", line.strip())
        if len(parts) < 5:
            continue

        rows.append({
            "date": parts[0],
            "ref_type": parts[1],
            "amount": parts[2],
            "balance": parts[3],
            "reason": parts[4],
        })

    return pd.DataFrame(rows)

# ---------------- CLEAN ----------------
def clean(df):
    df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["date"])

    df["amount"] = df["amount"].apply(parse_amount)
    df = df.dropna(subset=["amount"])

    df["ref_type"] = df["ref_type"].apply(normalize_ref_type)
    df["character"] = df["reason"].apply(detect_character)
    df["system"] = df["reason"].apply(detect_system)

    df = df[df["amount"] > 0]
    df = df[~df["ref_type"].eq("bounty_prize_corporation_tax")]

    df = df[
        df["ref_type"].str.contains("bounty") |
        df["ref_type"].str.contains("ess")
    ]

    return df.sort_values("date")

# ---------------- SESSION ----------------
def sessions(df):
    df["gap"] = df["date"].diff().dt.total_seconds().div(60).fillna(0)
    df["session"] = (df["gap"] > SESSION_GAP).cumsum() + 1
    return df

# ---------------- MAIN ----------------
if st.session_state["analyze_requested"] and raw_input.strip():

    df = parse_input(raw_input)
    df = clean(df)
    df = sessions(df)

    total_isk = df["amount"].sum()
    hours = (df["date"].max() - df["date"].min()).total_seconds() / 3600
    isk_hr = total_isk / hours if hours else 0

    fleet_isk = total_isk * PAID_PILOTS
    fleet_hr = isk_hr * PAID_PILOTS

    bounty = df[df["ref_type"].str.contains("bounty")]["amount"].sum()
    ess = df[df["ref_type"].str.contains("ess")]["amount"].sum()

    # -------- OVERVIEW --------
    st.subheader("Fleet Overview")
    c1, c2, c3 = st.columns(3)
    c1.metric("Fleet ISK", f"{fleet_isk:,.0f}")
    c2.metric("Fleet ISK/hr", f"{fleet_hr:,.0f}")
    c3.metric("Paid Pilots", PAID_PILOTS)

    # -------- PILOT (OPTIONAL) --------
    if not HIDE_PILOT_STATS:
        st.subheader("Pilot Stats")
        p1, p2 = st.columns(2)
        p1.metric("Pilot ISK", f"{total_isk:,.0f}")
        p2.metric("Pilot ISK/hr", f"{isk_hr:,.0f}")

    # -------- SYSTEM --------
    st.subheader("Per System")
    sys = df.groupby("system")["amount"].sum().reset_index()
    sys["Fleet ISK"] = sys["amount"] * PAID_PILOTS
    st.dataframe(sys)

    # -------- GRAPH --------
    st.subheader("Fleet ISK Over Time")
    df["cum"] = df["amount"].cumsum() * PAID_PILOTS
    st.line_chart(df.set_index("date")["cum"])

    if not HIDE_PILOT_STATS:
        st.subheader("Pilot ISK Over Time")
        df["pilot_cum"] = df["amount"].cumsum()
        st.line_chart(df.set_index("date")["pilot_cum"])