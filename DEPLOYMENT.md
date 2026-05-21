# Deploying to Streamlit Community Cloud

This guide walks you through getting the validator app live at a permanent URL like `https://your-app-name.streamlit.app`. **No Git or command-line knowledge required** — we'll do everything through the GitHub web UI and the Streamlit Cloud dashboard.

Total time: about 25–40 minutes the first time. After that, updates take 2 minutes each.

---

## Before you start: five things to know

1. **Streamlit Community Cloud is free**, but the free tier requires a **public** GitHub repository. The code becomes visible to anyone on the internet (the data the app processes is not — only the `.py` files). For this validator, that's fine: there are no proprietary algorithms in the code itself.

2. **`secrets.toml` must NEVER end up in the GitHub repo.** It contains password hashes that, while expensive to brute-force, are still credentials. The `.gitignore` file in this folder excludes it automatically. You'll paste the secrets into Streamlit Cloud's separate "Secrets" textbox instead.

3. **Auto-sleep after 7 days of no traffic.** If nobody uses the app for a week straight, it goes to sleep. The first user to hit it then triggers a 20–30 second wake-up. For a team using it weekly, this is essentially invisible. If you need always-on with no cold starts, you'd move to Render or Railway paid tier (~$7/mo).

4. **Memory ceiling: ~1 GB.** Your real input file (818k rows, ~8 MB on disk) peaks around 200 MB during validation, so you have plenty of headroom. If you ever load files 5–10× larger you'll hit the limit and need a paid host.

5. **The URL stays the same forever** — until you delete the app from Streamlit Cloud. Bookmark it, share it.

---

## Phase 1 — Create a GitHub account & repository (10 minutes)

### Step 1.1 — Sign up for GitHub

If you already have a GitHub account, skip to Step 1.2.

1. Go to **https://github.com/signup**
2. Use your work email or a personal one — your choice. The team won't see it.
3. Pick a username. Something like `narabhi` or `narabhi-work` is fine.
4. Verify your email (GitHub sends a code).

### Step 1.2 — Create a new repository

