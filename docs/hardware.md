# Hardware and setup

## Shopping list

For **each** of the two Pis:

| Item | Notes |
|---|---|
| Raspberry Pi 5, **8 GB** | 4 GB is too small for the AI plus its cache. |
| Official **Active Cooler** | **Essential.** The AI runs all four CPU cores flat out. Without a cooler the Pi throttles and slows right down. |
| Official **27 W USB-C** power supply | Phone chargers cause under-voltage and random slowdowns. |
| M.2 HAT+ (or similar NVMe base) + **NVMe SSD** (128 GB or more) | Loads the model in seconds and is far more reliable than SD cards. A good 64 GB microSD works if you must. |
| A case with airflow that fits the HAT and cooler | Or use no case and keep the Pis somewhere safe and ventilated. |
| Short ethernet cable | Wired is more reliable than Wi-Fi for the Pis. |

Shared:

| Item | Notes |
|---|---|
| Travel router (e.g. any GL.iNet-style pocket router) | Makes the event Wi-Fi. **Don't plug it into the internet** on the day. |
| Laptops/Chromebooks with Chrome, Edge or Firefox | One per team of 2-3 scouts. Keyboards matter: the games use arrow keys and space. |
| Projector or big TV | For the join code, demos and the awards. |
| USB sticks (optional) | To send scouts home with their games. |

## 1. Prepare each Pi (with internet)

1. Use **Raspberry Pi Imager** to write **Raspberry Pi OS Lite (64-bit)** onto the NVMe drive. A cheap USB-to-NVMe adapter works for this. In the Imager settings, create a user, turn on SSH, and add your home Wi-Fi so the Pi can download things.
2. Fit the drive, cooler and HAT, then boot. If it doesn't boot from NVMe, boot once from an SD card and run `sudo raspi-config` → *Advanced Options* → *Boot Order* → *NVMe/USB Boot*.
3. Update everything: `sudo apt update && sudo apt full-upgrade -y && sudo reboot`.
4. Get the code and install. This takes about 20 minutes: building llama.cpp takes about 10, plus the model download.

   ```bash
   git clone https://github.com/ijmok/scout-code.git
   cd scout-code
   sudo ./setup/install.sh --role basecamp     # on the FIRST Pi
   ```

   The end of the output shows the **leader PIN** and a **key**. On the **second** Pi:

   ```bash
   sudo ./setup/install.sh --role worker --key <KEY FROM BASECAMP>
   ```

5. Reboot both Pis, so their new names (`scout` and `scout-worker`) are picked up.

## 2. Choose the model

`download-models.sh` fetches the **3B** model by default. To see whether another model works better on your Pis, download it and let the benchmark compare them side by side:

```bash
./setup/download-models.sh 4b
sudo /opt/scout/venv/bin/python setup/benchmark.py --compare 3b 4b --show
```

For each model the benchmark:

1. switches the AI to it;
2. pre-loads the games, like the website does;
3. sends 10 typical scout requests, with the same automatic retry the studio uses;
4. checks whether each edited game still looks like **working code**.

At the end it puts your original model back, restarts the website, and prints a comparison table with a recommendation. The edited games are saved in `/tmp/scout-compare/` if you want to play them. It takes about 15-25 minutes.

Aim for **under ~90 s per request** and **8/10 or more working games**. To check a single model, run it without `--compare`. Add `--show` to print what the AI wrote whenever it needed a retry or broke the game.

| Model | On an 8 GB Pi 5 (tested) | Use when |
|---|---|---|
| 1.5B | Fastest, more mistakes | Big group, short session |
| **3B (default)** | **About 45 s per request, 9/10 working games** | **Recommended** |
| 4B (Qwen3) | Too big: 2 words/s, its cache doesn't fit, and the Pi crashed during testing | Not on an 8 GB Pi |
| 7B | Too big for an 8 GB Pi with these settings | Not on an 8 GB Pi |

`--compare` checks each model's memory needs first and skips models that won't fit safely (`--force` to try anyway). If a comparison is cut short, for example because the Pi restarted, the next benchmark run or `update-services.sh` puts your original model back. The leader dashboard shows which model each Pi is running.

Use the **same model on both Pis**.

> These model files are hosted on Hugging Face. If a download fails, the script stops with a clear message. Search Hugging Face for the model name with "GGUF" and update the URL in `setup/download-models.sh`.

## Updating after `git pull`

