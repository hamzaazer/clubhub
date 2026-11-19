# ClubHub — club management website (Flask)

Three roles — **Owner**, **Admin**, **Member** — with registration approval, projects, scoring criteria,
marks and notes, tasks with member replies, and a leaderboard whose first place an admin can set.

## What each role can do
| Role | Capabilities |
|---|---|
| **Owner** | Everything an admin can do, plus: add/edit/remove admins and set their permissions, rename the club, remove members and all their data. Created from environment variables (see below), never through the sign-up form. |
| **Admin** | Permissions are switched on per admin: *approve members* (registrations, name/email changes, password resets), *manage projects* (participants, criteria with max marks, marks, contributions, per-participant notes), *manage tasks* (send to one or many members, read replies), *manage leaderboard* (bonus points, choose first place). All admins can view member profiles, participation and marks. |
| **Member** | Signs up (name, email, phone, photo, address, equipment) and waits for approval. Then: edit phone/address/photo/equipment (name or email changes wait for admin approval), see tasks and send replies/progress, see projects, marks and notes, see leaderboard position. |

## Run it on your computer
```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # then edit the values
export $(grep -v '^#' .env | xargs)                      # Windows: set the variables manually
flask --app wsgi run                                     # open http://127.0.0.1:5000
```
Leave `DATABASE_URL` empty to use a local SQLite file. On first start the tables are created and the
Owner account is created from `OWNER_EMAIL` / `OWNER_PASSWORD`. You can also run
`flask --app wsgi create-owner`.

## Security built in
Hashed passwords (Werkzeug), CSRF protection on every form, login rate limiting (10 attempts/minute/IP),
secure/HTTP-only/SameSite cookies, HTTPS-only cookies and HSTS in production, strict Content-Security-Policy,
server-side validation on every form, uploaded images re-encoded and resized (no raw uploads are stored),
role/permission checks on every admin route, profile photos visible only to logged-in users.

## Deploy online (free): Render + Neon
**Why this pair.** Render runs the Python app for free, with free custom domains and managed HTTPS.
Render's disk is wiped on every deploy/restart, and its free Postgres expires after 30 days, so the
data lives in **Neon** (free Postgres with no expiry). Profile photos are stored *inside the database*
(resized to ~50 KB each), so nothing important is on Render's disk.

Free-tier trade-offs: the app sleeps after 15 minutes without visitors and takes ~1 minute to wake up;
the database also sleeps after 5 idle minutes and wakes in seconds. Upgrading Render to a paid instance
(about $7/month at the time of writing) removes the sleep.

### Step 1 — Put the code on GitHub
Create a private repository and push this folder (`.env` and `*.db` are git-ignored).

### Step 2 — Create the database (Neon)
1. Sign up at neon.com (no card) → **Create project** (pick a region near your members).
2. Click **Connect**, tick **Pooled connection**, copy the connection string. It looks like
   `postgresql://user:password@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require`.
   If you get an SSL/`channel_binding` error, delete `&channel_binding=require` from the string.

### Step 3 — Create the web service (Render)
1. render.com → **New → Blueprint** → select your repo (it reads `render.yaml`), **or** **New → Web Service** with:
   Runtime *Python 3*, Build `pip install -r requirements.txt`,
   Start `gunicorn wsgi:app --workers 1 --threads 4 --timeout 60`, Instance type *Free*,
   Health check path `/healthz`.
2. Add these environment variables:

| Variable | Value |
|---|---|
| `FLASK_ENV` | `production` (turns on secure cookies, HSTS, requires `SECRET_KEY`) |
| `SECRET_KEY` | long random string (`python -c "import secrets;print(secrets.token_hex(32))"`); the Blueprint generates one |
| `DATABASE_URL` | the Neon connection string from Step 2 |
| `OWNER_NAME`, `OWNER_EMAIL`, `OWNER_PASSWORD` | your Owner login (created automatically if no Owner exists) |
| `PYTHON_VERSION` | `3.12.7` |

3. Deploy. Tables are created automatically on first start. Open the `https://<name>.onrender.com`
   address, log in as Owner, then use **Password** to change it and remove `OWNER_PASSWORD` from Render.

### Step 4 — Custom domain + HTTPS
1. Buy a domain at any registrar (the only unavoidable cost, usually ~$10–15/year).
2. Render → your service → **Settings → Custom Domains → Add** (add both `example.com` and `www.example.com`).
3. At your registrar's DNS page create exactly the records Render shows: normally a **CNAME** for `www`
   pointing to `<name>.onrender.com`, and for the bare domain an **A/ALIAS** record with the value Render gives.
   Delete any old A/AAAA records on the same names.
4. Click **Verify** in Render. When DNS propagates (minutes to a few hours) Render issues and renews the
   HTTPS certificate automatically and redirects HTTP to HTTPS. No code change is needed.

### Persistence checklist
- Accounts, projects, tasks, marks, notes, leaderboard settings **and photos** → Neon Postgres. Redeploys,
  restarts and sleep never touch them.
- Back up occasionally: `pg_dump "$DATABASE_URL" > backup.sql`.
- Free Neon limits: roughly 0.5–1 GB storage and 100 compute-hours/month (see neon.com pricing) —
  far more than a club needs. If a free limit is hit, Neon suspends compute until the next month.

### Updating the app
Push to GitHub; Render redeploys. `create_all()` only creates *missing tables*. The app also adds the
`member_title` column to existing databases on startup and imports existing member titles into the club role
list, plus place of work and Algerian wilaya/commune fields. Owners manage club roles; members choose from
those roles and select their wilaya and commune when joining or editing their profile. Admins can filter
the member list by club role. Owners can change the club name and logo in Settings. Owners manage global scoring criteria in Settings; those criteria apply to
current projects and are copied into future projects. Admins can manage homepage copy, events, leaders, collaborations,
and community photos from Website in the admin menu. The bundled location data follows the 2026 administrative
division and is distributed under MIT from [Algeria-wilayas](https://github.com/islam-re/Algeria-wilayas).
For other schema changes, use Flask-Migrate or an `ALTER TABLE` statement.

## Project layout
```
app/__init__.py   app factory, security headers, error pages, Owner seeding
app/models.py     database tables, leaderboard logic
app/forms.py      validated forms        app/utils.py   permissions + image processing
app/auth.py       login, join, avatar    app/member.py  member area
app/admin.py      admin area             app/owner.py   owner-only area
app/templates/    pages                  app/static/    CSS + tiny JS
wsgi.py · render.yaml · requirements.txt · .env.example
```
