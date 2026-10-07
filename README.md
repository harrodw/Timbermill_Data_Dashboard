# Timbermill Wind & Wildlife — data progress dashboard

A static dashboard reporting annotation progress for the 2026 field season of
*Harnessing Wind Energy within Industrial Forests: Effects on Wildlife*
(Will Harrod, NC State University; Chowan County, North Carolina).

**Published figures remain preliminary.** Bucket-camera identifications are
complete; acoustic bird detections are filtered to per-species validated
cutoffs; anuran detections are not validated at all. The site carries that
caveat as a sticky banner that also survives printing, so a screenshotted or
printed chart keeps it.

---

## How it works

The dashboard is deliberately split in two, because the raw data cannot be
published:

```
data/  ──►  build/build_summaries.py  ──►  docs/data/*.json  ──►  docs/index.html
(private,   aggregates locally,           summaries only,        static site
 git-ignored)  ~15 seconds                ~440 KB total          (GitHub Pages)
```

Nothing under `data/` is ever committed or copied into `docs/`. The pipeline
reads the Wildlife Insights export, the cleaned AHDriFT detection table and
3.57 million BirdNET detections, and writes only aggregate counts. `docs/` is
fully self-contained: Leaflet and Plotly are vendored into
`docs/assets/vendor/`, so the site renders with no network access at all (the
only exception is the background map tiles — markers, legend, charts and all
data still render without them).

## Which file backs which view

This is the part that changed most recently, and getting it wrong would
double-count the bucket cameras:

| View | Source | Unit |
|---|---|---|
| Bucket cameras (AHDriFT) | `data/Clean_AHDriFT_Data/ahdrift_data_cleaned.csv` | detection events |
| Parallel cameras | `data/WI_Download/sequences.csv`, **CT deployments only** | sequences |
| Bird & frog audio | `preliminary_BirdNET_Results.csv` + `BirdNet_Thresholds.csv` | classifier detections |

The Wildlife Insights export still contains 4,945 AHDriFT sequences. They are
**not used anywhere on the dashboard**: the cleaned table carries the final
identifications and — critically — one row per surveyed plot-day that produced
nothing. Those recorded zeroes are what make survey effort, detection rate and
naive occupancy computable for the bucket cameras at all.

## Layout

| Path | Committed | Purpose |
|---|---|---|
| `build/build_summaries.py` | yes | The pipeline. Run from the repo root. |
| `build/make_photos.py` | yes | Photo selection, resize, EXIF strip. |
| `build/make_spectrograms.py` | yes | ARU clip spectrograms + audio transcode. |
| `build/make_media_json.py` | yes | Captions and the media manifest. |
| `build/stamp_assets.py` | yes | Cache-busts the JS/CSS URLs. Run last. |
| `build/photo_selection.json` | yes | Generated: which photo was published per taxon, with its Wildlife Insights identification. |
| `docs/index.html` | yes | The dashboard. GitHub Pages serves this folder. |
| `docs/assets/` | yes | CSS, six ES modules, vendored Leaflet + Plotly. |
| `docs/data/*.json` | yes | Generated summaries. Safe to publish. |
| `docs/media/` | yes | Web-sized, EXIF-stripped photos, spectrograms, audio. |
| `data/` | **no** | Source data. Git-ignored. |
| `private/` | **no** | Verification scripts and screenshots. Git-ignored. |

## Rebuilding

```bash
cd /home/will/NCSU/Claude_Science/2026_Sensor_Dashboard
python build/build_summaries.py     # ~15 s; rewrites docs/data/*.json
```

Requires `pandas`. Re-run it whenever you re-export from Wildlife Insights,
re-run BirdNET, update the cleaned AHDriFT table, or **edit
`BirdNet_Thresholds.csv`** — that last one changes every acoustic count on the
site.

The media assets are built by three further scripts, needed only when photos
or audio change:

```bash
python build/make_photos.py        # jpgs  -> docs/media/photos/ (EXIF stripped)
python build/make_spectrograms.py  # clips -> docs/media/spectrograms/ + audio/
python build/make_media_json.py    # captions -> docs/data/media.json
python build/build_summaries.py    # again, so the manifest picks up media counts
```

