"""
Scores and Highrollers — owner night-scores form (Streamlit + Google Sheets)
===========================================================================
Form order:  Type (RG / Oneoff)  →  Owner  →  Team Sales (Forms, Supports)
             →  Highrolling BA (or type a new BA name)  →  Highrolling BA (Forms, Supports)
             →  SignIn Date  →  Submit

Dropdown data comes from the Donation Pilot Project's Admin sheets, read-only:
    • RG Admin sheet      — "Owners" (OWNCODE|OwnerName|…), "BAs" (OWNCODE|BACode|BAName|…)
    • One-Off Admin sheet — "Owners" (OWNCODE|OwnerName|Client|…), "BAs" (OWNCODE|BACode|BAName|Client|…)
      An One-Off OWNCODE can have several Owners rows (one per Client); it is shown
      once, and its BA dropdown lists that owner's BAs across all Clients.

Each submit appends one row to the first worksheet of the Scores sheet (header
row is written automatically if the sheet is empty):
    Timestamp, Type, SignIn Date, OWNCODE, OwnerName, Highroller BA Name,
    Highroller BA Code, Team Forms, Team Supports, Team ADS,
    Highroller Forms, Highroller Supports, Highroller ADS

ADS is computed, never typed:
    Oneoff → Supports ÷ Forms
    RG     → Supports × 8

Run:
    python -m pip install -r requirements.txt
    (fill .streamlit/secrets.toml — see secrets.toml.example)
    python -m streamlit run app.py
"""

import os
import time
from datetime import datetime, timedelta, timezone

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

import ui_theme

LOGO_FILE = "logo.png"
SECRETS_SECTION = "google_sheets"
SERVICE_ACCOUNT_SECTION = "gcp_service_account"
RG, ONEOFF = "RG", "Oneoff"
TYPES = [RG, ONEOFF]
# secrets keys for each type's Admin sheet — RG also accepts the Donation app's own key name
ADMIN_SHEET_KEYS = {RG: ("rg_admin_sheet_id", "admin_sheet_id"), ONEOFF: ("oneoff_admin_sheet_id",)}
SCORES_SHEET_KEY = "scores_sheet_id"
RG_ADS_MULTIPLIER = 8
HEADERS = ["Timestamp", "Type", "SignIn Date", "OWNCODE", "OwnerName", "Highroller BA Name",
           "Highroller BA Code", "Team Forms", "Team Supports", "Team ADS",
           "Highroller Forms", "Highroller Supports", "Highroller ADS"]
BA_LABEL = "Select Highrolling BA from Your Team For Highroller Poster"
IST = timezone(timedelta(hours=5, minutes=30))
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

st.set_page_config(
    page_title="Scores and Highrollers",
    page_icon=LOGO_FILE if os.path.exists(LOGO_FILE) else "🏆",
    layout="centered",
)


# --------------------------------------------------------------------------- #
#  Google Sheets connection (service account from Streamlit secrets)
# --------------------------------------------------------------------------- #
def _has_secret(section):
    """Safely check for a secrets section. Returns False when no secrets.toml
    exists, instead of raising StreamlitSecretNotFoundError."""
    try:
        return section in st.secrets
    except Exception:  # noqa: BLE001 — no secrets file / not configured
        return False


def get_gc():
    """Return an authorized gspread client (cached per session)."""
    if "gc" not in st.session_state:
        creds = ServiceAccountCredentials.from_service_account_info(
            dict(st.secrets[SERVICE_ACCOUNT_SECTION]), scopes=SCOPES,
        )
        st.session_state.gc = gspread.authorize(creds)
    return st.session_state.gc


def sheet_id(*keys):
    cfg = st.secrets[SECRETS_SECTION]
    for k in keys:
        if cfg.get(k):
            return cfg[k]
    st.error(f"**{keys[0]}** is missing from the `[{SECRETS_SECTION}]` secrets.")
    st.stop()


def _get_status_code(e):
    """Extract HTTP status code from a gspread APIError."""
    if hasattr(e, "response") and hasattr(e.response, "status_code"):
        return e.response.status_code
    for code in (429, 401, 403, 500, 503):
        if str(code) in str(e):
            return code
    return None