```bash
cd ~/scout-code && git pull
sudo ./setup/update-services.sh     # on BOTH Pis: refreshes the AI and portal services and restarts them
```

## 3. Network for the day

1. Connect both Pis to the travel router with ethernet, and leave the router's internet port empty.
2. In the router's admin page, give each Pi a **fixed address** (DHCP reservation), for example:
   - `scout` → 192.168.8.10
   - `scout-worker` → 192.168.8.11
3. If the worker isn't reachable as `scout-worker.local`, edit `/opt/scout/data/config.json` on basecamp to use its IP, then run `sudo systemctl restart scout-portal`.
4. On a laptop on the event Wi-Fi, open `http://scout.local`. If that doesn't load (some Chromebooks and older Windows can't see `.local` names), use `http://192.168.8.10`. Write that address on the board.

## 4. Offline dress rehearsal (do this!)

With the internet unplugged:

1. Open `/leader`. Both workers should show a green dot and a temperature, and after a few minutes **🔥 Warm ✓**.
2. With 3 laptops, create teams, make 3 changes each, publish, then rate each other's games.
3. Watch the dashboard. Temperatures should stay below about 80 °C. If one shows ⚠️ *throttled*, improve the cooling or the power supply.
4. Optionally load-test from a laptop: `python setup/load_test.py --url http://scout.local --leader-pin <PIN> --teams 6`
5. Reset for the real event: on the dashboard, use **🔄 Start a new event** (see below).

## Switching off at the end

On the leader dashboard, press **⏻ Shut down both Pis** and confirm. The worker Pi shuts down first, then basecamp (which runs the website). Wait until each Pi's green light stops flashing and only the red light is on (about 20 seconds), then unplug them, then the router.

Nothing is lost: when you switch on again (router first, then the Pis), the event carries on where it left off and the AI warms up by itself.

If the dashboard can't reach a Pi, press the small **power button on the edge of the Pi once** (don't hold it). That also shuts it down cleanly. Never just pull the plug while a Pi is running: it can damage the saved games.

> The button needs a one-time permission on each Pi. `install.sh` and `update-services.sh` set it up. If a worker card on the dashboard says *"can't shut down from here yet"*, run `sudo ./setup/update-services.sh` on that Pi.

## Running another group

On the leader dashboard, type the new group's event name under **🔄 Start a new event** and press **Save this event and start a new one**. It:

- saves the current event to **Past events**: a full backup of every game, version, rating and vote, plus a zip of the games for USB sticks (both downloadable from the dashboard);
- stops any AI requests still running;
- clears all teams, games, ratings and votes, re-opens voting, hides the awards, unpauses the AI, and makes a new join code;
- sends any laptop still logged in back to the join page.

Your leader PIN, the AI, the model and the warm-up are untouched, so the Pis don't need restarting. Archives are kept in `/opt/scout/data/archive/` on basecamp.

**Bringing an old event back** (rarely needed): download its *backup*, or find it in the archive folder, then:

```bash
sudo systemctl stop scout-portal
cd /opt/scout/data && rm -f scout.db-wal scout.db-shm
cp archive/<event folder>/scout.db scout.db
sudo systemctl start scout-portal
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Red dot on a worker | `sudo systemctl status scout-llm` on that Pi. Check the model exists: `ls -l /opt/scout/models/current.gguf` |
| Everything is slow | Check temperatures on the dashboard. One Pi down means half speed. Try the 1.5B model. |
| A Pi drops off the network under heavy load | It probably ran out of memory or power. Check `journalctl -b -1 -k --no-pager \| grep -iE "out of memory\|voltage"` and `vcgencmd get_throttled` (`0x0` is good; `0x5…`/`0x50005` means under-voltage). Use the official 27 W power supply and the 3B model. |
| "The AI got confused" every time | Run `setup/benchmark.py --show` and look at what the AI actually wrote. On the dashboard, click a row in *Recent AI requests* to see the same thing. The AI is forced into the edit format by a grammar; to compare without it, add `"use_grammar": false` to `config.json` or run the benchmark with `--no-grammar`. |
| A team is stuck "Working…" | Dashboard → Queue → **Stop**. They can ask again. |
| A team forgot their PIN | Dashboard → Teams shows every PIN. **New PIN** issues a new one. |
| Laptops can't open scout.local | Use the IP address instead. |
| Need to pause everyone | **⏸️ Pause AI** on the dashboard. Queued requests wait until you resume. |
| Logs | `journalctl -u scout-portal -f` and `journalctl -u scout-llm -f` |
