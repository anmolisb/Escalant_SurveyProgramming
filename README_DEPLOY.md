# Putting the app on a server

The single-user app. Thirty minutes, about €4.50 a month, no domain,
nothing open to the internet.

One thing to be clear about first: **this version has no sign-in.** Anyone
who can reach it can run anything and delete runs. Tailscale is the only
thing standing in front of it, so only put people on the tailnet who
should have that.

## 1. The machine

Hetzner Cloud, console.hetzner.cloud.

- New project, **Add Server**
- Location: Nuremberg or Helsinki
- Image: **Ubuntu 24.04**
- Type: **CX22**, 2 vCPU and 4 GB, about €4.50 a month
- Add your SSH key
- Create

4 GB is the number that matters. Chromium running eight checks at once,
plus LimeSurvey, plus MySQL, will not fit in 2 GB.

## 2. Commit the deployment files

In your repository, alongside what is already there:

    Dockerfile
    docker-compose.yml
    .dockerignore
    .env.example
    setup-server.sh

And replace two files with the versions in this bundle:

    app.py          -> src/dashboard/app.py
    run_browser.py  -> src/agents/respondent_bot/run_browser.py

Both do the same small thing: take the LimeSurvey address from the
environment instead of assuming localhost. Inside a container localhost is
the container itself, so without this the bot cannot reach LimeSurvey.
Nothing changes when you run on your laptop.

Push.

## 3. One command on the server

    ssh root@<the ip>

    curl -fsSL <raw url of setup-server.sh> -o setup.sh
    REPO=https://github.com/<you>/<repo>.git \
    GROQ_API_KEY=<your key> \
    bash setup.sh

If the repository is private, scp the script across and clone by hand with
a deploy token instead.

Ten minutes. Most of it is fetching Chromium.

## 4. Reaching it

On the server:

    curl -fsSL https://tailscale.com/install.sh | sh
    tailscale up
    tailscale serve --bg --https=443  http://127.0.0.1:8501
    tailscale serve --bg --https=8443 http://127.0.0.1:8080

It prints an address like `https://survey-qa.tail1234.ts.net`. Everyone
else installs Tailscale, joins the same tailnet, and opens it.

No domain, no certificate, no open port. Remove a device and that person
is out.

## 5. Load the surveys

LimeSurvey is on the same address at port 8443. Sign in as `admin` with
the password in `/opt/survey-qa/.env`, import each `.lss` the builder
produces, activate it, and note the survey id it is given. That id goes in
the Respondent Bot page before a run.

## 6. First use

Open the app. The corpus is whatever is in `out/` on the server, which on
a fresh machine is empty: upload a questionnaire and walk it through.

If you want your existing runs there, copy them up before the first start:

    scp -r out root@<ip>:/opt/survey-qa/

## Running it

    cd /opt/survey-qa
    docker compose logs -f app                 # what it is doing
    docker compose restart app                 # after editing .env
    git pull && docker compose up -d --build   # deploy new code
    docker compose down                        # stop everything

`out/` and `data/` live on the host, so rebuilding never throws away a run.

## Two things that will bite you

**Do not publish the ports.** Docker writes its own firewall rules and a
published port is on the internet whatever ufw says. Both are bound to
127.0.0.1 and Tailscale proxies from inside the machine. Change that and
the app and the LimeSurvey admin panel are both public, the latter with a
password sitting in a file.

**Runs are not backed up.** `out/` is on one disk on one machine. Hetzner
snapshots cost about €1 a month and are worth it once there is work in
there you would mind losing.

## Why not something free

Streamlit Community Cloud loses its disk whenever the app sleeps, so every
run disappears, and it cannot run LimeSurvey at all. Render and Railway
free tiers are the same. The €4.50 buys 4 GB of memory and a disk that
stays put, and there is no free version of that.
