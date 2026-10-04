#!/usr/bin/env bash
# From a blank Ubuntu 24.04 machine to a running platform.
# Run as root on the new server.
set -euo pipefail

REPO="${REPO:?set REPO to your git url, or clone by hand first}"
BRANCH="${BRANCH:-main}"
DIR=/opt/survey-qa

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }

say "1/5  system packages"
apt-get update -qq
apt-get install -y -qq ca-certificates curl git

say "2/5  docker"
if ! command -v docker > /dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) \
signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
fi
docker --version

say "3/5  the repository"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

say "4/5  settings"
if [ ! -f .env ]; then
  gen() { python3 -c "import secrets; print(secrets.token_urlsafe(20))"; }
  cat > .env <<ENVFILE
GROQ_API_KEY=${GROQ_API_KEY:-}
DB_PASSWORD=$(gen)
DB_ROOT_PASSWORD=$(gen)
LIMESURVEY_ADMIN_PASSWORD=$(gen)
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@example.com}
ENVFILE
  chmod 600 .env
  echo "  wrote .env with generated passwords"
else
  echo "  .env already there, left alone"
fi
grep -q '^GROQ_API_KEY=.\+' .env || cat <<'WARN'

  GROQ_API_KEY is empty in .env. Everything except reading a new
  questionnaire will work without it. Add it, then: docker compose up -d
WARN

say "5/5  building and starting"
mkdir -p out data/inputs/qre_interpretation
docker compose build
docker compose up -d
printf "  waiting for the app"
for _ in $(seq 1 40); do
  curl -sf http://127.0.0.1:8501/_stcore/health > /dev/null 2>&1 && \
    { printf " up\n"; break; }
  printf "."; sleep 3
done

say "done"
cat <<DONE
  Nothing is published to the internet, which is deliberate. Install
  Tailscale and the team reaches it with no domain and no open port:

      curl -fsSL https://tailscale.com/install.sh | sh
      tailscale up
      tailscale serve --bg --https=443  http://127.0.0.1:8501
      tailscale serve --bg --https=8443 http://127.0.0.1:8080

  LimeSurvey's admin password is in $DIR/.env. Save it; it cannot be read
  back out of the running container.

  This version of the app has no sign-in. Anyone on the tailnet has full
  access, including deleting runs. That is fine for the five of you and
  is the reason not to widen the tailnet.
DONE