`make_photos.py` strips EXIF by rebuilding each image pixel-by-pixel, which
matters: camera-trap files can carry GPS and device serials. Run it on any new
image before it reaches `docs/`.

### Always finish with the asset stamp

```bash
python build/stamp_assets.py
```

`index.html` is revalidated on every load and the JSON is fetched with
`cache: 'no-cache'`, but the six ES modules are ordinary subresources that a
browser will keep serving from cache. After a push that changes both the
summary schema and the code reading it, that gives **new HTML + new JSON + old
JavaScript**, which does not throw — it silently draws an empty chart. It
happened once: the species panel reported "no species rows with detections
above zero" because the cached August module looked for `n_sequences` while the
rebuilt AHDriFT file publishes `n_detections`, and the activity and rate panels
stayed blank because that module has no code for them.

`stamp_assets.py` appends `?v=<content-hash>` to every import between our own
modules and to the two references in `index.html`, so a stale module is a URL
the browser has never seen. It is idempotent and the token is a function of the
code alone, so re-running without a change is a no-op. Vendored Leaflet and
Plotly are deliberately left unstamped — they never change and staying cached
is the point of vendoring them.

If you ever see a panel that is empty rather than erroring, hard-reload
(Ctrl/Cmd-Shift-R) first and check whether the stamp ran.

## BirdNET confidence cutoffs

For each species, 150 detections were reviewed by ear and the lowest confidence
at which 95% of them were true positives was recorded in
`data/Bird_Frog_Audio_Summaries/BirdNet_Thresholds.csv`. The pipeline applies
each cutoff to its own species and splits the 80 BirdNET labels into four
states, which the dashboard keeps separate rather than averaging:

| Group | n species | What is shown |
|---|---|---|
| Validated birds | 47 | only detections at or above that species' cutoff |
| No attainable cutoff | 5 | raw detections, flagged; 95% was never reached at any confidence, so the log carries a nominal 1.0 |
| Frogs and toads | 11 | raw detections, unvalidated |
| Birds awaiting validation | 12 | raw detections, unvalidated |

Plus 5 anthropogenic and domestic labels (engine, gunshot, human, dog), kept
visible on the validation table and excluded from every species and activity
figure.

Filtering is not cosmetic: across the 47 validated species it keeps 1,740,770
of 2,637,897 raw detections — 66%. Cutoffs run from 0.25 to 0.95 with a median
of 0.44, and ten species sit at the 0.25 floor.

To add a cutoff, fill in the `Threshold` column for that species and re-run the
pipeline. A species with a blank threshold and class `Amphibia` lands in the
frog group; blank and `Aves` lands in the queue. Nothing is inferred beyond
that, and a label with no row in the file at all is excluded from every figure
and reported under "Known data gaps".

### Why the per-species listening rate is not a precision figure

The table reports, per species, the share of reviewed clips that were genuinely
that species. That describes **the clips that were listened to**, which were
chosen to locate each cutoff — not a random sample of the species' detections.
It is validation effort, not the precision of the published counts, and is
labelled that way everywhere it appears. No pooled "overall precision" number
is published anywhere on the site.

## Activity curves

Half-hour histograms of detection time are smoothed with a Gaussian kernel
(σ = 1.4 bins ≈ 42 min) and scaled to unit area, which makes curve **shapes**
comparable between plot types with very different totals; the totals themselves
are printed beside the chart and in every hover.

The kernel wraps around midnight **only when the sensor sampled the whole
clock**. For the cameras it does: a detection at 23:50 is twenty minutes from
one at 00:10, and a non-circular smoother would invent a trough at midnight.
For the ARUs it must not — see the next section.

Each panel has a **plot-type toggle**. "Separate" draws one curve per plot type;
"Combined" pools them into a single curve by summing counts *and* effort before
dividing. Pooling the two separately is deliberate: averaging four per-plot-type
densities would give Interior Forest, with the least effort behind it, the same
weight as Turbine Opening. Summing first weights each plot type by the survey
effort actually behind it.

Shaded bands are 95% intervals from propagating Poisson counts through the same
kernel. They are the honest brake on over-reading a single-species curve: pick
a taxon with thirty detections and the band is wider than the curve.

