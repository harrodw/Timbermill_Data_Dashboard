/* ==========================================================================
   data.js -- shared constants, loading, and formatting helpers.

   Every number on the page comes from ./data/*.json at runtime; nothing from
   the summaries is hardcoded here. All paths are relative so the site works
   from a file:// directory listing and from a GitHub Pages project subpath.
   ========================================================================== */

/* Canonical plot-type order and colors. These are a project-wide convention
   (see manifest.plot_types), not data, so they live in code. */
export const PLOT_TYPES = [
  'Turbine Opening',
  'Turbine Edge',
  'Interior Forest',
  'Reference Edge'
];

export const PLOT_COLORS = {
  'Turbine Opening': '#C1666B',
  'Turbine Edge':    '#E4A05E',
  'Interior Forest': '#4F7942',
  'Reference Edge':  '#6B8EAD'
};

export const UNKNOWN_COLOR = '#9aa4ad';

export function plotColor(pt) {
  return PLOT_COLORS[pt] || UNKNOWN_COLOR;
}

/** Canonical-order index; unknown types sort last but stay visible. */
export function plotTypeRank(pt) {
  const i = PLOT_TYPES.indexOf(pt);
  return i === -1 ? PLOT_TYPES.length : i;
}

/** Order an arbitrary set of plot types canonically, keeping unknowns. */
export function orderPlotTypes(types) {
  return Array.from(new Set(types)).sort(
    (a, b) => plotTypeRank(a) - plotTypeRank(b) || String(a).localeCompare(String(b))
  );
}

/* ------------------------------------------------------------------ loading */

export const DATA_DIR = './data/';

/**
 * Fetch one JSON summary. Rejects with a human-readable Error so panels can
 * print something specific instead of failing silently to the console.
 */
export async function loadJSON(name) {
  const url = DATA_DIR + name;
  let res;
  try {
    res = await fetch(url, { cache: 'no-cache' });
  } catch (err) {
    throw new Error(
      `Could not read ${url} (${err && err.message ? err.message : 'network error'}). ` +
      `If this page was opened directly from disk, serve the docs/ directory over HTTP instead.`
    );
  }
  if (!res.ok) {
    throw new Error(`Could not read ${url} -- server returned HTTP ${res.status} ${res.statusText}.`);
  }
  try {
    return await res.json();
  } catch (err) {
    throw new Error(`${url} is not valid JSON (${err && err.message ? err.message : 'parse error'}).`);
  }
}

/** Load, returning {ok, value} | {ok:false, error} instead of throwing. */
export async function tryLoadJSON(name) {
  try {
    return { ok: true, value: await loadJSON(name) };
  } catch (err) {
    return { ok: false, error: err.message || String(err) };
  }
}

/**
 * Wait for a CDN global (Leaflet, Plotly) to appear. Deferred CDN scripts
 * normally run before module code, but a blocked or slow CDN must degrade to a
 * readable message rather than an uncaught TypeError.
 */
export function waitForGlobal(name, timeoutMs = 12000) {
  return new Promise((resolve, reject) => {
    if (window[name]) { resolve(window[name]); return; }
    const started = Date.now();
    const tick = window.setInterval(() => {
      if (window[name]) {
        window.clearInterval(tick);
        resolve(window[name]);
      } else if (Date.now() - started > timeoutMs) {
        window.clearInterval(tick);
        reject(new Error(
          `The ${name} library did not load from its CDN. Charts and maps need network ` +
          `access to unpkg.com and cdn.plot.ly; everything else on this page still works.`
        ));
      }
    }, 60);
  });
}

/* --------------------------------------------------------------- formatting */

const NF = new Intl.NumberFormat('en-US');

export function fmtInt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '\u2014';
  return NF.format(Math.round(n));
}

export function fmtNum(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return '\u2014';
  return Number(n).toFixed(digits);
}

/** Integers print bare; fractional values keep one decimal. */
export function fmtDays(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '\u2014';
  return Number.isInteger(n) ? NF.format(n) : Number(n).toFixed(1);
}

export function fmtPct(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return '\u2014';
  return `${Number(n).toFixed(digits)}%`;
}

/* --------------------------------------------------------- DOM conveniences */

export const $ = (sel, root = document) => root.querySelector(sel);

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function setText(sel, value) {
  const node = $(sel);
  if (node) node.textContent = value === null || value === undefined ? '' : String(value);
}

export function clear(node) {
  if (node) while (node.firstChild) node.removeChild(node.firstChild);
}

