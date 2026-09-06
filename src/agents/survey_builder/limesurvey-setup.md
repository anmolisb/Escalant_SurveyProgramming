# LimeSurvey Local Setup (Docker)

This sets up your own local copy of LimeSurvey Community Edition. It runs entirely on your machine — nothing is shared with anyone else's instance.

## 1. Install Docker Desktop

Download from https://www.docker.com/products/docker-desktop and install it.

- **Mac**: open the `.dmg`, drag Docker to Applications, launch it.
- **Windows**: run the installer. If prompted, enable WSL2 (Docker will guide you through this).

Once installed, open Docker Desktop and make sure it says it's running (whale icon in the menu bar / system tray).

## 2. Create the project folder

Anywhere on your machine, make a folder called `limesurvey-project`.

## 3. Add the compose file

Inside that folder, create a file named exactly `docker-compose.yml` and paste this in:

```yaml
version: '3'
services:
  limesurvey:
    image: docker.io/martialblog/limesurvey:latest
    restart: always
    environment:
      - DB_TYPE=pgsql
      - DB_PORT=5432
      - DB_HOST=db
      - DB_PASSWORD=limesurvey_db_pass
      - DB_NAME=limesurvey
      - DB_USERNAME=limesurvey
      - ADMIN_USER=admin
      - ADMIN_NAME=Admin
      - ADMIN_PASSWORD=Escalent_Capstone_2026
      - ADMIN_EMAIL=admin@example.com
      - PUBLIC_URL=http://localhost:8080
    volumes:
      - limesurvey:/var/www/html/upload
    ports:
      - 8080:8080
    depends_on:
      - db
  db:
    image: docker.io/postgres:10-alpine
    restart: always
    volumes:
      - db-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=limesurvey
      - POSTGRES_DB=limesurvey
      - POSTGRES_PASSWORD=limesurvey_db_pass
volumes:
  limesurvey:
  db-data:
```

Feel free to change `ADMIN_PASSWORD` to your own value before starting it up — it only affects your own local instance.

## 4. Start it up

Open a terminal, navigate into the folder, and run:

```bash
cd path/to/limesurvey-project
docker-compose up -d
```

The `-d` runs it in the background. First run will take a minute or two while it downloads the images.

## 5. Open it

Go to `http://localhost:8080` in your browser.

Log in with:
- **Username**: `admin`
- **Password**: `Escalent_Capstone_2026` (or whatever you set in step 3)

## Stopping / restarting

- Stop: `docker-compose down` (data persists)
- Start again: `docker-compose up -d`
- Check status in Docker Desktop under "Containers" — you should see `limesurvey-project` with `limesurvey-1` and `db-1` running.

## If something doesn't work

- **Port 8080 already in use**: change `8080:8080` to something like `8081:8080` in the compose file, then access via `http://localhost:8081`.
- **Windows + WSL2 issues**: Docker Desktop will prompt you to install/enable it — follow that prompt.
- **Containers won't start**: check Docker Desktop is actually running first.