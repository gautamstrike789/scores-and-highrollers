# Scores and Highrollers

Streamlit form for owners to report a night's team sales and their Highrolling BA
(for the Highroller Poster). Owners and BAs come from the Donation Pilot Project's
RG and One-Off Admin sheets (read-only); each submit appends one row to the Scores sheet.

Form order: **Type (RG / Oneoff) → Owner → Highrolling BA (that owner's team only)
→ SignIn Date → Team Sales tab (Forms, Supports) → Highrolling BA tab (Forms, Supports) → Submit**

Saved columns:
`Timestamp, Type, SignIn Date, OWNCODE, OwnerName, Highroller BA Name, Highroller BA Code,
Team Forms, Team Supports, Team ADS, Highroller Forms, Highroller Supports, Highroller ADS`

**Owner passwords:** the first time an owner is picked, the form asks them to set a
password (typed twice, min 4 characters); after that it asks for it before showing
anything else, once per browser session. Passwords are stored in this Scores sheet's
own **Passwords** tab (created automatically), not in the Admin sheets, and one password
covers the owner under both RG and Oneoff. To reset an owner, clear their Password cell
or delete their row; they'll be asked to set a new one.

If the BA isn't in the dropdown, type their name in **"BA not in the list?"** — it's saved
with that row only (BA Code blank); the Admin sheet is not changed.

ADS is calculated, not typed: **Oneoff = Supports ÷ Forms**, **RG = Supports × 8**.

## Local run

```powershell
python -m pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # then fill in the IDs + service account
python -m streamlit run app.py
```

## Setup

1. Create an empty Google Sheet for the scores (the header row is written on the first submit).
2. Share it with the service account email as **Editor**. The RG and One-Off Admin
   sheets only need **Viewer** (they're already shared if you reuse the Donation app's service account).
3. Put the three sheet IDs and the service account block in `.streamlit/secrets.toml`,
   or in the app's Secrets on Streamlit Community Cloud (main file `app.py`).