/** Show a specific, actionable failure message inside one panel. */
export function showPanelError(slotSel, title, detail) {
  const slot = $(slotSel);
  if (!slot) return;
  clear(slot);
  slot.appendChild(el('strong', null, title));
  slot.appendChild(el('span', null, detail));
  slot.hidden = false;
}

export function hidePanelError(slotSel) {
  const slot = $(slotSel);
  if (slot) { clear(slot); slot.hidden = true; }
}

/** Placeholder shown inside a chart container when its data is unusable. */
export function showChartMessage(container, title, detail) {
  if (!container) return;
  clear(container);
  const box = el('div', 'media-empty');
  box.appendChild(el('h4', null, title));
  box.appendChild(el('p', null, detail));
  container.appendChild(box);
}

/* ======================================================= taxonomic classes */

/* Canonical class order and colours. A project-wide convention (mirrored by
   manifest.class_order / class_labels), not data, so it lives in code. */
export const CLASS_ORDER = ['Mammalia', 'Aves', 'Reptilia', 'Amphibia',
  'Insecta', 'Arachnida'];

export const CLASS_LABELS = {
  Mammalia: 'Mammals',
  Aves: 'Birds',
  Reptilia: 'Reptiles',
  Amphibia: 'Amphibians',
  Insecta: 'Insects',
  Arachnida: 'Arachnids'
};

export function classLabel(k) {
  return CLASS_LABELS[k] || k || 'Unclassified';
}

export function classRank(k) {
  const i = CLASS_ORDER.indexOf(k);
  return i === -1 ? CLASS_ORDER.length : i;
}

/** Classes present in a species list, canonically ordered, with counts. */
export function classesPresent(list) {
  const counts = new Map();
  for (const s of list || []) {
    const k = s.klass || s.class || null;
    if (!k) continue;
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => classRank(a[0]) - classRank(b[0]) || a[0].localeCompare(b[0]))
    .map(([klass, n]) => ({ klass, label: classLabel(klass), n }));
}

/** Populate a <select> with "All classes" plus the classes actually present. */
export function fillClassControl(sel, list, current) {
  if (!sel) return;
  const prev = current !== undefined ? current : sel.value;
  clear(sel);
  const all = el('option', null, 'All classes');
  all.value = 'all';
  sel.appendChild(all);
  for (const { klass, label, n } of classesPresent(list)) {
    const o = el('option', null, `${label} (${n})`);
    o.value = klass;
    sel.appendChild(o);
  }
  sel.value = Array.from(sel.options).some(o => o.value === prev) ? prev : 'all';
  return sel.value;
}

/* ========================================================= activity curves */

/* Half-hour histograms are smoothed with a wrapped Gaussian kernel. The
   kernel wraps because the day does: a detection at 23:50 is 20 minutes from
   one at 00:10, and a non-circular smoother would flatten both ends of the
   curve toward zero and invent a trough at midnight that is not in the data.

   The bandwidth is fixed rather than exposed as a control. ACT_SD_BINS = 1.4
   half-hour bins (42 min) is wide enough that a species with a few hundred
   detections gives a readable curve and narrow enough to keep a dawn peak
   separate from a dusk one. */
export const ACT_SD_BINS = 1.4;

function wrappedKernel(nBins, sdBins) {
  /* Row i holds the weights that bin i's smoothed value draws from every
     other bin. Precomputed once per bin count: it is the same matrix for
     every species and every curve on the page. */
  const rows = [];
  for (let i = 0; i < nBins; i += 1) {
    const w = new Array(nBins).fill(0);
    let sum = 0;
    for (let j = 0; j < nBins; j += 1) {
      let d = Math.abs(i - j);
      if (d > nBins / 2) d = nBins - d;          // wrap at midnight
      const v = Math.exp(-0.5 * (d / sdBins) ** 2);
      w[j] = v;
      sum += v;
    }
    for (let j = 0; j < nBins; j += 1) w[j] /= sum;
    rows.push(w);
  }
  return rows;
}

const KERNEL_CACHE = new Map();
function kernelFor(nBins) {
  const key = `${nBins}:${ACT_SD_BINS}`;
  if (!KERNEL_CACHE.has(key)) KERNEL_CACHE.set(key, wrappedKernel(nBins, ACT_SD_BINS));
  return KERNEL_CACHE.get(key);
}

