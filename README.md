# Timbermill Wind & Wildlife — data progress dashboard

A static dashboard reporting annotation progress for the 2026 field season of
*Harnessing Wind Energy within Industrial Forests: Effects on Wildlife*
(Will Harrod, NC State University; Chowan County, North Carolina).

**All published figures are preliminary and unvalidated.** The site carries that
disclaimer as a sticky banner that also survives printing, so a screenshotted or
printed chart keeps its caveat.

---

## How it works

The dashboard is deliberately split in two, because the raw data cannot be
published:

```
raw_data/  ──►  build/build_summaries.py  ──►  docs/data/*.json  ──►  docs/index.html
(private,        aggregates locally,           summaries only,        static site
 git-ignored)    ~12 seconds                   ~230 KB total          (GitHub Pages)
```

Nothing under `raw_data/` is ever committed or copied into `docs/`. The pipeline
reads 565 MB of Wildlife Insights exports and 3.6 million BirdNET detections and
writes only aggregate counts. `docs/` is fully self-contained: Leaflet and Plotly
are vendored into `docs/assets/vendor/`, so the site renders with no network
access at all (the only exception is the background map tiles — markers, legend
and all data still render without them).

## Layout

| Path | Committed | Purpose |
|---|---|---|
| `build/build_summaries.py` | yes | The pipeline. Run from the repo root. |
| `build/validation_log.csv` | yes | Your BirdNET validation tally — **edit this by hand**. |
| `docs/index.html` | yes | The dashboard. GitHub Pages serves this folder. |
| `docs/assets/` | yes | CSS, six ES modules, and vendored Leaflet + Plotly. |
| `docs/data/*.json` | yes | Generated summaries. Safe to publish. |
| `docs/media/` | yes | Web-sized, EXIF-stripped photos, spectrograms, audio. |
| `raw_data/` | **no** | Source data. Git-ignored. |
| `private/` | **no** | Verification scripts and screenshots. Git-ignored. |

## Rebuilding the summaries

```bash
cd /home/will/NCSU/Claude_Science/2026_Sensor_Dashboard
python build/build_summaries.py
```

Requires `pandas`. It rewrites the six JSON files under `docs/data/` and
refreshes `build/validation_log.csv`, preserving any counts you have entered.
Re-run it whenever you re-export from Wildlife Insights, re-run BirdNET, or log
more validations — then commit and push.

The media assets are built by three separate scripts, which only need re-running
when you add new photos or audio clips:

```bash
python build/make_spectrograms.py   # ARU clips  -> docs/media/spectrograms/
python build/make_photos.py         # jpgs       -> docs/media/photos/ (EXIF stripped)
python build/make_media_json.py     # captions   -> docs/data/media.json
```

`make_photos.py` strips EXIF, which matters: 9 of the 12 source photographs
carried Exif blocks that can include GPS coordinates and device serial numbers.
Run it on any new image before it reaches `docs/`.

## Tracking BirdNET validation progress

**150 recordings are validated per species**, drawn *stratified across
confidence bins*. A logistic regression of true-positive outcome on BirdNET
confidence then gives the cutoff where P(true positive) = 0.95; detections at
or above that cutoff are the positives carried into the multi-species occupancy
model. Total workload: **11,730 validations** across 84 species. It currently
reads 0%.

To record progress, edit **`build/validation_log.csv`**. It has one row per
species per confidence bin (641 rows), and you fill in two columns:

| column | meaning |
|---|---|
| `n_checked` | how many detections **in that confidence bin** you have listened to |
| `n_true_positive` | how many of those were genuinely that species |

Everything else (`confidence_bin`, `n_available`, `target`) is regenerated and
can be left alone; `notes` is yours. Counts you have entered are preserved
across rebuilds, keyed on species + bin, so re-running the pipeline after new
BirdNET output never discards validation work.

### Why stratified, and what that costs