**The ARU curves are effort-corrected and the camera curves are not**, which is
not an inconsistency. Cameras ran continuously, so every half-hour of the clock
got equal watching and the denominator cancels. The ARU schedule does not:
roughly 1,800 five-minute recordings per hour through the night, a 60-minute
recording over the dawn chorus, and only about 65 recordings *all season* for
each midday hour. A raw histogram of BirdNET detection times would therefore
show a dawn spike and an empty afternoon that are mostly an artefact of when
the recorders were on. The acoustic panel plots detections per recording-hour,
reconstructed from all 29,096 recording files.

### The acoustic curves are clipped to the recorded window

Effort correction fixes the *shape* of the curve but not its *extent*: dividing
a handful of midday detections by a handful of midday recording-hours produces
a noisy, wildly uncertain density across two-thirds of the x-axis that the
schedule never meant to sample. So the acoustic panel draws only the half-hours
the recorders actually covered, **17:30 → 08:30** (30 of 48 bins, 15 hours),
and the x-axis is labelled with that window.

The window is derived, not typed in. A bin counts as sampled when it carries at
least 3% of the peak bin's recording effort. That threshold sits inside a wide
empirical gap rather than being a round number: the daytime plateau never
exceeds ~2.1% of peak, and no scheduled bin falls below ~3.6%. The resulting
window holds **93.9% of all recording effort** and 95.8% of detections above
cutoff.

Two things follow, and both are published in `birdnet.json` so the panel can
state them rather than hide them:

- **The schedule is solar-anchored, not fixed-clock.** The median first file of
  the night moves from 17.9 h in March to 19.6 h in August, tracking sunset.
  Measured against computed sunset for the study site, recording starts a median
  of **1.4 hours *before* sunset** — not at sunset — and ends a median of 0.5
  hours after sunrise. The published window is the envelope across the whole
  season, so on any individual night the recorder started somewhat inside it.
- **4.3% of detections fall outside the window and are not drawn.** Every one
  of them comes from 590 off-schedule daytime recordings at just four plots —
  IF07, TO04, RE05 and TO15. That was checked at record level, not assumed: of
  the 73,068 excluded detections in the validated group, 100% trace to those
  four plots and none to any other. The counts are published as
  `activity.off_schedule.n_detections_excluded` so the activity panel and the
  species chart can be reconciled.

Because dusk and morning are 14 hours apart rather than adjacent, the smoother
is **not** wrapped for the acoustic curves; wrapping would smear the dawn
chorus backwards into the previous evening. The x-axis runs past 24 (17:30 is
17.5, 08:30 is 32.5) so the night reads left to right as one continuous series,
and tick labels are rewritten back to clock time.

Recording length is inferred per file from the largest detection offset it
contains. The two scheduled lengths separate cleanly — no file in the dataset
has a maximum offset between 300 and 310 s — so the inference is safe; the
residual error is a 60-minute file whose only detections fell in its first few
minutes, which would be scored short and slightly under-state effort in that
bin.

## Detection rate and naive occupancy

Back-to-back bars, one pair per taxon: naive occupancy on a reversed left axis,
detection rate on the right. The two are deliberately **not** combined into an
index. Occupancy is how widespread a taxon is; rate is how often it was
recorded per unit effort. A taxon can be everywhere but rarely, or
concentrated but prolific, and keeping both visible is the point.

The site unit differs by sensor and the chart says which it is using:

| View | Site | Effort denominator |
|---|---|---|
| Bucket cameras | plot (50) | 8,979 hut-days over 5,582 array-days |
| Parallel cameras | camera station (151) | 5,967 camera-days |

An AHDriFT array is one or two camera huts at a plot, so rate is per hut-day:
a plot that ran one hut is not credited with two huts' worth of opportunity.
Parallel cameras are independent stations, three to six per plot, so occupancy
is over stations rather than plots.

Naive occupancy is an **observed proportion, uncorrected for imperfect
detection** — a floor on true occupancy, not an estimate of it. That is what
the multi-species occupancy model is for.

The acoustic view carries no rate chart. Recording hours are not comparable to
trap-days, and a plot-level "occupancy" built from unvalidated classifier hits
would not mean what the figure implies.

