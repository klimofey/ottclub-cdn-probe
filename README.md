# cdnprobe

Works out which **ilook.tv CDN** actually keeps your stream fed, by measuring
every CDN the account offers, over and over, and ranking them on evidence
rather than on a single lucky reading.

Runs as one Docker container with a dashboard.

English · [Русский](README.ru.md)

Several resellers run the same OTTClub panel — **ilook.tv** and
**vipdrive.net** among them — so point `PANEL_URL` at whichever one your
subscription is with.

![tests](https://img.shields.io/badge/tests-99%20passing-brightgreen)
![docker](https://img.shields.io/badge/docker-1.32GB-blue)

![dashboard](dashboard.png)

<details><summary>Dark theme</summary>

![dashboard, dark theme](dashboard-dark.png)

</details>

---

## ⚠️ Do not point this at the account you watch on — unless you set active hours

The container **switches CDNs continuously**; that is the whole point of it.
While a round runs, the account it uses is a poor thing to watch TV on: the
stream is re-routed every few minutes and each switch takes minutes to settle.

Two ways to live with that:

**A separate cheap subscription.** A couple of dollars, and rounds can run
around the clock without ever touching what you watch. This is the clean
option.

**Or `ACTIVE_HOURS` plus `AUTO_APPLY`.** Test only while you are asleep and
have the best CDN left in place by morning. See
[Testing on an account you also watch](#testing-on-an-account-you-also-watch).

Either way, note the container discovers the playlist link from the account it
logs into — so the account you give it is the one that gets hammered.

---

## Install

Save as `docker-compose.yml`, run `docker compose up -d`, open
<http://localhost:8080>.

```yaml
services:
  cdnprobe:
    image: ghcr.io/klimofey/ottclub-cdn-probe:latest
    container_name: cdnprobe
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      ILOOK_EMAIL: you@example.com
      ILOOK_PASSWORD: your-password
      ROUND_PAUSE: none          # none | manual | 30m | 1h
      # PANEL_URL: https://ilook.tv
      # ACTIVE_HOURS: "01:00-07:00"   # only measure while you sleep
      # TZ: Europe/Berlin             # timezone the window is read in
      # AUTO_APPLY: "true"            # leave the best CDN applied
    volumes:
      - cdnprobe-data:/data

volumes:
  cdnprobe-data:
```

Or without a file at all:

```bash
docker run -d --name cdnprobe --restart unless-stopped -p 8080:8080 \
  -e ILOOK_EMAIL='you@example.com' -e ILOOK_PASSWORD='your-password' \
  -v cdnprobe-data:/data ghcr.io/klimofey/ottclub-cdn-probe:latest
```

```bash
docker compose logs -f                       # watch it work
docker compose pull && docker compose up -d  # update
```

The volume keeps the measurement history; the statistics are the whole point,
so leave it in place across updates.

## Configuration

Everything is an environment variable; only the first two are required.

| Variable | Default | Meaning |
|---|---|---|
| `PANEL_URL` | `https://ilook.tv` | Panel to log into |
| `ILOOK_EMAIL` | — | Account email |
| `ILOOK_PASSWORD` | — | Account password |
| `ROUND_PAUSE` | `none` | Gap between full rounds: `none`, `manual`, `30m`, `1h`, `3600` |
| `ACTIVE_HOURS` | _(all day)_ | Only test inside this window, e.g. `01:00-07:00` |
| `TZ` | `UTC` | Timezone the window is read in |
| `AUTO_APPLY` | `false` | Switch the account to the best proven CDN after each round |
| `WEB_PORT` | `8080` | Dashboard port on the host |
| `DISCOVERY_ROUNDS` | `20` | Balancer polls per channel; more gives better weighting |
| `CHANNELS` | `2` | Channels sampled per round |
| `EDGE_CAP_SECONDS` | `3.0` | Per-edge download cap |
| `EDGE_CAP_MB` | `6` | Per-edge byte cap |
| `MAX_ACTIVE_CDNS` | `10` | Keep at most this many in rotation; `0` disables |
| `BENCH_MIN_ROUNDS` | `3` | Rounds a CDN must have before it can be benched |
| `BENCH_BELOW_RATIO` | `2.0` | Median below this benches a CDN outright |
| `PAROLE_PER_ROUND` | `1` | Benched CDNs re-tested per round; `0` disables |
| `HISTORY_DAYS` | `30` | Drop measurements older than this |
| `HISTORY_MAX_RECORDS` | `20000` | Hard cap on journal size |

The journal is pruned on every write. Age is the primary filter and it is
there for accuracy, not disk space: CDN quality drifts from day to day, so a
month-old round describes a different network and only blurs today's median.
At a dozen rounds a day the file settles around 2 MB and stays there.

`AUTO_APPLY` needs the account to be left alone afterwards to mean anything.
With `ROUND_PAUSE=none` the next round begins at once and switches the CDN
away within minutes, so the setting achieves nothing - the container says so
on startup. Pair it with `ACTIVE_HOURS`, or with a pause long enough to watch
something in.

When the window closes mid-round, the best CDN is applied before the round
goes to sleep, not only when a round finishes. Without that the account would
sit all day on whichever CDN happened to be under test at dawn - the opposite
of what the setting promises.

Any column on the dashboard sorts on click - useful for asking a different
question of the same data, such as "which CDN has the best *worst* round"
rather than the best median.

`ROUND_PAUSE=manual` holds the daemon still until you press **Run round** on
the dashboard. Handy if you only want to measure during the hours you
actually watch.

## Benching the hopeless ones

A round costs about five minutes per CDN, so measuring twenty of them takes
hours. Once a CDN has repeatedly failed there is little point paying that
price again — benching it lets the rest be sampled twice as often, which is
what actually sharpens the statistics.

Three rules keep that from becoming self-fulfilling:

**A CDN needs several rounds before it can be benched.** One bad evening is
not evidence. A CDN measured here read 1.81x one hour and 7.36x the next; a
hair-trigger rule would have benched one of the best options.

**The account's automatic option is never benched.** It is the reference
point that separates "this CDN is bad" from "the whole network is bad
tonight". Without it you cannot tell those apart.

**New CDNs are always measured.** An option the provider adds tomorrow has no
history, so there are no grounds to skip it.

**Benched CDNs are not forgotten.** One per round — the one unchecked longest
— is let out on parole and measured again. If it now passes the same test
that benched it, it is released automatically; there is no point learning it
recovered and keeping it out anyway. The round-robin paces itself: with nine
on the bench each is re-tested roughly every nine rounds.

The dashboard also offers a manual release button, for overriding the machine
rather than waiting for it.

## How long a round takes

Measured on a live account: **1.6 to 2.5 hours** for a full pass over 19
CDNs, or about **50 minutes** once benching has trimmed the rotation to ten.

The limit is not the measuring, which takes about two minutes per CDN. It is
the provider, which accepts a CDN change roughly **once every five minutes**;
the measurement fits inside that wait. The spread comes from how quickly the
edge pool turns over after a switch - sometimes 20 seconds, sometimes the
full propagation timeout.

A six-hour window therefore fits two or three rounds a night, which is enough
to accumulate 15-20 rounds per CDN in a week.

## Testing on an account you also watch

Two settings together make this workable without a second subscription:

```env
ACTIVE_HOURS=01:00-07:00
TZ=Asia/Jerusalem
AUTO_APPLY=true
```

Rounds then run only while you are asleep, and when one finishes the account
is left on the CDN that has actually proven itself. The window is re-checked
before every CDN, not once per round, so a round that is still going at 07:00
pauses and resumes the next night rather than switching CDNs under you at
breakfast.

`AUTO_APPLY` only acts on a **solid** verdict - a high median that jumps
around does not qualify. If nothing has proven steady yet, it leaves the
setting alone and says so in the log.

That said, a separate cheap subscription is still the cleaner answer if you
want rounds running around the clock.

## What it measures, and why not ping

Latency to the edges is nearly identical (150–230 ms) and separates them not
at all. The difference is entirely throughput, so the metric is the
**realtime ratio**: how many seconds of video arrive per second of wall clock.

```
ratio = segment duration / (segment size / download speed)
```

`5x` means ten seconds of video download in two — a fourfold margin. `1x`
means the stream barely keeps up. Below `2x` any hiccup causes buffering.

Two decisions make the numbers honest:

**The average is weighted by how often an edge is actually served.** On one
CDN the fast edges (up to 6.89x) appeared in 10% of requests and the slow
ones (1.14x) in 90%. A plain average across servers said 3.7x; weighted by
what the viewer really receives it was 1.81x.

**The headline is the median across rounds, not the mean.** A single freak
round moves a mean and leaves a median alone — which matters, because freak
rounds happen (see below).

The table also shows the **worst round ever recorded** and the **spread**,
because streams break in the dips, not in the average. A CDN with a 9x median
and a 1.5x worst round is worse than a steady 6x.

## How the provider works

Reverse-engineered by observation; the method follows from it.

```
1. PORTAL     <hash>.ottclub.net/playlists/uplist/<TOKEN>/playlist.m3u8
              thousands of channels, all pointing at ONE balancer host
                        │
2. BALANCER   <hash>.russtv.net/iptv/<STREAM_TOKEN>/<CHANNEL_ID>/index.m3u8
              returns a channel playlist whose segments sit on bare IPs
                        │
3. EDGES      the servers actually delivering .ts
```

**Choosing a CDN does not change any URL.** The balancer host belongs to the
account; the setting only changes which edges it hands out. So CDNs cannot be
enumerated by rewriting URLs — only through the account panel, and changes
are rate limited to roughly **one every five minutes**, which is what makes a
full round take a couple of hours.

**Edges are handed out at random.** A single IP is not stable, but its `/24`
is a physical site and does persist. Results are therefore rolled up per site.

**Every channel has its own edge pool.** Pools of neighbouring channels did
not overlap at all, so discovery and measurement always stay within one
channel.

**The `md5` in a segment URL is an access key for the (edge, channel) pair,
not a signature of the segment.** It is identical across every segment that
edge serves for that channel; a foreign key returns `401`, the right one
`200`. That is what allows every edge to be measured on one identical
segment, which is the only fair comparison.

## Why rounds have to repeat

Measured on a live account across one evening:

| CDN | early reading | later reading |
|---|---|---|
| Automatic | 3.28x | 1.43x |
| Germany | 1.81x | 7.36x |
| Spain | 12.89x | 5.37x |

The variation of a single CDN over hours is as large as the difference
between CDNs. A table of one-shot readings taken at different times ranks the
clock, not the CDNs — which is why this runs in a loop and reports medians,
spreads and worst cases instead of a single number.

Spain's 12.89x is the cautionary case: that round was measured immediately
after Italy and picked up Italy's site before the switch had propagated. The
tool now flags a round whose edge pool never turned over, and the median
absorbs whatever slips through.

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install pytest
./.venv/bin/playwright install chromium
PYTHONPATH=. ./.venv/bin/pytest tests/ -q
```

Commands outside Docker:

```bash
python -m cdnprobe serve   # rounds + dashboard (what the container runs)
python -m cdnprobe once    # a single round, then exit
python -m cdnprobe stats   # print the table
python -m cdnprobe list    # show the playlist and CDNs the account offers
```

Tests cover everything that does not need the network: playlist parsing, site
aggregation, ratio arithmetic, cooldown handling, the statistics, and a
regression for the per-channel key rule.

## Notes

Credentials are read from the environment and never logged, never written to
disk, and never passed as command-line arguments. The browser session is
cached in the volume so the site's Cloudflare protection is not provoked by
repeated logins.

This talks to your own account with your own credentials and does nothing the
web panel does not. It is a measurement tool, not a workaround for anything.

## License

MIT
