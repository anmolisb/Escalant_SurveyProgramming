# Deploying the app, step by step

Follow in order. Each step says what to type and what you should see. If
what you see is different, stop there rather than carrying on.

Total time about 45 minutes, most of it waiting.

---

## Part 1 — Prepare the repository (on your laptop, 10 minutes)

### 1.1 Put the deployment files in place

Unzip the bundle. From it, copy into
`C:\ISB-Capstone\Escalant_SurveyProgramming\`:

    Dockerfile
    docker-compose.yml
    .dockerignore
    .env.example
    setup-server.sh
    README_DEPLOY.md
    RUNBOOK.md

And replace two existing files:

    app.py          ->  src\dashboard\app.py
    run_browser.py  ->  src\agents\respondent_bot\run_browser.py

### 1.2 Check the app still runs locally

    cd C:\ISB-Capstone\Escalant_SurveyProgramming
    python -m streamlit run src/dashboard/app.py

It should behave exactly as before. The two changed files only read an
environment variable that is not set on your machine, so the old default
applies. Close it with Ctrl+C.

### 1.3 Make sure .env can never be committed

Open `.gitignore` and check these lines are in it. Add them if not:

    .env
    out/
    data/platform.db

### 1.4 Commit and push

    git add Dockerfile docker-compose.yml .dockerignore .env.example setup-server.sh README_DEPLOY.md RUNBOOK.md
    git add src/dashboard/app.py src/agents/respondent_bot/run_browser.py
    git commit -m "Deployment: container, compose, and server setup"
    git push

### 1.5 Note your repository URL

You need it in Part 3. It looks like:

    https://github.com/anmolisb/Escalant_SurveyProgramming.git

**If the repository is private**, the server cannot clone it with that URL
alone. Either make it public for now, or create a GitHub personal access
token (Settings, Developer settings, Tokens, classic, scope `repo`) and
use:

    https://<token>@github.com/anmolisb/Escalant_SurveyProgramming.git

---

## Part 2 — Create the server (10 minutes)

### 2.1 Make an SSH key, if you do not already have one

In PowerShell:

    ssh-keygen -t ed25519 -C "anoop-capstone"

Press Enter three times to accept the default path and no passphrase.

Then print the public half, which you will paste into Hetzner:

    type $env:USERPROFILE\.ssh\id_ed25519.pub

It is one line starting `ssh-ed25519 AAAA...`. Copy the whole line.

### 2.2 Sign up at Hetzner

1. Go to **console.hetzner.cloud**
2. Sign up. It asks for a card and may take a few minutes to verify.
3. Once in, click **+ New Project**, call it `capstone`, open it.

### 2.3 Create the server

Click **Add Server**, then:

| Field | Choose |
|---|---|
| Location | **Nuremberg** or **Helsinki** |
| Image | **Ubuntu 24.04** |
| Type | **Shared vCPU**, **x86**, then **CX22** |
| Networking | leave IPv4 and IPv6 ticked |
| SSH keys | **Add SSH key**, paste the line from 2.1, name it, Add |
| Volumes, firewalls, backups | skip for now |
| Name | `survey-qa` |

CX22 is 2 vCPU, 4 GB, about €4.50 a month. Do not take CX11 or anything
with 2 GB: Chromium plus LimeSurvey plus MySQL will not fit.

Click **Create & Buy now**.

### 2.4 Note the IP address

The server appears with an IPv4 address like `91.99.12.34`. Copy it.

### 2.5 Connect

In PowerShell:

    ssh root@91.99.12.34

Type `yes` when it asks about the fingerprint. You should land at a prompt
like `root@survey-qa:~#`.

If it asks for a password, the SSH key did not attach. Easiest fix:
delete the server and create it again, making sure the key is ticked.

---

## Part 3 — Install the platform (15 minutes, mostly waiting)

### 3.1 Fetch the setup script

On the server. Replace the URL with your own repository's raw link:

    curl -fsSL https://raw.githubusercontent.com/anmolisb/Escalant_SurveyProgramming/main/setup-server.sh -o setup.sh

Check it arrived:

    head -3 setup.sh

You should see `#!/usr/bin/env bash`. If you get HTML or `404`, the URL is
wrong or the repository is private; in that case paste the file across
instead:

    nano setup.sh

then paste the contents, Ctrl+O, Enter, Ctrl+X.

### 3.2 Run it

One command, with your repository URL and your Groq key:

    REPO=https://github.com/anmolisb/Escalant_SurveyProgramming.git \
    GROQ_API_KEY=gsk_your_key_here \
    bash setup.sh

What happens, in order:

