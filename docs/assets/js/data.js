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