1. Once signed in, click the green **"New"** button on your dashboard (top-left), OR go directly to **https://github.com/new**.
2. Fill in:
   - **Repository name**: `forecast-disagg-validator` (or any name you like)
   - **Description** (optional): "Forecast disaggregation validation tool"
   - **Public/Private**: Select **Public**. Streamlit Cloud free tier requires this.
   - **Initialize this repository with**: Leave all three checkboxes **unchecked** (we'll upload files in Step 1.3).
3. Click the green **"Create repository"** button at the bottom.

You'll land on a page that says "Quick setup — if you've done this kind of thing before". Ignore the command-line instructions. Look for the line that says **"uploading an existing file"** — that's a clickable link.

### Step 1.3 — Upload the project files

1. Click **"uploading an existing file"** (or go to `https://github.com/YOUR_USERNAME/forecast-disagg-validator/upload/main`).
2. Drag and drop these files from the deliverable folder into the browser drop zone:
   - `app.py`
   - `auth_gate.py`
   - `add_user.py`
   - `validator_engine.py`
   - `excel_exporter.py`
   - `requirements.txt`
   - `.gitignore`
   - `README.md`
   - `DEPLOYMENT.md` (this file)
   - `USER_GUIDE.md`
   - `FORECASTER_ACTION_PLAN.md`
3. **DO NOT** upload:
   - ❌ `.streamlit/secrets.toml` (your real secrets — this goes into Streamlit Cloud's dashboard, NOT GitHub)
   - ❌ Any `.xlsx` data files
   - ❌ Any `__pycache__/` folders
4. **DO** upload the `.streamlit/` folder containing only:
   - ✅ `.streamlit/config.toml`
   - ✅ `.streamlit/secrets.toml.template`

   To upload a folder structure: drag the entire `.streamlit` folder (with just those two files inside) into the drop zone. GitHub preserves the folder.
5. Scroll down. In the **"Commit changes"** box:
   - Title: `Initial commit`
   - Leave description empty
   - Make sure **"Commit directly to the `main` branch"** is selected
6. Click the green **"Commit changes"** button.

You'll be redirected to the repo's main page. You should see a file list with `app.py`, `auth_gate.py`, etc. The `.streamlit/` folder should show as a folder you can click into.

### Step 1.4 — Verify what's in the repo

Click around and confirm:

- ✅ `app.py` is at the root
- ✅ `requirements.txt` is at the root
- ✅ `.streamlit/config.toml` is in the `.streamlit` folder
- ✅ `.streamlit/secrets.toml.template` is in the `.streamlit` folder
- ❌ There is **NO** file called `.streamlit/secrets.toml` (no `.template` suffix). If you see one, click it, click the trash-can icon to delete it, commit, and re-verify. **This is critical** — secrets.toml in a public repo is a security leak.

---

## Phase 2 — Deploy to Streamlit Cloud (10 minutes)

### Step 2.1 — Sign in to Streamlit Cloud

1. Go to **https://share.streamlit.io/**
2. Click **"Continue with GitHub"** (or "Sign in with GitHub")
3. Authorize Streamlit to read your repositories. Streamlit needs this to pull the code.

### Step 2.2 — Create a new app

1. Click the blue **"Create app"** button (top right).
2. Streamlit will ask: *"Do you already have an app?"* — click **"Yup, I have an app"**.
3. Fill in the form:
   - **Repository**: Pick `YOUR_USERNAME/forecast-disagg-validator` from the dropdown.
   - **Branch**: `main` (the default).
   - **Main file path**: `app.py`
   - **App URL**: You can customize this. Streamlit suggests `your-app-name.streamlit.app`. Pick something memorable — like `acme-forecast-validator`. This is the URL you'll send to users.
4. **DO NOT click "Deploy" yet.** Click **"Advanced settings…"** first.

### Step 2.3 — Paste the secrets

This is the most important step. Streamlit Cloud stores secrets in its own dashboard — they never touch GitHub.

1. In the Advanced Settings panel, find the **"Secrets"** section.
2. You'll see a textbox that looks like a code editor.
3. Generate the secrets locally first. Open a terminal on your machine and run (you only need to do this once):

   ```bash
   # Install bcrypt
   pip install bcrypt

   # Generate a hash for each user (run once per user)
   python add_user.py alice
   # → prompts for password, prints: alice = "$2b$12$..."

   python add_user.py bob
   # → alice = "$2b$12$..."

   # Generate the cookie signing key
   python add_user.py --new-cookie-key
   # → cookie_signing_key = "..."
   ```

4. Paste the following into the Secrets textbox, replacing each placeholder with the real value from step 3:

   ```toml
   [auth]
   session_hours = 8
   max_failed_attempts = 5
   lockout_minutes = 15
   cookie_signing_key = "PASTE_THE_REAL_COOKIE_KEY_HERE"

   [auth.users]
   alice = "PASTE_THE_REAL_HASH_FOR_ALICE_HERE"
   bob   = "PASTE_THE_REAL_HASH_FOR_BOB_HERE"
   # add more users by running `python add_user.py <name>` and pasting the line here
   ```

5. Click **"Save"** at the bottom of Advanced Settings.

### Step 2.4 — Deploy

1. Click the blue **"Deploy"** button.
2. You'll see a console-like view streaming the deploy logs. It runs `pip install -r requirements.txt`, then `streamlit run app.py`. First deploy takes 2–4 minutes.
3. When you see *"You can now view your Streamlit app in your browser"*, the app is live.
4. Click the **"Manage app"** button (bottom right) to find your public URL, or just navigate to `https://your-app-name.streamlit.app` directly.

### Step 2.5 — Sanity-check the deployed app

1. Open the URL in a fresh browser tab (or incognito window — useful for testing as a "new user").
2. You should see the login screen.
3. Try logging in with one of the credentials you set in Step 2.3.
4. After login, upload your Excel file. Run a validation. Confirm it produces the expected results.

If you see "Authentication is not configured" instead of the login screen, your secrets weren't saved properly. Go back to Advanced Settings, paste them again, and click "Reboot app".

---

## Phase 3 — Share the URL with your team (2 minutes)

1. Send the URL (`https://your-app-name.streamlit.app`) to your 5–10 users.
2. Send each user their username + password separately (don't put them in the same email).
3. Tell them about the auto-sleep behavior: *"If nobody's used it in over a week, the first person to open it may wait ~30 seconds for it to wake up. After that, it's instant."*

That's it. The URL is permanent. The app survives your laptop being offline, your Colab session being killed, anything — Streamlit Cloud runs it on their servers.

---

## Common operations after deployment

### Adding a new user

1. On your local machine, run: `python add_user.py charlie`
2. Copy the line it outputs.
3. Go to **https://share.streamlit.io/** → click your app → click "⋮" menu → "Settings" → "Secrets".
4. Find the `[auth.users]` section and add the new line.
5. Click "Save". Streamlit will reboot the app automatically (~30 seconds).
6. The new user can now sign in.

### Removing a user

Same as above, but delete their line from `[auth.users]` and click Save.

### Changing a user's password

Same as adding — run `python add_user.py alice` again, paste the *new* hash to *replace* the old line for that user.

### Updating the code

1. On your local machine, edit the file (e.g. `app.py`).
2. Go to your GitHub repo in the browser.
3. Click the file you changed (e.g. `app.py`).
4. Click the pencil icon (top right of the file view) to edit.
5. Paste the new contents over the old.
6. Scroll down → "Commit changes" → green button.
7. Streamlit Cloud detects the change within ~30 seconds and auto-redeploys. The URL stays the same.

For larger changes, you can also re-upload files via the "Add file → Upload files" button on the repo page.

### Checking app logs

Sign in to **https://share.streamlit.io/** → click your app → you'll see live logs at the bottom. Useful when debugging.

### Rebooting the app manually

If something's stuck: app dashboard → "Manage app" → "⋮" → "Reboot app". Takes ~30 seconds.

---

## What if something breaks

**"This site can't be reached"** when opening the URL
→ The app may be asleep (no traffic for 7 days). Wait 30 seconds and refresh. If still broken, sign in to Streamlit Cloud and click "Reboot app".

**"Authentication is not configured"**
→ Secrets aren't set in Streamlit Cloud's dashboard. Go to app settings → Secrets → paste the full `[auth]` and `[auth.users]` block → Save.

**"Module not found: bcrypt"** (or any other module)
→ Check that `requirements.txt` is in the repo root, contains the module, and the spelling matches. Then reboot.

**Login form looks weird or styles are missing**
→ The `.streamlit/config.toml` file might not have been uploaded. Verify it's in the repo at `.streamlit/config.toml` (in the `.streamlit` folder, not the root).

**Users report it's slow on first hit**
→ Expected if it just woke from sleep. After the first hit it's responsive. If it's persistently slow, check the logs for memory pressure (Streamlit Cloud free tier has ~1 GB).

**You accidentally committed `secrets.toml` to GitHub**
→ This is bad. Do these immediately, in order:
  1. Regenerate all bcrypt hashes (`python add_user.py <name>` for each user) so the leaked hashes become useless
  2. Regenerate the cookie signing key
  3. Update the Streamlit Cloud secrets with the new values
  4. Delete the bad file from GitHub: navigate to it, click the trash icon, commit the deletion
  5. (Optional, advanced) Purge the file from Git history using GitHub's instructions for "removing sensitive data from a repository"
  6. Verify `.gitignore` correctly lists `.streamlit/secrets.toml` so it doesn't happen again

---

## Comparison vs. what you had before

| Aspect | Colab + ngrok (before) | Streamlit Cloud (now) |
|---|---|---|
| **URL** | Rotates on every restart | Permanent |
| **Uptime** | Tied to your Colab session | 24/7 (auto-sleeps if idle 7 days, wakes in ~30s) |
| **Survives laptop shutdown** | ❌ No | ✅ Yes |
| **Survives Colab session timeout** | ❌ No | ✅ Yes (no Colab involved) |
| **Cost** | $0 | $0 |
| **Session length** | 8 hours (from auth gate) | 8 hours (same) |
| **Max users at once** | A few, limited by Colab | Comfortable for 5–10 |
| **Setup once** | Each new Colab session | One-time, then forget |
| **Updates** | Re-upload to Drive, restart cell | Edit on GitHub, auto-deploys |

---

## The next steps you can take later (none required)

- **Custom domain** like `forecast.yourcompany.com` instead of `yourapp.streamlit.app` — Streamlit Cloud supports this on their paid plan ($25/mo per app).
- **Always-on (no sleep)** — Move to Render or Railway paid tier (~$7/mo) for instant response even after a long quiet period.
- **Real SSO** (Google Workspace login instead of usernames) — would require swapping the auth gate for an OAuth integration. Out of scope for this version.
- **Private repository** — Streamlit Cloud paid plan ($25/mo) allows private repos. Free tier requires public.

For now you have everything you need: permanent URL, free hosting, persistent auth, survives your laptop being offline. That covers the original ask.
