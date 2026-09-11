# cdnprobe

Works out which **ilook.tv CDN** actually keeps your stream fed, by measuring
every CDN the account offers, over and over, and ranking them on evidence
rather than on a single lucky reading.

Runs as one Docker container with a dashboard.

English · [Русский](README.ru.md)

Several resellers run the same OTTClub panel — **ilook.tv** and
**vipdrive.net** among them — so point `PANEL_URL` at whichever one your
subscription is with.

![tests](https://img.shields.io/badge/tests-144%20passing-brightgreen)
![docker](https://img.shields.io/badge/docker-1.32GB-blue)

![dashboard](dashboard.png)

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

**Or run it passively.** With `OBSERVE_ONLY` the container never touches the
CDN select at all: it measures whatever the account is already set to. Nothing
is re-routed, so the account stays watchable around the clock. See
[Two copies: one steering, one watching](#two-copies-one-steering-one-watching).

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
| `OBSERVE_ONLY` | `false` | Measure the CDN the account is on and never switch it |
| `WEB_PORT` | `8080` | Dashboard port on the host |
| `DISCOVERY_ROUNDS` | `20` | Balancer polls per channel; more gives better weighting |
| `CHANNELS` | `2` | Channels sampled per round |
| `EDGE_CAP_SECONDS` | `3.0` | Per-edge download cap |
| `EDGE_CAP_MB` | `6` | Per-edge byte cap |
| `MAX_ACTIVE_CDNS` | `0` | Cap the rotation at this many; `0` benches nothing |
| `BENCH_MIN_ROUNDS` | `3` | Rounds a CDN must have before it can be benched |
| `BENCH_BELOW_RATIO` | `0` | Median below this benches a CDN outright; `0` disables |
| `PAROLE_PER_ROUND` | `1` | Benched CDNs re-tested per round; `0` disables |
| `SETTLE_SECONDS` | `210` | Let a switch take over this long before measuring |
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

## Data endpoints

Everything the dashboard shows is available as plain files, no key required:

| Path | What it gives |
|---|---|
| `/api/stats.json` | The ranked table, the pick, coverage and the per-part leaders |
| `/api/stats.json?part=evening` | The same for one part of the day |
| `/api/series.json` | The chart's time series (`?limit=` to widen it) |
| `/api/history.jsonl` | Every measurement, one JSON object per line |
| `/api/history.csv` | The same as a spreadsheet (UTF-8 BOM, so names open correctly) |

```bash
curl -s localhost:8080/api/stats.json | jq '.pick'
curl -s 'localhost:8080/api/stats.json?part=evening' | jq '.cdns[0]'
curl -O localhost:8080/api/history.csv
```

`Access-Control-Allow-Origin: *` is set, so a browser script or a spreadsheet
can pull them directly. **There is no authentication anywhere** — on the
dashboard or these endpoints. That is fine on a home network and wrong on the
open internet: put it behind a reverse proxy with auth, or a VPN, before
exposing it.

## The chart

The dashboard plots the leading CDNs' margin over time - one line each, with
the `2x` floor marked. It exists because the table cannot show *when* things
changed, and with this provider the when matters: the same CDN swung fourfold
across one evening.

Lines are monotone cubic curves rather than straight segments. Ordinary
spline smoothing overshoots between points, which here would be a lie
rather than a flourish: a curve sagging between two measurements of 2.4x
would draw a dip below the 2x floor that never happened. The monotone
variant is provably free of maxima and minima the data does not contain.

Only the top few CDNs are drawn. Twenty lines is not a chart, and the question
worth asking is how the plausible candidates behave, not how the hopeless ones
do. Hovering names the measurement under the cursor - each CDN is measured at
its own moment, so the nearest real point is shown rather than a shared
vertical slice that would imply simultaneity that does not exist.

## Letting a switch land

A newly chosen CDN is given **3.5 minutes** before anything is measured. The
panel promises 5-10; measuring sooner catches a mixture of the outgoing CDN
and the incoming one, and records the mixture as a fault of the incoming one.
That is not hypothetical - a CDN read 0.86x that way, with a foreign site in
its pool, while its owner was watching on it without a hitch.

The wait is nearly free. A switch is only allowed every five minutes anyway,
so settling for 3.5 and then measuring for two finishes right as the next
switch becomes possible. Waiting less does not make a round faster; it only
makes the numbers wrong.

Whether the edge pool was seen to turn over is still recorded, but as a
confidence flag rather than as the trigger to start measuring. A pool
changing on one channel does not mean the switch has landed everywhere.

## Time of day

The same journal can be read for one part of the day at a time — night 00-06,
morning 06-12, afternoon 12-18, evening 18-24, in the container's local time
(`TZ`). Tabs on the dashboard switch between them.

This is not a nicety. Measured on a live account, the automatic option read
3.28x at 19:12 and 1.43x at 23:34; Germany read 1.81x at 22:00 and 7.36x at
23:48. Averaged into one number, neither the evening nor the night is
described. Sliced, the best CDN for the evening turned out not to be the best
for the night.

A round lasts hours and crosses these boundaries, so the split also corrects
for a bias inside a single round: the CDNs measured last are measured later
at night than the ones at the start.

Each slice needs its own two rounds per CDN before it recommends anything, so
expect empty slices at first. A slice with no data is shown as such rather
than hidden — "not measured yet" is information, and hiding it would read as
a verdict.

## Benching the hopeless ones

**Off by default.** It acts on a verdict, and a verdict is only as good as
the measurements under it — excluding a CDN wrongly costs far more than
measuring one needlessly. Turn it on with `MAX_ACTIVE_CDNS` once the data has
earned trust. Turning it back off also releases whoever is already benched.


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

**Benched CDNs are not forgotten.** One per round — the one unchecked longest,
and it is measured **first**: rounds get interrupted often enough that anything
at the tail is never reached, and a parole that never runs is decoration
— is let out on parole and measured again. If it now passes the same test
that benched it, it is released automatically; there is no point learning it
recovered and keeping it out anyway. The round-robin paces itself: with nine
on the bench each is re-tested roughly every nine rounds.

The dashboard also offers a manual release button, for overriding the machine
rather than waiting for it.

Rounds walk the least-measured CDN first. A round that always restarted at
the top of the list would re-measure the opening CDNs after every
interruption - an update, a crash, a reboot - and never reach the tail;
observed live as one CDN with five rounds beside another with one. Ordering by
coverage makes the next round repair that rather than compound it.

## How long a round takes

Measured on a live account: **1.6 to 2.5 hours** for a full pass over 19
CDNs, or about **50 minutes** once benching has trimmed the rotation to ten.

Most of that is spent letting a switch take over before measuring it — see
below. The limit is not the measuring, which takes about two minutes per CDN. It is
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

## Two copies: one steering, one watching

`OBSERVE_ONLY=true` turns a copy into an observer. A round stops being a walk
over every CDN and becomes a single measurement of whichever CDN the account
is already on; the CDN select is never written to, not by the round and not by
`AUTO_APPLY`. `ROUND_PAUSE` decides how often it looks - a passive round takes
minutes rather than hours, so `30m` is a reasonable gap.

```env
OBSERVE_ONLY=true
ROUND_PAUSE=30m
```

Two things make this worth having. It is safe to point at the account you
actually watch, because nothing is re-routed. And it lets a second machine
watch an account that another copy - in Docker elsewhere, say - is switching:
two copies both driving the select would fight each other, and each would
record the other's CDN under its own name.

The CDN is read from the panel before the measurement and again after it. If
the other copy switched the account in between, the sample covers two CDNs at
once, so it is dropped rather than filed under either name. A mislabelled
round is worse than a missing one: it goes into the median and argues for the
wrong CDN for as long as it is kept.

Give the observer its own data volume if you want its numbers kept apart from
the active copy's; point both at the same one and the journals merge, which is
usually not what you want, because the observer's samples all describe the CDN
the other copy happened to be testing.

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

A CDN is called out for dropping only when the dips repeat - at least two
rounds under the floor, and a quarter of its rounds. A lone dip is noise: a
measurement caught mid-propagation, or a moment of congestion. Letting one
overrule a healthy median is the same mistake the median exists to avoid. The
dip is still counted and shown, it just no longer decides alone.

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