## Basemaps

A switcher in the top right of the map offers four options, all **keyless**:
Esri topographic (the default — light and labelled, so the plot-type marker
colours stay legible), Esri aerial imagery, OpenStreetMap, and No basemap.

The aerial layer is worth knowing about: the stand boundaries, harvest openings
and turbine clearings that the plot types are *defined* by are visible in it
and invisible on a street map.

This panel used CARTO's open `light_all` endpoint until CARTO moved its
basemaps behind an API key. An unauthenticated request now returns a
placeholder tile reading "API key required", which is worse than no basemap:
it renders as content rather than failing, so the tile-error handler never
fires and the map looks broken rather than degraded. Hence a switchable set —
the next provider to change its terms costs a click, not a code edit. To change
the default, edit `BASEMAP_DEFAULT` at the top of `docs/assets/js/map.js`.

**OpenStreetMap is offered but is not the default, on purpose.** Those tiles
come from volunteer infrastructure under a usage policy that asks not to be
treated as a free CDN for websites, and a request without an identifying
User-Agent is refused with a "403 Access blocked" tile — verified directly
while testing this change. Fine for local use; the wrong thing to point a
published, shared dashboard at.

Sensor markers, the legend and the coordinate-precision note are all drawn from
local data and stay correct with no basemap at all, which is the point of the
"No basemap" option and of vendoring Leaflet.

## Map popups

Hovering a marker lists the species recorded by that sensor and how many times;
clicking pins the full list, which for an ARU plot runs to sixty-odd rows and
scrolls.

The three streams resolve to different spatial units and the popup labels which
one it is using. Parallel-camera sequences belong to the individual camera
station. The cleaned AHDriFT table and the BirdNET output are both recorded at
the plot — there is exactly one AHDriFT array and one ARU per plot, so nothing
is lost, but the popup still says "the AHDriFT array at plot IF01" rather than
implying a point-level tally.

## Photo album

One photograph per reptile and amphibian taxon, plus the mammal frames the
album already carried. Black bear keeps three: a bear filling a bucket mouth
and a sow with cubs crossing a thinned stand are different photographs of
different things.

The reptile and amphibian photos are filed one directory per taxon under
`data/AHDriFT_Photos/`, with Wildlife Insights export filenames carrying the
image UUID. That UUID is the join key into `images_2011183.csv`, so every
caption's species, plot, schedule and timestamp comes from the Wildlife
Insights identification **of that exact frame** rather than from the directory
name. This is load-bearing: one file filed under `T.saurita/` is identified in
Wildlife Insights as a common gartersnake (*Thamnophis sirtalis*), not a ribbon
snake, and the album follows the identification. Six hand-exported originals
have no image record to join against; their identification is the researcher's
own and is labelled as such in the lightbox.

Several directory names carry a trailing space (`A.terestris/`), which is
invisible in a listing. `make_photos.py` resolves each selection by filename
when its literal path does not exist, so the album does not break on that.

Twenty-one of the twenty-seven published frames carry a Wildlife Insights
identification, out of 76 candidates on disk. To change a selection, edit
`PICKS` in `build/make_photos.py` and re-run the three media scripts.

Ten of the album's reptile and amphibian frames show a taxon that does **not**
appear in the cleaned motion-capture table: copperhead, wormsnake, ring-necked
snake, DeKay's brownsnake, ribbonsnake, gartersnake, broadhead skink,
salamander, spotted turtle, and one snake identified only to Squamata.

Seven of the ten came from the time-lapse schedule, which the cleaned table
does not cover, so their absence is expected. The spotted turtle is a
hand-exported original with no Wildlife Insights record at all. The remaining
two are **motion-capture** frames, which the cleaned table does cover:
broadhead skink, whose records the cleaned list carries one rank up as
`Plestiodon Species`, and ring-necked snake, which the cleaned list has no
entry for at any rank. Since that table is your final species set — "only the
species I care about" — the ring-necked snake is presumably a deliberate
exclusion rather than a gap, but it is the one case where a motion-capture
photograph shows an animal the detection data does not acknowledge, and worth
a glance.

