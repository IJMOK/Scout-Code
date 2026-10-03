---
name: pi-deploy
description: Install, update, benchmark or troubleshoot Scout Code on the Raspberry Pi 5s (basecamp + worker). Use when asked about setting up the Pis, changing the AI model, the offline dress rehearsal, or a service not working.
---

# Deploying Scout Code to the Pis

The full leader-facing guide is `docs/hardware.md`. This is the short version for making changes.

## Roles

- **basecamp** (hostname `scout`): `scout-portal` (FastAPI on port 80), `scout-llm` (llama-server on 8080), `scout-stats` (8099).
- **worker** (hostname `scout-worker`): `scout-llm` and `scout-stats` only.
- Config: `/opt/scout/data/config.json` on basecamp lists both workers. The llama-server API key is in `/opt/scout/llm-key`, and must be the same on both Pis.

## Install / update

The install needs internet:

```bash
sudo ./setup/install.sh --role basecamp
sudo ./setup/install.sh --role worker --key "$(ssh scout.local cat /opt/scout/llm-key)"
```

To update the code later: `git pull`, then `sudo ./setup/update-services.sh` on each Pi. That re-renders the systemd units from `setup/systemd/` and restarts them. Re-run `install.sh` only for new packages or a new llama.cpp version. It is idempotent.

Speed: most of a request's time is the Pi *reading* the game (the prompt). `--cache-ram` plus `--cache-reuse` in `scout-llm.service`, and the portal's start-up warm-up of all starters (`JobQueue.start_warmup`), keep that short. `setup/benchmark.py --repeat --show` shows cold vs warm times and any failing replies.

The llama.cpp version is pinned with `LLAMA_REF` in `install.sh`. If you change it, check that the flags in `setup/systemd/scout-llm.service` still exist (`llama-server --help`).

## Change the model (same on both Pis)

```bash
./setup/download-models.sh 1.5b
sudo ln -sf /opt/scout/models/<file>.gguf /opt/scout/models/current.gguf
sudo systemctl restart scout-llm
/opt/scout/venv/bin/python setup/benchmark.py
```

## Dress rehearsal checklist (offline!)

1. Unplug the router's internet. Both workers show green on `/leader`.
2. `python setup/load_test.py --url http://scout.local --leader-pin <PIN> --teams 6`: the longest wait should be acceptable (a few minutes at most).
3. Do a real run with laptops: join, 3 edits, publish, rate, close voting, reveal awards, download the zip.
4. Temperatures stay under ~80 °C with no ⚠️ throttled.
5. Reset: stop `scout-portal`, move `/opt/scout/data/scout.db` aside, then start it again.

## Debugging

- `journalctl -u scout-llm -f` / `journalctl -u scout-portal -f`
- `curl -H "Authorization: Bearer $(cat /opt/scout/llm-key)" localhost:8080/props`
- In development without Pis, use `SCOUT_MOCK=1` (see README).