/**
 * Smooth a half-hour detection histogram into an activity density.
 *
 * @param {number[]} counts  detections per bin
 * @param {number[]|null} effort  recording-hours per bin, or null when effort
 *        is uniform across the day (continuously running cameras)
 * @returns {{x:number[], y:number[], lo:number[], hi:number[], n:number, ok:boolean}}
 *
 * With `effort`, the smoothed quantity is detections per recording-hour,
 * which is the only honest activity measure for the ARUs: their schedule
 * records roughly 1,800 night-time files per hour of the clock but only about
 * 65 midday files all season, so a raw histogram would mostly describe the
 * recording schedule. With continuous cameras the denominator is constant and
 * cancels, so `effort` is omitted.
 *
 * Each curve is then scaled to integrate to 1 over the 24-hour cycle. That
 * makes the SHAPE comparable between plot types with very different totals,
 * which is the comparison the panel is for; the totals are reported
 * separately in the legend and hover so the scaling never hides them.
 *
 * `lo`/`hi` are a 95% interval from propagating Poisson counts through the
 * same kernel: var(sum w_j n_j) = sum w_j^2 n_j. It widens where a curve rests
 * on few detections, which is exactly where a single-species curve should not
 * be over-read.
 */
export function activityCurve(counts, effort) {
  const n = (counts || []).length;
  const total = (counts || []).reduce((a, b) => a + (Number(b) || 0), 0);
  if (!n || !total) return { x: [], y: [], lo: [], hi: [], n: 0, ok: false };
  const K = kernelFor(n);

  const num = new Array(n).fill(0);
  const varNum = new Array(n).fill(0);
  const den = new Array(n).fill(0);
  for (let i = 0; i < n; i += 1) {
    const w = K[i];
    for (let j = 0; j < n; j += 1) {
      const c = Number(counts[j]) || 0;
      num[i] += w[j] * c;
      varNum[i] += w[j] * w[j] * c;
      den[i] += w[j] * (effort ? (Number(effort[j]) || 0) : 1);
    }
  }

  const rate = new Array(n).fill(0);
  const se = new Array(n).fill(0);
  for (let i = 0; i < n; i += 1) {
    if (den[i] > 0) {
      rate[i] = num[i] / den[i];
      se[i] = Math.sqrt(varNum[i]) / den[i];
    }
  }

  // Normalize to unit area over 24 h. Bin width in hours = 24 / n.
  const dx = 24 / n;
  const area = rate.reduce((a, b) => a + b, 0) * dx;
  const k = area > 0 ? 1 / area : 0;

  const x = [];
  const y = [];
  const lo = [];
  const hi = [];
  for (let i = 0; i < n; i += 1) {
    x.push((i + 0.5) * dx);
    y.push(rate[i] * k);
    lo.push(Math.max(0, (rate[i] - 1.96 * se[i]) * k));
    hi.push((rate[i] + 1.96 * se[i]) * k);
  }
  // Close the circle so the drawn line meets itself at midnight instead of
  // stopping short of both axis ends.
  x.unshift(0); y.unshift(y[n - 1]); lo.unshift(lo[n - 1]); hi.unshift(hi[n - 1]);
  x.push(24); y.push(y[1]); lo.push(lo[1]); hi.push(hi[1]);
  return { x, y, lo, hi, n: total, ok: true };
}

/** Element-wise sum of several equal-length bin arrays. */
export function sumBins(arrays, nBins) {
  const out = new Array(nBins).fill(0);
  for (const a of arrays || []) {
    if (!a) continue;
    for (let i = 0; i < nBins; i += 1) out[i] += Number(a[i]) || 0;
  }
  return out;
}

/** "14:30" from an hour-of-day in decimal hours. */
export function fmtClock(h) {
  const t = ((Number(h) % 24) + 24) % 24;
  const hh = Math.floor(t);
  const mm = Math.round((t - hh) * 60);
  return `${String(mm === 60 ? hh + 1 : hh).padStart(2, '0')}:${String(mm === 60 ? 0 : mm).padStart(2, '0')}`;
}

/**
 * True only for a finite JSON number.
 *
 * `Number.isFinite(Number(x))` is the obvious-looking test and the wrong one
 * for fields this pipeline publishes as null: Number(null) is 0, which is
 * finite, so a deliberately absent value passes as a real zero. Several
 * summary fields ARE null by design -- a BirdNET species has no naive
 * occupancy, an unvalidated species has no cutoff -- and must be excluded,
 * not read as zero. JSON numbers arrive as numbers, so a typeof check is both
 * sufficient and honest about intent.
 */
export function isNum(v) {
  return typeof v === 'number' && Number.isFinite(v);
}