The album states the absence on each tile rather than letting a missing count
read as a zero.

## What the numbers mean

Three counting units appear and none are interchangeable:

- **AHDriFT detection events** — one motion-capture sequence of one taxon at
  one array, identified by the researcher. Identification is complete for the
  season, and plot-days with no detection are recorded explicitly, so these
  counts are complete rather than in progress. Events are counted as rows:
  the export carries 0 in both `n.Seq` and `Max.Group.Size` for every row, so
  neither a sequence count nor a group size is used anywhere.
- **Wildlife Insights sequences** — an identification unit (a burst of images
  of one species at one camera), not a count of individual animals. Vehicle,
  blank, human and coarse-group labels are excluded from the species charts and
  counted separately. Labels above genus (`Passeriformes Order`,
  `Cathartidae Family`) are excluded by rank; genus-level labels
  (`Corvus Species`) are kept, because they are the same kind of unit as the
  cleaned AHDriFT list's `Plestiodon Species`.
- **BirdNET detections** — classifier hits on 3-second windows. Validated
  species are filtered to their own cutoff; every other group is raw, and the
  group selector says which.

### Scaling the species chart by effort

The species chart has a **Scale** control: raw counts, or detections per 100
units of survey effort. The denominator is per plot type, not one figure for
the whole view, because effort is badly unbalanced:

| View | Unit | TO | TE | IF | RE |
|---|---|---|---|---|---|
| Bucket cameras | hut-days | 2,864 | 2,716 | 1,773 | 1,626 |
| Parallel cameras | camera-days | 1,581 | 1,753 | 941 | 1,692 |
| Bird & frog audio | recording-hours | 4,862 | — | 2,501 | 2,247 |

Interior Forest ran roughly 60% of Turbine Opening's camera effort, so a raw
stacked bar makes Interior Forest look quieter than it is. Scaling divides each
*segment* of the bar by its own plot type's effort, so the segments stay
comparable to each other and the total becomes a pooled rate. Hovers keep the
unscaled count visible ("N records before scaling") so nothing is lost.

This is a different question from the rate-vs-occupancy chart. Scaling here
reweights the composition of a stacked bar across plot types; the christmas
tree asks how often versus how widely a single taxon was recorded. The
activity panel is corrected for the ARUs only, for the reason given above.

## Map coordinates are deliberately wrong

Published sensor positions are displaced 41–165 m (median 94 m) from their true
locations along a fixed pseudo-random bearing, then rounded to three decimal
places. This is intentional: the sensors sit on private industrial forest land
and the detections include species of conservation concern. The offset is
deterministic, so markers do not move between rebuilds.

Full-precision coordinates stay in `data/`, which is git-ignored. Do not "fix"
the map by publishing the real coordinates.

## Known data gaps

Published in the page footer, not hidden; see `data_gaps` in `manifest.json`.

- **ARU plot IF10** has 7 recording days in the BirdNET output (2–8 March 2026)
  but no entry in `cam_trap_locations_info.csv` and no Wildlife Insights
  deployment, so it cannot be mapped. Its detections still appear in the
  species, activity and effort panels. Worth checking whether this plot was
  retired early or is simply missing from the location table.
- **IF09-CT01 and TE02-CT04** have Wildlife Insights deployments but no row in
  the location table, so they contribute effort and detections but no marker.
- **Tree Frog Species** is the one reptile or amphibian in the cleaned AHDriFT
  table with no photograph in the album.
- **Audio clips carry no plot or date.** The five example clips are named for
  the species they contain, and that identification — yours, made by listening
  — is what the panel shows. The filenames carry no recorder, plot or
  timestamp and the files hold no embedded metadata, so no location or date is
  attributed to a clip; the context shown beside each is season-wide for the
  species and labelled as such. Re-exporting with the recorder and timestamp in
  the filename would let the panel name the plot and date again.

  Species names are cross-checked against `birdnet.json` at build time: an
  unrecognized filename is reported and skipped rather than published without
  a Latin name. To add a clip, drop the WAV in `data/Audio_Data/` and add its
  filename stem to `CLIP_SPECIES` in `build/make_spectrograms.py`.

## Verification