Raw confidences are concentrated near the 0.25 floor (median 0.43, 25th
percentile 0.28). A simple random 150 would therefore put almost nothing near
the crossing point — for pickerel frog, about *one* of 150 draws would land at
or above 0.90, and for Swainson's warbler 130 of 150 would fall below 0.40. The
0.95 cutoff would be extrapolated rather than estimated.

Allocating roughly 19 validations to each of eight bins from 0.25 to 1.0 puts
data on both sides of the crossing. The cost is that **validated detections are
no longer a random sample**, so the pooled true-positive rate over your
validated clips is *not* the precision of the dataset. The dashboard therefore
reports per-stratum rates and the fitted curve, and deliberately publishes no
"overall precision" figure. The fitted curve is the object of interest, which
is what the threshold approach needs anyway.

A cutoff appears only once a species has validations in **at least two**
confidence bins. Until then the table reads "not started". Where the fit runs
but cannot identify a cutoff — precision not increasing with confidence, or
0.95 never reached inside the confidence range — the table says "not
identifiable" and the reason is in the tooltip and in `species[].fit.reason`.
No number is invented in those cases.

### Tuning the design

Near the top of `build_summaries.py`:

| constant | effect |
|---|---|
| `VALIDATION_N_PER_SPECIES` | validations per species (currently 150) |
| `VALIDATION_TARGET_P` | target true-positive probability (currently 0.95) |
| `VALIDATION_BIN_EDGES` | the confidence strata |
| `VALIDATION_POOL_THRESHOLD` | the retained-detection floor (currently 0.25) |

Changing bin edges rewrites the log's row set. Counts are matched on the bin
label, so **keep a copy of the log before changing the edges** — rows whose
label no longer exists are dropped.

## Adding the bat and vegetation views

Both already appear in the toggle as "planned" with a description of the pending
work. To activate one:

1. Add the raw export under `raw_data/`.
2. Add a `build_bats()` / `build_vegetation()` function to
   `build/build_summaries.py` that writes `docs/data/bats.json` (follow the
   shape of `birdnet.json`) or `docs/data/vegetation.json`.
3. In the `views` list near the bottom of `main()`, change that view's
   `"status"` from `"pending"` to `"available"` and fill in its counts.
4. For a species chart, add the view id to the species-file mapping in
   `docs/assets/js/charts.js`.

The toggle, headline stats and pending states are all generated from
`manifest.json`, so steps 1–3 are usually the whole job. Adding a sixth view is
a pipeline change, not an HTML change.

## Publishing to GitHub Pages

The repository is already initialized and committed. To publish:

**1. Create an empty repository on GitHub.** Do not add a README, license, or
`.gitignore` — this repo has its own. Note whether it is public or private
(Pages on a private repo requires a paid plan).

**2. Add the remote and push:**

```bash
cd /home/will/NCSU/Claude_Science/2026_Sensor_Dashboard
git remote add origin https://github.com/harrodw/Timbermill_Data_Dashboard.git
git branch -M main
git push -u origin main
```

**3. Enable Pages.** In the repository on GitHub: **Settings → Pages**. Under
"Build and deployment" set Source to **Deploy from a branch**, then branch
**main** and folder **`/docs`**. Save.

**4. Wait about a minute**, then visit
`https://<your-username>.github.io/<repo-name>/`.

Subsequent updates are just:

```bash
python build/build_summaries.py
git add -A
git commit -m "Update summaries"
git push
```

Pages redeploys automatically on push.

### Before you push — a 20-second check

```bash
git status --porcelain          # should list nothing from raw_data/ or private/
git ls-files | grep -c raw_data # must print 0
```

The `.gitignore` handles this, but the data is unpublished and the check is
cheap.

### Sharing the link

The site sets `noindex, nofollow`, so search engines will not list it — but a
public repository is still public to anyone with the URL. For sharing with Apex,
TNC, or conference attendees that is usually what you want. If you need it
genuinely restricted, use a private repository with Pages on a paid plan.

