# Deploying on AWS EC2

One Ubuntu 24.04 EC2 instance runs everything with Docker Compose: Caddy, the Streamlit frontend, the API, the
worker and Redis. Supabase stays the database. Caddy is the only service with host ports (80 and 443), with an
automatic Let's Encrypt certificate. It serves the API under `/api` (prefix stripped) and everything else from
the frontend. The browser only uses `/api` for the report's player, which streams the recording through a signed
link that expires after 10 minutes; every other API route still needs the `X-API-Key` header. Redis and the
worker publish no ports.

```
browser ──https──> Caddy :443 ─┬─ /*     ──> frontend :8501 ──> api :8000 ──> redis ──> worker
                                └─ /api/* ──> api :8000 (the player's signed video link)
```

## 1. Launch the instance

In the EC2 console, *Launch instance*:

- **AMI:** Ubuntu Server 24.04 LTS (64-bit x86).
- **Type:** `t3.large` (2 vCPU, 8 GB). `t3.medium` (4 GB) also works with the swap from step 3, but is tight
  while Whisper runs. t3 instances are burstable: a long transcription uses CPU credits, and in the default
  *unlimited* mode heavy use costs a little extra.
- **Key pair:** create or pick one; you need its `.pem` file to SSH in.
- **Security group:** three inbound rules, nothing else:

  | Type | Port | Source |
  |---|---|---|
  | SSH | 22 | My IP |
  | HTTP | 80 | 0.0.0.0/0 |
  | HTTPS | 443 | 0.0.0.0/0 |

- **Storage:** 30 GB gp3 or more. Each class keeps 100–250 MB of video and work files until
  `scripts/cleanup.py` removes them.

The public IP changes every time the instance is stopped and started. Because the sslip.io name contains the IP,
allocate an **Elastic IP** (*Network & Security → Elastic IPs → Allocate*, then *Associate* it with the
instance) so the domain stays valid. Like any public IPv4 address on AWS, it is billed per hour.

The domain is the IP with dashes, e.g. `13.233.10.20` → `13-233-10-20.sslip.io`. sslip.io resolves it to that IP
without any DNS setup.

Connect, then run everything that follows on the instance:

```bash
chmod 400 humaniti.pem
ssh -i humaniti.pem ubuntu@<public-ip>
```

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

## 3. Add 4 GB of swap

The image build and Whisper both peak in memory, and swap keeps a spike from killing a container:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf
sudo sysctl --system > /dev/null
free -h    # Swap: 4.0Gi
```

## 4. Clone

Give the instance a read-only deploy key, which works for a private repository. For a public one,
`git clone https://github.com/shivankarpatra04/humaniti-ai.git ~/humaniti-ai` is enough.

```bash
ssh-keygen -t ed25519 -N "" -C "humaniti-ai deploy" -f ~/.ssh/humaniti_deploy
cat ~/.ssh/humaniti_deploy.pub
```

On GitHub, open the repository → *Settings → Deploy keys → Add deploy key*. Paste the public key and leave
**Allow write access** unticked. Then:

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

## 5. Create `.env`

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
| `DOMAIN` | `<public-ip-with-dashes>.sslip.io` |
| `DEMO_PASSWORD` | the password reviewers type: `openssl rand -base64 12`. Avoid `$`, which Compose would expand |
| `WHISPER_MODEL` | `small.en` (default) or `base.en`; see below |

Leave `REDIS_URL` and `PUBLIC_API_URL` as they are. The compose files point the containers at `redis://redis:6379/0`,
and `docker-compose.prod.yml` sets `PUBLIC_API_URL` to `https://$DOMAIN/api`.

### Whisper model on 2 vCPU

Transcription is the slow step, and there is one worker, so classes are evaluated one after another. Measured on
a 10-minute stretch of a real class, int8, with the container pinned to 2 CPUs:

| `WHISPER_MODEL` | 10 min of audio | 45-minute class (estimate) | Notes |
|---|---|---|---|
| `base.en` | 65 s | ~5 min | ~3x faster; found 75 segments where `small.en` found 92, so it misses speech |
| `small.en` | 183 s | ~14 min | default; the transcripts the rubric was tuned on |