`private/` holds the harnesses (git-ignored, reusable after any rebuild):

```bash
node private/frontend_check.mjs              # 1,635 assertions against the real JSON
cd docs && python3 -m http.server 8000 &     # then:
python3 private/shots.py http://localhost:8000/ private/shots_new
```

`frontend_check.mjs` runs the dashboard's own selector functions against the
published summaries and checks the things a glance at the page cannot: that
every activity curve integrates to 1 over the window it was drawn on, that the
sampled window is contiguous in clock time, that a windowed curve does *not*
close at midnight while a fully sampled one does, that the combined curve's
counts and effort equal the sum of the separate ones, that every plot type
carrying detections also carries an effort denominator, that per-plot-type
counts sum to each taxon's total, that occupancy equals sites-detected over
sites, that rate equals count over effort, that map popup tallies reconcile
with the species files, that filtering never increases a count, and that every
herp taxon is either in the album or declared a gap. It stages the ES modules into `private/.jscheck/` so
Node reads them as modules without a `package.json` being published in `docs/`.

`shots.py` renders all three views in headless Firefox, forces lazy images to
load, opens a map popup on each view, exercises the class and species filters,
and prints a JSON probe of what actually rendered — element visibility, Plotly
trace counts, image load state, error slots. A panel that renders blank is
caught by the numbers rather than only by eye.

Rendering was verified in headless Firefox only. A pass in Chrome or Safari
before the next meeting would be prudent.

## Publishing to GitHub Pages

**This is already set up.** The remote is
`https://github.com/harrodw/Timbermill_Data_Dashboard.git`, the branch is
`main`, and Pages serves the `/docs` folder at
<https://harrodw.github.io/Timbermill_Data_Dashboard/>. Publishing an update is
commit and push; none of the one-time setup needs repeating.

### Updating the live site

```bash
cd /home/will/NCSU/Claude_Science/2026_Sensor_Dashboard

# 1. rebuild (see "Rebuilding" above for when the media scripts are needed too)
python build/build_summaries.py
python build/stamp_assets.py      # never skip: this is what busts the JS cache

# 2. check nothing private is staged — the only step worth not skipping
git status --porcelain | grep -E '^\?\? (data|private)/' || echo "clean"
git ls-files | grep -cE '^(data|private)/'        # must print 0

# 3. commit and push
git add -A
git commit -m "Describe what changed"
git push
```

Pages redeploys automatically on push and takes about a minute. A hard reload
(Ctrl/Cmd-Shift-R) clears the old JSON out of the browser cache if the numbers
look stale.

### If git asks who you are

`user.name` and `user.email` are not currently set in this clone, so
`git commit` will stop with *"Please tell me who you are."* The three existing
commits were authored as `Will Harrod <wdharrod@ncsu.edu>`; to keep the history
consistent:

```bash
git config user.name  "Will Harrod"
git config user.email "wdharrod@ncsu.edu"
```

Without `--global` this applies to this repository only.

### Authentication

Pushing over HTTPS needs a GitHub personal access token as the password (an
account password will be rejected). If the push prompts and fails, either
create a token with `repo` scope under **GitHub → Settings → Developer
settings → Personal access tokens**, or switch the remote to SSH:

```bash
git remote set-url origin git@github.com:harrodw/Timbermill_Data_Dashboard.git
```

### If Pages ever needs re-pointing

**Settings → Pages**, Source **Deploy from a branch**, branch **main**, folder
**`/docs`**.

### Sharing the link

The site sets `noindex, nofollow`, so search engines will not list it — but a
public repository is still public to anyone with the URL. For sharing with
Apex, TNC, or conference attendees that is usually what you want. If you need
it genuinely restricted, use a private repository with Pages on a paid plan.

## Credits

Field data and photographs: W. Harrod / NC State University.
Wildlife identifications: project team via Wildlife Insights.
Advisers: Christopher E. Moorman (NC State), Liz Kalies (The Nature Conservancy).
Site access and support: Apex Clean Energy, Weyerhaeuser.
Basemaps: © OpenStreetMap contributors; imagery and topographic tiles © Esri,
Maxar, Earthstar Geographics and the GIS User Community.