# --------------------------------------------------------------------------- #
#  Owners + BAs from the RG / One-Off Admin sheet (cached 2 min)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=120, show_spinner="Loading owners…")
def load_owners(kind):
    sh = get_gc().open_by_key(sheet_id(*ADMIN_SHEET_KEYS[kind]))

    def sheet_rows(ws_name):
        values = sh.worksheet(ws_name).get_all_values()
        if not values:
            return []
        headers = values[0]
        return [dict(zip(headers, row)) for row in values[1:]]

    # one entry per OWNCODE (One-Off repeats an owner once per Client)
    owner_name_by_code = {}
    for r in sheet_rows("Owners"):
        c = str(r.get("OWNCODE", "")).strip()
        if c:
            owner_name_by_code.setdefault(c, str(r.get("OwnerName", "")).strip())

    ba_by_code = {}
    for r in sheet_rows("BAs"):
        c = str(r.get("OWNCODE", "")).strip()
        name = str(r.get("BAName", "")).strip()
        bacode = str(r.get("BACode", "")).strip()
        if not c or not name:
            continue
        ba_by_code.setdefault(c, [])
        if name not in [t[0] for t in ba_by_code[c]]:
            ba_by_code[c].append((name, bacode))
    for c in ba_by_code:
        ba_by_code[c] = sorted(ba_by_code[c], key=lambda t: t[0].lower())

    label_by_code = {
        c: (f"{nm}  ·  {c}" if nm else c)
        for c, nm in sorted(owner_name_by_code.items(), key=lambda t: (t[1] or t[0]).lower())
    }
    return {"label_by_code": label_by_code,
            "code_by_label": {v: k for k, v in label_by_code.items()},
            "owner_name_by_code": owner_name_by_code,
            "ba_by_code": ba_by_code}


# --------------------------------------------------------------------------- #
#  ADS + saving
# --------------------------------------------------------------------------- #
def compute_ads(kind, forms, supports):
    """Oneoff → Supports ÷ Forms; RG → Supports × 8. None while inputs are incomplete."""
    if supports is None:
        return None
    if kind == RG:
        return round(supports * RG_ADS_MULTIPLIER, 2)
    if not forms:
        return None
    return round(supports / forms, 2)


def fmt_number(v):
    """Plain string for a sheet cell, without a spurious trailing .0 for whole numbers."""
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else str(round(f, 2))


def append_score_row(row, max_attempts=6):
    """Appends `row` to the Scores sheet, writing the header row first if the
    sheet is empty. Backs off and retries on rate limits."""
    notice = st.empty()
    try:
        for attempt in range(max_attempts):
            try:
                ws = get_gc().open_by_key(sheet_id(SCORES_SHEET_KEY)).sheet1
                if not ws.row_values(1):
                    ws.update([HEADERS], "A1")
                ws.append_row(row, value_input_option="USER_ENTERED", table_range="A1")
                return
            except gspread.exceptions.APIError as e:
                code = _get_status_code(e)
                if code in (429, 500, 503) and attempt < max_attempts - 1:
                    wait = 2 ** attempt
                    notice.warning(
                        f"High traffic detected — retrying in {wait} second{'s' if wait > 1 else ''}. "
                        f"Please do not close this tab."
                    )
                    time.sleep(wait)
                elif code == 401 and attempt == 0:
                    st.session_state.pop("gc", None)
                else:
                    raise
    finally:
        notice.empty()


# --------------------------------------------------------------------------- #
#  Guard
# --------------------------------------------------------------------------- #
if not (_has_secret(SERVICE_ACCOUNT_SECTION) and _has_secret(SECRETS_SECTION)):
    st.error(
        "Google Sheets secrets not found. Fill **.streamlit/secrets.toml** "
        "(see `.streamlit/secrets.toml.example`), or add them in Streamlit Cloud."
    )
    st.stop()

ui_theme.apply_theme()

st.session_state.setdefault("nonce", 0)          # bumped after a successful submit to clear the form
st.session_state.setdefault("flash_success", None)
n = st.session_state.nonce

ui_theme.render_header("Scores and Highrollers", "Team sales + Highrolling BA · source: Google Sheets",
                       logo_path=LOGO_FILE)

if st.session_state.flash_success:
    st.success(st.session_state.flash_success)
    st.session_state.flash_success = None

# ---- 1) Type ----
kind = st.radio("1 · Type *", TYPES, index=None, horizontal=True, key=f"kind_{n}")
if not kind:
    st.info("Select **RG** or **Oneoff** to continue.")
    st.stop()

try:
    A = load_owners(kind)
except Exception as e:  # noqa: BLE001
    st.error(f"Couldn't load {kind} owners from Google Sheets: {e}")
    st.stop()

# ---- 2) Owner (key includes the type so it resets when the type changes) ----
owner_label = st.selectbox(
    f"2 · {kind} Owner Name *",
    list(A["label_by_code"].values()),
    index=None,
    placeholder="Search owner name or code…",
    key=f"owner_{kind}_{n}",
)
code = A["code_by_label"].get(owner_label) if owner_label else None
if not code:
    st.info("Select the **Owner** to continue.")
    st.stop()