These cover transcription only; frames, audio metrics and the LLM add a few minutes. A laptop core is faster
than an EC2 vCPU, so expect somewhat longer times on the instance. Switch with
`WHISPER_MODEL=base.en` in `.env` and `dcp up -d worker`. Changing the model does not re-transcribe classes
that already have a cached transcript.

## 6. Start

Every command uses both compose files. An alias saves typing them:

```bash
echo "alias dcp='docker compose -f docker-compose.yml -f docker-compose.prod.yml'" >> ~/.bashrc
source ~/.bashrc
```

First start (the first build takes several minutes):

```bash
cd ~/humaniti-ai
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
dcp run --rm --no-deps api alembic upgrade head
dcp ps
```

Only `caddy` shows host ports (`0.0.0.0:80`, `0.0.0.0:443`). Open `https://<public-ip-with-dashes>.sslip.io` and
enter `DEMO_PASSWORD`. The first certificate takes up to a minute. The Whisper model downloads into the
`whisper_models` volume on the first transcription, and later runs reuse it.

Check from another machine that only Caddy can be reached:

```bash
curl -I http://<public-ip-with-dashes>.sslip.io           # 308 redirect to https
curl https://<public-ip-with-dashes>.sslip.io/api/health  # {"status":"ok",...} through Caddy
curl -m 5 http://<public-ip-with-dashes>.sslip.io:8000    # times out: port 8000 is not published
```

All services have `restart: unless-stopped`, and Docker starts on boot, so the app comes back after a reboot or
a stop and start.

## 7. Logs

```bash
dcp logs -f worker               # one line per stage, per evaluation
dcp logs -f --tail 100 api
dcp logs caddy | grep -i error   # certificate or proxy problems
dcp ps                           # status and restarts
```

## 8. Update

```bash
cd ~/humaniti-ai
git pull
dcp up -d --build
dcp run --rm --no-deps api alembic upgrade head
docker image prune -f
```

A running evaluation is lost when the worker restarts. Submitting the same file or link again resumes from the
cached transcript.

## 9. Stop or terminate to save credits

Stop the app but keep the instance running:

```bash
dcp down       # removes the containers; volumes, ./data and .env stay
```

Do not run `dcp down -v`: it deletes the Whisper model cache and Caddy's certificate. Re-issuing the certificate
too often hits Let's Encrypt rate limits.

Stop the **instance** between demos (*EC2 → Instances → Instance state → Stop*). A stopped instance costs nothing
for compute; the EBS volume and the Elastic IP are still billed. *Start* brings everything back, and the
containers start on their own. Without an Elastic IP, the public IP is new after a start: update `DOMAIN` in
`.env` and run `dcp up -d`.

**Terminate** when the demo is over (*Instance state → Terminate*). This deletes the instance and its volume,
including uploaded videos and cached transcripts. Evaluation results stay in Supabase. Then release the Elastic
IP (*Elastic IPs → Actions → Release*), or it keeps being billed.

## Disk

Uploads and work folders live in `~/humaniti-ai/data`. Free space with the retention script (see the README's
*Disk cleanup*):

```bash
dcp run --rm --no-deps worker python -m scripts.cleanup
df -h /
```

## Troubleshooting

- **No certificate / site does not load:** the security group must allow 80 and 443 from `0.0.0.0/0`, and
  `DOMAIN` must contain the instance's current public IP. Then run `dcp restart caddy`.
- **"Cannot reach the Humaniti AI API":** `dcp logs api`. Usually `DATABASE_URL` is wrong or Supabase paused the
  project.
- **Containers restart during transcription:** out of memory; check `free -h` and that swap is on (step 3).
- **The report shows no video:** `https://<domain>/api/health` must answer, and
  `dcp exec api printenv PUBLIC_API_URL` must print `https://<domain>/api`.
- **Player says the link is invalid:** the instance clock is off, or `DOMAIN` changed after the page loaded;
  reload.
- **Upload fails above 1 GB:** this is the limit everywhere (Caddy, Streamlit `--server.maxUploadSize`,
  `max_upload_mb` in `app/config.py`).
