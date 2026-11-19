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

## Use Supabase for the database
ClubHub uses its existing Flask authentication and SQLAlchemy models; Supabase provides PostgreSQL storage.
The app does not use Supabase Auth or the Supabase Data API. Accounts, project data, settings, and resized
photos are stored in the database.

### Connect the existing local dataset
The current local database is `instance/club.db`. Create a Supabase project, then open **Connect** in its
dashboard and copy the **Session pooler** connection string (port `5432`). The Session pooler is suitable
for this long-running Flask/Gunicorn service on Render's IPv4 network. Keep the password private and
percent-encode reserved characters in it.

Set `SUPABASE_DATABASE_URL` in your local shell to that connection string, then run a dry run:

```bash
python scripts/migrate_sqlite_to_supabase.py
```

Review the printed row counts, then run the import and type `IMPORT` when prompted:

```bash
python scripts/migrate_sqlite_to_supabase.py --apply
```

The importer refuses to copy into a destination that already has ClubHub rows. It copies the application
tables, including password hashes and photo data, adjusts PostgreSQL ID sequences, and enables RLS on the
app tables. Back up the SQLite file before migration. The importer does not print credentials or member data.

### Deploy on Render
1. Push the project to a private GitHub repository (`.env` and `*.db` are git-ignored).
2. In Render, create a Blueprint from the repository or create a Python Web Service with the commands in
   `render.yaml`.
3. Set `DATABASE_URL` to the same Supabase Session pooler URL. Set `OWNER_NAME`, `OWNER_EMAIL`, and
   `OWNER_PASSWORD` only if you need a new Owner account; remove `OWNER_PASSWORD` after first login.
   `SUPABASE_ENABLE_RLS=true` enables Row Level Security on the app's public tables. The Flask server
   connects as the database owner and enforces ClubHub permissions; RLS without client policies blocks
   direct Data API access. Keep the database URL server-side and do not put a Supabase secret key in browser
   code.
4. Deploy and verify `/healthz`, then sign in and confirm the migrated records are present.

If the project will only be accessed through this Flask backend, you can also disable the Supabase Data API
in the Supabase dashboard. If you later expose tables to the Data API, add and review RLS policies for the
intended client access before enabling it.

Render's free service may sleep after inactivity. Supabase database availability and limits depend on the
selected Supabase plan; check the project dashboard for current usage and backup options.

### Persistence checklist
- Accounts, projects, tasks, marks, notes, leaderboard settings, and photos live in Supabase Postgres.
- Back up using Supabase's dashboard backup options or `pg_dump` over a direct connection. The Session
  pooler is for app connections; use a direct connection for database migrations and backup tools.
- Set `SUPABASE_ENABLE_RLS=true` in production. If a new table is added later, ensure it is covered by the
  RLS startup setup and has no unintended Data API grants or policies.

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
wsgi.py · render.yaml · requirements.txt · .env.example · scripts/migrate_sqlite_to_supabase.py
```