owner_name = A["owner_name_by_code"].get(code, "")


def scores_inputs(prefix, who):
    # keys include type + owner so the numbers clear when a different owner is picked
    c1, c2 = st.columns(2)
    forms = c1.number_input(f"{who} Forms *", min_value=0, step=1, value=None,
                            placeholder="0", key=f"{prefix}_forms_{kind}_{code}_{n}")
    supports = c2.number_input(f"{who} Supports *", min_value=0.0, step=1.0, value=None,
                               format="%.2f", placeholder="0.00", key=f"{prefix}_supports_{kind}_{code}_{n}")
    ads = compute_ads(kind, forms, supports)
    rule = f"Supports × {RG_ADS_MULTIPLIER}" if kind == RG else "Supports ÷ Forms"
    st.caption(f"ADS ({rule}): **{fmt_number(ads) if ads is not None else '—'}**")
    return forms, supports, ads


# ---- 3) Team Sales — shown as soon as the owner is picked ----
with st.container(border=True):
    st.markdown(f"**👥 3 · Team Sales** — {owner_name or code}")
    team_forms, team_supports, team_ads = scores_inputs("team", "Team")

# ---- 4) Highrolling BA, only from this owner's team ----
ba_pairs = A["ba_by_code"].get(code, [])
ba_labels = [f"{nm}  ·  {cd}" if cd else nm for nm, cd in ba_pairs]
label_to_ba = dict(zip(ba_labels, ba_pairs))
new_ba_key = f"newba_{kind}_{code}_{n}"
new_ba_typed = bool(str(st.session_state.get(new_ba_key, "") or "").strip())
if new_ba_typed:
    ba_ph = "Disabled — you're typing a new BA name below"
elif ba_labels:
    ba_ph = "Search BA name or code…"
else:
    ba_ph = "No BAs mapped for this owner — type the name below"
ba_label = st.selectbox(
    f"4 · {BA_LABEL} *",
    ba_labels,
    index=None,
    placeholder=ba_ph,
    disabled=not ba_labels or new_ba_typed,
    key=f"ba_{kind}_{code}_{n}",
)
# a BA missing from the Admin sheet — saved with this row only, BA Code left blank
new_ba_name = " ".join(st.text_input(
    "BA not in the list? Type the BA name", key=new_ba_key, placeholder="Full name",
).split())
if new_ba_name:
    # typed a name that is in the list after all → use that BA (and its code)
    existing = {nm.lower(): (nm, cd) for nm, cd in ba_pairs}
    ba_name, ba_code = existing.get(new_ba_name.lower(), (new_ba_name, ""))
elif ba_label:
    ba_name, ba_code = label_to_ba[ba_label]
else:
    st.info("Select the **Highrolling BA**, or type their name if they're not in the list, to continue.")
    st.stop()

# ---- 5) Highrolling BA's Forms + Supports — shown once the BA is picked ----
with st.container(border=True):
    st.markdown(f"**🏆 5 · Highrolling BA** — {ba_name}")
    hr_forms, hr_supports, hr_ads = scores_inputs("hr", "Highroller")

# ---- 6) SignIn Date ----
signin = st.date_input("6 · SignIn Date *", value=None, format="YYYY-MM-DD", key=f"signin_{n}")
if not signin:
    st.info("Select the **SignIn Date** to continue.")
    st.stop()

if st.button("✅ Submit", type="primary", use_container_width=True):
    errors = []
    for who, forms, supports in (("Team", team_forms, team_supports),
                                 ("Highrolling BA", hr_forms, hr_supports)):
        if forms is None or forms < 1:
            errors.append(f"**{who} Forms** must be 1 or more.")
        if supports is None:
            errors.append(f"**{who} Supports** is required.")
    if errors:
        for e in errors:
            st.error(e)
    else:
        row = [
            datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), kind, signin.isoformat(), code,
            A["owner_name_by_code"].get(code, ""), ba_name, ba_code,
            fmt_number(team_forms), fmt_number(team_supports), fmt_number(team_ads),
            fmt_number(hr_forms), fmt_number(hr_supports), fmt_number(hr_ads),
        ]
        try:
            with st.spinner("Saving to Google Sheets…"):
                append_score_row(row)
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't save to the Scores sheet: {e}")
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.caption(
                    "**403 / permission denied** — share the Scores sheet with the "
                    "service-account email as **Editor**."
                )
        else:
            st.session_state.flash_success = (
                f"✅ Saved {kind} scores for {A['owner_name_by_code'].get(code) or code} "
                f"({signin:%d %b %Y}) — Highrolling BA: {ba_name}."
            )
            st.session_state.nonce += 1
            st.rerun()