## What the numbers mean

Two different counting units appear on the dashboard and they are not
comparable:

- **Wildlife Insights sequences** — an identification unit (a burst of images of
  one species at one camera), not a count of individual animals. Only
  human-reviewed sequences are counted; the remainder carry MegaDetector output
  awaiting expert review. Vehicle and blank sequences are excluded.
- **BirdNET detections** — raw classifier hits on 3-second windows, with no
  validation. These are not verified occurrences and include false positives at
  an unknown rate. That rate is exactly what the validation workflow above
  measures.

Neither is corrected for survey effort, which differs substantially among
sensors — the effort chart shows how much. Sensor-day totals exclude
zero-length and disrupted deployments, so they run slightly below the raw
counts in the TNC progress report. AHDriFT arrays log a motion-capture and a
time-lapse schedule for the same physical camera; these are collapsed so effort
is not double counted.

## Map coordinates are deliberately wrong

Published sensor positions are displaced 41–165 m (median 94 m) from their true
locations along a fixed pseudo-random bearing, then rounded to three decimal
places. This is intentional: the sensors sit on private industrial forest land
and the detections include species of conservation concern. The offset is
deterministic, so markers do not move between rebuilds, and 229 sensor points
collapse to 178 distinct published positions.

Full-precision coordinates stay in `raw_data/`, which is git-ignored. Do not
"fix" the map by publishing the real coordinates.

## Known data gaps

The dashboard surfaces these rather than hiding them; see `data_gaps` in
`manifest.json`.

- **ARU plot IF10** has 8 recording days in the BirdNET output (1–8 March 2026)
  but no entry in `cam_trap_locations_info.csv` and no Wildlife Insights
  deployment, so it cannot be mapped. Its detections still appear in the species
  and effort panels. Worth checking whether this plot was retired early or is
  simply missing from the location table.
- **`gartersnake.jpg`** is filed under `raw_data/CT_photos/` but is
  unmistakably an AHDriFT bucket interior, so it is presented under the bucket
  camera view. Worth correcting at the source.
- **`Spottie!.jpg`** is a spotted turtle (*Clemmys guttata*), not a spotted
  skunk, and is captioned accordingly.
- **Audio clips carry no plot or date.** The five example clips are named for
  the species they contain (`pine_warbler.wav`), and that identification —
  yours, made by listening — is what the panel shows. But unlike the earlier
  `SMM2-<unit>_<date>_<time>` exports, these filenames carry no recorder, plot
  or timestamp, and the files hold no embedded metadata, so no location or date
  is attributed to a clip. The context shown beside each is season-wide for the
  species, labelled as such. Re-exporting with the recorder and timestamp in
  the filename would let the panel name the plot and date again.

  The species names are cross-checked against `birdnet.json` at build time: an
  unrecognized filename is reported and skipped rather than published without a
  Latin name. To add a clip, drop the WAV in `raw_data/Audio_Data/` and add its
  filename stem to `CLIP_SPECIES` in `build/make_spectrograms.py`.

## Verification scripts

`private/` holds the harnesses used to check the build (git-ignored, reusable
after any rebuild):

```bash
node private/frontend_check.mjs        # 166 assertions against the real JSON
cd docs && python3 -m http.server 8000 # then open http://localhost:8000/
python3 private/shot.py http://localhost:8000/ private/shots bucket_camera
```

Rendering was verified in headless Firefox only. A quick pass in Chrome or
Safari before the October Wind Wildlife Research Meeting would be prudent.

## Credits

Field data and photographs: W. Harrod / NC State University.
Wildlife identifications: project team via Wildlife Insights.
Advisers: Christopher E. Moorman (NC State), Liz Kalies (The Nature Conservancy).
Site access and support: Apex Clean Energy, Weyerhaeuser.
Basemap: © OpenStreetMap contributors, © CARTO.