1. `1/5 system packages` — about 30 seconds
2. `2/5 docker` — about 2 minutes
3. `3/5 the repository` — seconds
4. `4/5 settings` — writes `.env` with generated passwords
5. `5/5 building and starting` — **this is the long one, 8 to 12 minutes.**
   It downloads the Playwright image, which is about 2 GB.

It finishes with `done` and a block of instructions.

### 3.3 Check it is running

    docker compose ps

Three containers, all `Up`. The `db` one should say `(healthy)`.

    curl -s http://127.0.0.1:8501/_stcore/health

Should print `ok`.

If a container says `Exited`, look at why:

    docker compose logs app --tail 40

### 3.4 Save the passwords

    cat /opt/survey-qa/.env

Copy the whole thing somewhere safe. **The LimeSurvey admin password
cannot be recovered** once the container is running; you would have to
delete its volume and start again.

---

## Part 4 — Reach it from your laptop (10 minutes)

### 4.1 Install Tailscale on the server

    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up

It prints a URL. Open it in your browser, sign in with Google or GitHub.
That account owns the network, so use one the team can share or one you
are happy to invite people from.

Back on the server it says `Success`.

### 4.2 Expose the two services on the tailnet

    tailscale serve --bg --https=443  http://127.0.0.1:8501
    tailscale serve --bg --https=8443 http://127.0.0.1:8080

Then:

    tailscale serve status

It prints the addresses, something like:

    https://survey-qa.tail1a2b3c.ts.net/        -> http://127.0.0.1:8501
    https://survey-qa.tail1a2b3c.ts.net:8443/   -> http://127.0.0.1:8080

Copy both.

### 4.3 Install Tailscale on your laptop

Download from **tailscale.com/download**, install, sign in with the same
account.

### 4.4 Open the app

In your browser, the first address from 4.2. The dashboard should load.

If it does not: check Tailscale says Connected on your laptop, and that
`tailscale status` on the server lists your laptop.

### 4.5 Add the rest of the team

On tailscale.com, Admin console, **Users**, **Invite external users**.
Send each of them a link. They install Tailscale, accept, and the same
address works for them.

---

## Part 5 — Put your work on it (10 minutes)

### 5.1 Copy your existing runs up

On your laptop:

    cd C:\ISB-Capstone\Escalant_SurveyProgramming
    scp -r out root@91.99.12.34:/opt/survey-qa/

That is a few hundred megabytes and takes a couple of minutes. Afterwards,
the corpus in the app shows everything you have locally.

### 5.2 Import your surveys into LimeSurvey

1. Open the `:8443` address from 4.2
2. Sign in: user `admin`, password from `.env` (`LIMESURVEY_ADMIN_PASSWORD`)
3. **Surveys**, **Create**, **Import survey**
4. Upload `out/S01_campus_cafeteria_experience_generated.lss` from your
   laptop
5. Open the imported survey and **Activate** it
6. **Note the survey id** it was given. It is in the URL and on the survey
   settings page, and it will not be 900001.

Repeat for any other survey you want to run checks against.

### 5.3 First run

In the app: open S01, go to **Respondent Bot**, put the survey id from 5.2
into the box, and run the checks. It should finish in about a minute with
38 of 41 passing.

---

## Running it from now on

All on the server, in `/opt/survey-qa`:

| What | Command |
|---|---|
| See what it is doing | `docker compose logs -f app` |
| Deploy new code | `git pull && docker compose up -d --build` |
| Restart after editing .env | `docker compose restart app` |
| Stop everything | `docker compose down` |
| Start again | `docker compose up -d` |
| Disk space | `df -h` |

---

## If something goes wrong

**The app will not load in the browser.** Check `docker compose ps` on the
server. If `app` is up, the problem is Tailscale: run `tailscale status`
on both machines.

**The bot blocks every check.** Almost always the survey id, or the survey
is not activated in LimeSurvey. Open the survey in LimeSurvey yourself and
check it serves a page.

**Out of disk.** `df -h`. Old Docker images are the usual cause:
`docker system prune -a` reclaims them.

**Out of memory during a run.** Lower the workers slider. The server has
4 GB and eight Chromium instances is close to the limit.

**You want to start completely over.** `docker compose down -v` deletes
the LimeSurvey database too, then run `setup.sh` again.

---

## Two things to do once it is working

**Turn on backups.** In the Hetzner console, the server's **Backups** tab,
enable them. About €1 a month, and `out/` lives on that one disk with no
other copy.

**Keep the tailnet small.** This version of the app has no sign-in, so
anyone on the network can run anything and delete runs. That is fine for
five people and is the reason not to add anyone who should not have it.
