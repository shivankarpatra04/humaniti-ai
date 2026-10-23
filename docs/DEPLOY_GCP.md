# Deploying on a Google Cloud VM

One Ubuntu 24.04 VM runs everything with Docker Compose: Caddy, the Streamlit frontend, the API, the worker
and Redis. Supabase stays the database. Caddy is the only service that listens on the internet (ports 80 and
443), with an automatic Let's Encrypt certificate. It forwards everything to the frontend except
`/evaluations/<id>/video`, the signed, expiring link the report's player streams the recording from. The rest of
the API, Redis and the worker publish no ports.

```
browser ──https──> Caddy :443 ──> frontend :8501 ──> api :8000 ──> redis ──> worker
                         └─ /evaluations/<id>/video (signed link) ──> api :8000
```

## 1. Create the VM

In the Cloud Console, *Compute Engine → VM instances → Create instance*:

- Machine type `e2-standard-2` (x86, 2 vCPU, 8 GB), region `asia-south1` (Mumbai, close to Supabase).
- Boot disk: Ubuntu 24.04 LTS (x86/64), 50 GB balanced persistent disk. Each class keeps 100–250 MB of video
  and work files until `scripts/cleanup.py` removes them.
- Firewall: tick **Allow HTTP traffic** and **Allow HTTPS traffic**. Open no other ports.
- *Networking → External IPv4 address*: **reserve a static address**. The sslip.io name contains the IP, so
  the address must not change when the VM restarts.

The domain is the IP with dashes, e.g. `34.93.10.20` → `34-93-10-20.sslip.io`. sslip.io resolves it to that IP
without any DNS setup.

Connect with the *SSH* button in the console, or `gcloud compute ssh <vm-name> --zone <zone>`. All the
following commands run on the VM.

## 2. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in so the group change applies, then check:

```bash
docker run --rm hello-world
docker compose version    # needs v2.24 or newer for the `!reset` tags in docker-compose.prod.yml
```

## 3. Clone with a read-only deploy key

Create a key on the VM that can only read this one repository:

```bash
ssh-keygen -t ed25519 -N "" -C "humaniti-ai deploy" -f ~/.ssh/humaniti_deploy
cat ~/.ssh/humaniti_deploy.pub
```

On GitHub, open the repository → *Settings → Deploy keys → Add deploy key*. Paste the public key, name it after
the VM, and leave **Allow write access** unticked.

Back on the VM:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-humaniti
    HostName github.com
    User git
    IdentityFile ~/.ssh/humaniti_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T github-humaniti    # answer "yes" once; expect "You've successfully authenticated"
git clone github-humaniti:shivankarpatra04/humaniti-ai.git ~/humaniti-ai
cd ~/humaniti-ai
```

## 4. Create `.env`

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Fill in:

| Key | Value |
|---|---|
| `DATABASE_URL` | Supabase *Connect → Session pooler* URI with the `postgresql+psycopg://` prefix |
| `ANTHROPIC_API_KEY` | the production Anthropic key |
| `API_KEY` | a new random secret: `openssl rand -base64 32` |
| `DOMAIN` | `<ip-with-dashes>.sslip.io` |
| `DEMO_PASSWORD` | the password reviewers type: `openssl rand -base64 12`. Avoid `$`, which Compose would expand |

Leave `REDIS_URL` and `PUBLIC_API_URL` as they are. The compose files point the containers at `redis://redis:6379/0`,
and `docker-compose.prod.yml` sets `PUBLIC_API_URL` to `https://$DOMAIN`.

## 5. Start

Every command uses both compose files. An alias saves typing them:

```bash
echo "alias dcp='docker compose -f docker-compose.yml -f docker-compose.prod.yml'" >> ~/.bashrc
source ~/.bashrc
```

First start:

```bash
cd ~/humaniti-ai
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
dcp run --rm --no-deps api alembic upgrade head
dcp ps
```

Only `caddy` shows published ports (`0.0.0.0:80`, `0.0.0.0:443`). Open `https://<ip-with-dashes>.sslip.io` and
enter `DEMO_PASSWORD`. The first certificate takes up to a minute. The Whisper model (~500 MB) downloads into the
`whisper_models` volume on the first transcription, and later runs reuse it.

Check from another machine that only Caddy can be reached:

```bash
curl -I http://<ip-with-dashes>.sslip.io           # 308 redirect to https
curl -m 5 http://<ip-with-dashes>.sslip.io:8000    # times out: the API is not public
```

All services have `restart: unless-stopped`, and Docker starts on boot, so the app comes back after a VM restart.

## 6. Logs

```bash
dcp logs -f worker               # one line per stage, per evaluation
dcp logs -f --tail 100 api
dcp logs caddy | grep -i error   # certificate or proxy problems
dcp ps                           # status and restarts
```

## 7. Update

```bash
cd ~/humaniti-ai
git pull
dcp up -d --build
dcp run --rm --no-deps api alembic upgrade head
docker image prune -f
```

A running evaluation is lost when the worker restarts. Submitting the same file or link again resumes from the
cached transcript.

## 8. Stop

```bash
dcp stop       # stop the containers and keep them
dcp start      # start them again
dcp down       # remove the containers; volumes and ./data stay
```

Do not run `dcp down -v`: it deletes the Whisper model cache and Caddy's certificate. Re-issuing the certificate
too often hits Let's Encrypt rate limits.

## Disk

Uploads and work folders live in `~/humaniti-ai/data`. Free space with the retention script (see the README's
*Disk cleanup*):

```bash
dcp run --rm --no-deps worker python -m scripts.cleanup
df -h /
```

## Troubleshooting

- **No certificate / browser warning:** ports 80 and 443 must be open in the VPC firewall (the *Allow HTTP/HTTPS*
  boxes) and `DOMAIN` must contain the VM's current external IP. Then `dcp restart caddy`.
- **"Cannot reach the Humaniti AI API":** `dcp logs api`. Usually `DATABASE_URL` is wrong or Supabase paused the
  project.
- **Player says the link is invalid:** the VM clock is off, or `DOMAIN` changed after the page loaded; reload.
- **Upload fails above 1 GB:** this is the limit everywhere (Caddy, Streamlit `--server.maxUploadSize`,
  `max_upload_mb` in `app/config.py`).
