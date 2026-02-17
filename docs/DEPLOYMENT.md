# TeamClaws v3.2 — Deployment Guide (GCP Free Tier)

## GCP Free Tier Setup

```
Instance: e2-micro (1 vCPU, 1GB RAM) — always free in us-west1/us-central1/us-east1
OS: Ubuntu 22.04 LTS
Storage: 30GB standard persistent disk (free)
```

## 1. Create GCP VM

```bash
gcloud compute instances create teamclaws \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --tags=http-server,https-server
```

## 2. SSH into VM

```bash
gcloud compute ssh teamclaws --zone=us-central1-a
```

## 3. One-command install

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB/TeamClaws/main/setup.sh | bash
```

## 4. Configure API keys

```bash
nano ~/teamclaws/.env
# Add: GROQ_API_KEY=gsk_...  (free at groq.com)
```

## 5. Test

```bash
teamclaws chat
```

## 6. Auto-start on boot (optional)

```bash
sudo systemctl enable teamclaws
sudo systemctl start teamclaws
```

## Resource Budget (GCP Free Tier)

| Resource | Free Limit | TeamClaws Usage |
|---|---|---|
| Compute | 1 e2-micro always free | ~30% CPU idle |
| RAM | 1GB | <500MB (CEO only) |
| Storage | 30GB | <1GB (DB + logs) |
| Network egress | 1GB/month | ~100MB/month |

## Cost Optimization Tips

1. Use Groq (free tier) as primary provider
2. Set daily budget: `budget.daily_usd: 0.10`
3. Use `fast` model_type for simple tasks
4. Dream Team presets are stateless — no background processes
5. `teamclaws cost` — check spending anytime

## Updating

```bash
cd ~/teamclaws && git pull && pip install -e . -q
```
