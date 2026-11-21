"""Static HTML dashboard with calm editorial UI, interactive muted Carto/Leaflet map, revision/2009-7 diff tracking, per-filing digests, Turkish guide, and RSS 2.0 feed."""

from __future__ import annotations

import html
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .geo import province_centroid
from .gis import coord_cache_key, detect_spatial_omissions
from .revisions import build_revision_index, parse_pdf_url_meta

LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

BASE_CSS = """
:root {
  --bg: #f8f9fb;
  --surface: #ffffff;
  --surface-subtle: #f2f4f7;
  --border: #e4e7ec;
  --border-strong: #cfd5df;
  --text: #101828;
  --text-secondary: #344054;
  --muted: #667085;
  --accent: #175cd3;
  --accent-soft: #eff8ff;
  --red: #b42318;
  --red-soft: #fef3f2;
  --red-border: #fecdca;
  --amber: #b54708;
  --amber-soft: #fffaeb;
  --amber-border: #fedf89;
  --green: #067647;
  --green-soft: #ecfdf3;
  --green-border: #abefc6;
  --violet: #5925dc;
  --violet-soft: #f4f3ff;
  --violet-border: #d9d6fe;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  --radius: 10px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f131a;
    --surface: #161b24;
    --surface-subtle: #1d2430;
    --border: #273040;
    --border-strong: #39465c;
    --text: #eaedf2;
    --text-secondary: #c5cdd9;
    --muted: #8a95a6;
    --accent: #6cb0ff;
    --accent-soft: rgba(108, 176, 255, 0.14);
    --red: #ff857a;
    --red-soft: rgba(248, 81, 73, 0.13);
    --red-border: rgba(248, 81, 73, 0.36);
    --amber: #f0b849;
    --amber-soft: rgba(210, 153, 34, 0.13);
    --amber-border: rgba(210, 153, 34, 0.36);
    --green: #4cc38a;
    --green-soft: rgba(63, 185, 80, 0.13);
    --green-border: rgba(63, 185, 80, 0.36);
    --violet: #bda3ff;
    --violet-soft: rgba(158, 119, 237, 0.15);
    --violet-border: rgba(158, 119, 237, 0.38);
    --shadow: 0 1px 3px rgba(0, 0, 0, 0.28);
  }
}
:root[data-theme="dark"] {
  --bg: #0f131a;
  --surface: #161b24;
  --surface-subtle: #1d2430;
  --border: #273040;
  --border-strong: #39465c;
  --text: #eaedf2;
  --text-secondary: #c5cdd9;
  --muted: #8a95a6;
  --accent: #6cb0ff;
  --accent-soft: rgba(108, 176, 255, 0.14);
  --red: #ff857a;
  --red-soft: rgba(248, 81, 73, 0.13);
  --red-border: rgba(248, 81, 73, 0.36);
  --amber: #f0b849;
  --amber-soft: rgba(210, 153, 34, 0.13);
  --amber-border: rgba(210, 153, 34, 0.36);
  --green: #4cc38a;
  --green-soft: rgba(63, 185, 80, 0.13);
  --green-border: rgba(63, 185, 80, 0.36);
  --violet: #bda3ff;
  --violet-soft: rgba(158, 119, 237, 0.15);
  --violet-border: rgba(158, 119, 237, 0.38);
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.28);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Unified Sticky Topbar */
.topbar {
  position: sticky;
  top: 0;
  z-index: 900;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.topbar-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 10px 20px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  font-weight: 700;
  font-size: 0.96rem;
  letter-spacing: -0.01em;
}
.brand:hover { text-decoration: none; color: var(--accent); }
.brand-scope {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 2px 7px;
  border-radius: 999px;
}
.nav-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.nav-link {
  padding: 5px 10px;
  border-radius: 7px;
  font-size: 0.84rem;
  font-weight: 500;
  color: var(--text-secondary);
}
.nav-link:hover { background: var(--surface-subtle); text-decoration: none; color: var(--text); }
.nav-link.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.theme-btn {
  margin-left: 4px;
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 0.79rem;
  font-weight: 500;
}
.theme-btn:hover { border-color: var(--border-strong); color: var(--text); }

/* Layout */
.wrap { max-width: 1120px; margin: 0 auto; padding: 22px 20px 72px; }
.wrap.narrow { max-width: 900px; }
h1 { margin: 0 0 6px; font-size: 1.5rem; line-height: 1.25; letter-spacing: -0.02em; }
h2 { margin: 28px 0 10px; font-size: 1.15rem; line-height: 1.3; letter-spacing: -0.01em; }
h3 { margin: 16px 0 8px; font-size: 0.96rem; line-height: 1.35; }
.sub { color: var(--muted); font-size: 0.91rem; margin: 0; }

/* Compact Masthead */
.masthead {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px 20px;
  margin-bottom: 16px;
}
.masthead-left { max-width: 720px; }
.masthead-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 0.82rem;
  color: var(--muted);
}
.kpi-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 18px;
  padding: 10px 16px;
  margin-bottom: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.84rem;
  color: var(--muted);
  box-shadow: var(--shadow);
}
.kpi-item { display: inline-flex; align-items: baseline; gap: 5px; }
.kpi-item strong {
  color: var(--text);
  font-size: 0.96rem;
  font-variant-numeric: tabular-nums;
}
.kpi-item.accent strong { color: var(--accent); }
.kpi-item.rev strong { color: var(--violet); }
.kpi-sep { color: var(--border-strong); user-select: none; }

/* Map Card */
.map-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
}
.map-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 14px;
  padding: 9px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  font-size: 0.8rem;
  color: var(--muted);
}
.map-box.collapsed .map-bar { border-bottom: none; }
.map-box.collapsed #map { display: none; }
.map-legend-inline { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
#map { width: 100%; height: 320px; background: var(--surface-subtle); }
#digest-map { width: 100%; height: 300px; background: var(--surface-subtle); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }

/* Streamlined Controls */
.controls-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
}
.controls-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.controls-row + .controls-row {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.advanced-row { display: none; }
.advanced-row.open { display: flex; }
input[type="search"], select.filter-select {
  padding: 7px 11px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 0.87rem;
}
input[type="search"]:focus, select.filter-select:focus {
  outline: 2px solid var(--accent-soft);
  border-color: var(--accent);
}
input[type="search"] { flex: 1 1 240px; }
select.filter-select { min-width: 155px; }
button.pill {
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 500;
}
button.pill:hover { background: var(--surface-subtle); color: var(--text); }
button.pill.active { background: var(--accent); border-color: var(--accent); color: #ffffff; font-weight: 600; }
button.pill.rev-pill.active { background: var(--violet); border-color: var(--violet); }
.ctrl-right { margin-left: auto; display: flex; align-items: center; gap: 6px; }
button.ghost-btn {
  padding: 5px 9px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 0.79rem;
  font-weight: 500;
}
button.ghost-btn:hover { color: var(--text); border-color: var(--border-strong); background: var(--surface-subtle); }

/* Calm Two-Tier Cards */
.list-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 0.83rem;
  color: var(--muted);
}
.cards { display: flex; flex-direction: column; gap: 10px; }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 15px 18px;
  box-shadow: var(--shadow);
  transition: border-color 0.12s;
}
.card:hover { border-color: var(--border-strong); }
.card.urgent-edge { border-left: 3px solid var(--red); }
.card.ek1 { border-left: 3px solid var(--accent); }
.card.has-rev { border-left: 3px solid var(--violet); }
.card.urgent-edge.has-rev { border-left: 3px solid var(--red); }

/* Tier 1: Quiet Metadata Context Row (zero boxes!) */
.card-ctx {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 4px 12px;
  font-size: 0.79rem;
  color: var(--muted);
  margin-bottom: 5px;
}
.ctx-left { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.ctx-loc { color: var(--text-secondary); font-weight: 600; }
.ctx-ek1 { color: var(--accent); font-weight: 600; }
.ctx-geo { color: var(--green); font-weight: 500; }
.ctx-sep { color: var(--border-strong); }
.ctx-right { font-variant-numeric: tabular-nums; white-space: nowrap; }

.title { font-weight: 650; font-size: 1.01rem; line-height: 1.38; color: var(--text); margin: 0; }
.title a { color: var(--text); }
.title a:hover { color: var(--accent); text-decoration: none; }
.owner-line { font-size: 0.82rem; color: var(--muted); margin: 3px 0 0; }

/* Tier 2: Signal Pills (Status, Clock, Findings, Revision ONLY) */
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 0.74rem;
  font-weight: 500;
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}
.badge.urgent { background: var(--red-soft); border-color: var(--red-border); color: var(--red); font-weight: 600; }
.badge.warn { background: var(--amber-soft); border-color: var(--amber-border); color: var(--amber); font-weight: 600; }
.badge.ok { background: var(--green-soft); border-color: var(--green-border); color: var(--green); font-weight: 600; }
.badge.info { background: var(--accent-soft); border-color: transparent; color: var(--accent); font-weight: 600; }
.badge.rev { background: var(--violet-soft); border-color: var(--violet-border); color: var(--violet); font-weight: 600; }
.badge.muted { color: var(--muted); }

/* Calm 2-line Clamped Summary */
.summary-clamp {
  margin: 9px 0 0;
  font-size: 0.87rem;
  color: var(--text-secondary);
  line-height: 1.52;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.summary-clamp.muted { color: var(--muted); }

.rev-inline {
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: var(--violet-soft);
  border: 1px solid var(--violet-border);
  font-size: 0.8rem;
  color: var(--text-secondary);
}
.rev-inline strong { color: var(--violet); }

/* Quiet Action Row */
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  font-size: 0.82rem;
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid var(--border);
}
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 7px;
  background: var(--accent);
  color: #ffffff;
  font-weight: 600;
  font-size: 0.81rem;
}
.btn-primary:hover { text-decoration: none; filter: brightness(1.06); }
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--surface-subtle);
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 0.81rem;
  cursor: pointer;
}
.btn-secondary:hover { text-decoration: none; border-color: var(--border-strong); color: var(--text); }
.quiet-link { color: var(--muted); font-weight: 500; }
.quiet-link:hover { color: var(--accent); }

/* Pagination Bar */
.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 18px;
}
.pager button {
  padding: 8px 18px;
  border-radius: 8px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}
.pager button:hover { border-color: var(--accent); color: var(--accent); }
.pager .pager-all {
  border-color: transparent;
  background: transparent;
  color: var(--muted);
  font-weight: 500;
}

/* Digest & Guide Tables, Accordions, Callouts */
table.kv {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 0.88rem;
  background: var(--surface);
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--border);
}
table.kv th, table.kv td {
  border-bottom: 1px solid var(--border);
  padding: 9px 13px;
  text-align: left;
  vertical-align: top;
}
table.kv tr:last-child th, table.kv tr:last-child td { border-bottom: none; }
table.kv th { width: 240px; background: var(--surface-subtle); color: var(--text); font-weight: 600; }
table.data-tbl {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 0.84rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
table.data-tbl th, table.data-tbl td {
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
table.data-tbl th { background: var(--surface-subtle); font-weight: 600; color: var(--muted); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.03em; }
table.data-tbl tr:last-child td { border-bottom: none; }
code {
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  padding: 1px 5px;
  border-radius: 5px;
  font-size: 0.84em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
blockquote {
  margin: 10px 0;
  padding: 12px 16px;
  border-left: 3px solid var(--accent);
  background: var(--surface-subtle);
  border-radius: 0 8px 8px 0;
  font-size: 0.89rem;
  color: var(--text-secondary);
}
.callout {
  padding: 14px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface);
  margin: 14px 0;
}
.callout.rev { background: var(--violet-soft); border-color: var(--violet-border); }
details.accordion {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin: 10px 0;
  overflow: hidden;
}
details.accordion summary {
  padding: 12px 16px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.92rem;
  color: var(--text);
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface);
}
details.accordion summary::-webkit-details-marker { display: none; }
details.accordion summary::after {
  content: "+";
  font-size: 1.1rem;
  color: var(--muted);
  font-weight: 400;
}
details.accordion[open] summary::after { content: "−"; }
details.accordion[open] summary { border-bottom: 1px solid var(--border); background: var(--surface-subtle); }
.accordion-body { padding: 14px 16px; }
.timeline {
  list-style: none;
  margin: 10px 0 0;
  padding: 0 0 0 18px;
  border-left: 2px solid var(--border-strong);
}
.timeline li { position: relative; margin: 0 0 9px; padding-left: 8px; font-size: 0.86rem; }
.timeline li::before {
  content: "";
  position: absolute;
  left: -24px;
  top: 6px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--surface);
}
.hit { margin: 8px 0; font-size: 0.87rem; line-height: 1.55; }
.pno { font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }
.notice {
  margin-top: 32px;
  padding: 13px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-subtle);
  font-size: 0.82rem;
  color: var(--muted);
}
.toc-pills { display: flex; flex-wrap: wrap; gap: 7px; margin: 14px 0 20px; }
.toc-pills a {
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 0.81rem;
  font-weight: 500;
}
.toc-pills a:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
.step-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
  margin: 14px 0 22px;
}
.step-num {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 5px;
}
pre.template-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
  overflow-x: auto;
  font-size: 0.84rem;
  line-height: 1.55;
  white-space: pre-wrap;
}
.section-head-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.leaflet-popup-content { color: #101828; font-size: 0.84rem; line-height: 1.45; }
@media (max-width: 700px) {
  table.kv th { width: 140px; }
  #map { height: 270px; }
  .topbar-inner { padding: 9px 14px; }
  .wrap { padding: 16px 14px 54px; }
}
@media print {
  .topbar, .no-print, #digest-map, .map-box { display: none !important; }
  body { background: #ffffff; color: #000000; font-size: 11pt; }
  .card, table.kv, table.data-tbl, details.accordion { box-shadow: none; break-inside: avoid; }
  details.accordion { border: 1px solid #ccc; }
  a { color: #000000; text-decoration: underline; }
}
"""

THEME_JS = """
(() => {
  const root = document.documentElement;
  const saved = localStorage.getItem('eced_theme');
  if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);
  function isDarkNow() {
    const cur = root.getAttribute('data-theme');
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    return cur ? cur === 'dark' : prefersDark;
  }
  window.__ecedIsDark = isDarkNow;
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  function syncLabel() {
    btn.textContent = isDarkNow() ? 'Açık Tema' : 'Koyu Tema';
  }
  syncLabel();
  btn.addEventListener('click', () => {
    const next = isDarkNow() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('eced_theme', next);
    syncLabel();
    window.dispatchEvent(new CustomEvent('eced-theme-change', { detail: { dark: next === 'dark' } }));
  });
})();
"""

CARTO_TILE_HELPER_JS = """
function createCartoTileLayer(isDark) {
  const style = isDark ? 'dark_all' : 'light_all';
  return L.tileLayer(`https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`, {
    maxZoom: 19,
    subdomains: 'abcd',
    attribution: '&copy; OpenStreetMap &copy; CARTO'
  });
}
"""

TR_SIGNAL_LABELS = {
    "coordinates_and_footprint": "Koordinatlar, Parsel ve Alan Büyüklüğü",
    "water_and_discharge": "Su Kullanımı, Hidrojeoloji ve Deşarj",
    "protected_land_and_olive": "Korunan Alanlar, Orman ve Zeytinlikler",
    "ecology_and_baseline": "Flora, Fauna ve Saha Metodolojisi",
    "pollutants_and_hazards": "Emisyonlar, Jeokimya ve Atıklar",
    "cost_and_capacity": "Proje Bedeli, Güç ve Kapasite",
    "splitting_and_thresholds": "Proje Parçalama, Kapasite Artışı ve Eşik Değerler",
    "agency_opinions": "Kurum Görüşleri (DSİ, İl Tarım, OGM, MAPEG, SİT)",
}

TR_DANISTAY_CATEGORIES = {
    "zeytinlik_3573": "3573 Zeytincilik (3 km)",
    "proje_parcalama": "Proje Parçalama / Eşik Değer",
    "kumulatif_etki": "Kümülatif Etki",
    "flora_fauna_mevsimsel": "Flora / Fauna & Mevsimsellik",
    "su_hidrojeoloji": "Su / Hidrojeoloji",
    "tarim_orman_korunan_alan": "5403 / Orman / Korunan Alan",
    "izleme_olcum_celiskisi": "Ölçüm / İç Tutarlılık",
}

TR_BASELINE_STATUS = {
    "field_survey_documented": "Belgelenmiş saha çalışması mevcut",
    "literature_only": "Yalnızca literatür taramasına dayalı",
    "mixed_or_unclear": "Karışık veya yöntemi belirsiz",
    "not_found": "İncelenen sayfalarda tespit edilemedi",
    "completed_pre_project": "Başvuru öncesinde tamamlanmış",
    "promised_post_approval_only": "Yalnızca onay sonrasına ertelenmiş",
    "unclear": "Belirsiz",
    "quantitatively_assessed": "Nicel değerlendirme yapılmış",
    "superficial_or_boilerplate": "Yüzeysel veya şablon düzeyinde",
    "omitted_or_not_found": "Eksik veya tespit edilemedi",
}

TR_SEVERITY = {
    "high": "YÜKSEK",
    "medium": "ORTA",
    "low": "DÜŞÜK",
}


def _esc(val: Any) -> str:
    return html.escape(str(val or ""), quote=True)


def _topbar_html(active: str, prefix: str = "") -> str:
    return f"""<nav class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="{prefix}index.html">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3v9l6 3"/><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>
      <span>Türkiye e-ÇED İzleme</span>
      <span class="brand-scope">81 İl</span>
    </a>
    <div class="nav-links">
      <a class="nav-link {'active' if active == 'index' else ''}" href="{prefix}index.html">Duyurular</a>
      <a class="nav-link {'active' if active == 'guide' else ''}" href="{prefix}rehber.html">Kullanım Rehberi</a>
      <a class="nav-link" href="{prefix}feed.xml">RSS</a>
      <a class="nav-link" href="https://eced-duyuru.csb.gov.tr/eced-prod/duyurular.xhtml" target="_blank" rel="noopener">Resmi e-ÇED ↗</a>
      <button id="theme-toggle" class="theme-btn" type="button">Tema</button>
    </div>
  </div>
</nav>"""


def _best_active_clock(filing: dict[str, Any]) -> dict[str, Any] | None:
    clocks = filing.get("statutory_clocks") or []
    dated = [c for c in clocks if c.get("days_remaining") is not None]
    if dated:
        dated.sort(key=lambda c: c["days_remaining"])
        return dated[0]
    return clocks[0] if clocks else None


def _stage_filter_bucket(filing: dict[str, Any]) -> str:
    dt = (filing.get("decision_type") or "").lower()
    if "iptal" in dt or "iade" in dt:
        return "iptal_iade"
    clocks = filing.get("statutory_clocks") or []
    codes = {c.get("code") for c in clocks}
    if "iyuk_20a" in codes:
        return "iyuk_20a"
    if "aski_10d" in codes:
        return "aski_10d"
    if "hkt" in codes or "idk" in codes:
        return "hkt_idk"
    if "process_open" in codes:
        return "process_open"
    return "other"


def _clock_badge_html(clock: dict[str, Any] | None) -> str:
    if not clock:
        return ""
    dr = clock.get("days_remaining")
    code = clock.get("code", "")
    if code == "process_open":
        return '<span class="badge info">Karar Öncesi (m. 8/16)</span>'
    label = {
        "iyuk_20a": "İYUK 20/A",
        "aski_10d": "Madde 14 Askı",
        "hkt": "HKT",
        "idk": "İDK",
    }.get(code, "Yasal Süre")
    if dr is None:
        return f'<span class="badge warn">{_esc(label)} · Tarih duyuruda</span>'
    if dr < 0:
        return f'<span class="badge muted">{_esc(label)} · Süresi doldu</span>'
    if dr <= 7:
        return f'<span class="badge urgent">{_esc(label)} · {dr} gün kaldı ({clock["deadline"]})</span>'
    if dr <= 15:
        return f'<span class="badge warn">{_esc(label)} · {dr} gün kaldı ({clock["deadline"]})</span>'
    return f'<span class="badge ok">{_esc(label)} · {dr} gün kaldı ({clock["deadline"]})</span>'


def _revision_badges_html(rev_entry: dict[str, Any] | None) -> str:
    if not rev_entry:
        return ""
    flags = rev_entry.get("flags") or []
    out: list[str] = []
    if "pdf_changed" in flags:
        ver = rev_entry.get("revision_count", 2)
        out.append(f'<span class="badge urgent">PDF Revizyonu (v{ver})</span>')
    if "circular_2009_7" in flags:
        out.append('<span class="badge urgent">2009/7 Revizyon</span>')
    if "portal_text_changed" in flags:
        out.append('<span class="badge rev">Portal Kaydı Değişti</span>')
    if "multi_stage" in flags:
        n_st = len(rev_entry.get("timeline") or [])
        out.append(f'<span class="badge rev">{n_st} Aşama</span>')
    if "related_filing" in flags:
        n_rel = len(rev_entry.get("related_filings") or [])
        out.append(f'<span class="badge rev">{n_rel} İlişkili</span>')
    if "legacy_resurfaced" in flags:
        gap = rev_entry.get("legacy_gap_years") or 1
        out.append(f'<span class="badge warn">Eski Dosya ({gap}+ yıl)</span>')
    return " ".join(out)


def _marker_color(filing: dict[str, Any], has_digest: bool) -> str:
    clock = _best_active_clock(filing)
    if clock:
        code = clock.get("code", "")
        dr = clock.get("days_remaining")
        if code == "process_open":
            return "#175cd3"
        if dr is not None:
            if 0 <= dr <= 7:
                return "#d92d20"
            if 8 <= dr <= 15:
                return "#d97706"
            if dr > 15:
                return "#16a34a"
            return "#667085"
        return "#d97706"
    if filing.get("project_type") == "Ek-1" or has_digest:
        return "#175cd3"
    return "#667085"


def _render_revision_section_html(
    filing_id: str,
    pdf_info: dict[str, Any],
    doc_meta: dict[str, Any],
    rev_entry: dict[str, Any] | None,
) -> str:
    rev_entry = rev_entry or {}
    rev_hist = rev_entry.get("revision_history") or []
    latest_diff = rev_entry.get("latest_pdf_diff")
    timeline = rev_entry.get("timeline") or []
    related = rev_entry.get("related_filings") or []
    portal_changes = rev_entry.get("portal_change_log") or []

    url_meta = parse_pdf_url_meta(
        pdf_info.get("source_url")
        or (doc_meta["pdf_urls"][0]["url"] if doc_meta.get("pdf_urls") else "")
    )

    has_notable = bool(latest_diff or len(timeline) >= 2 or related or portal_changes)

    # Compact single-line integrity strip when cleanly v1 with no multi-stage/related alerts
    if not has_notable:
        return (
            f'<div class="card" style="padding:11px 15px;margin:14px 0;font-size:0.84rem;color:var(--text-secondary);">'
            f'<span class="badge ok">v1 Arşivlendi</span> &nbsp;'
            f'SHA-256: <code>{_esc((pdf_info.get("sha256") or "")[:16])}…</code> · '
            f'Yükleme: <code>{_esc(url_meta.get("upload_date") or doc_meta.get("submitted_at") or "—")}</code> · '
            f'<span style="color:var(--muted);">Rapor değiştirilirse sürümler arası fark (v1→v2) otomatik kaydedilir.</span>'
            f'</div>'
        )

    parts: list[str] = [
        '<h2>Belge Bütünlüğü, Revizyon ve Süreç Geçmişi</h2>',
        '<p class="sub">Her PDF dosyasının SHA-256 özeti, yükleme tarihi ve teknik göstergeleri arşivlenir; 2009/7 Genelgesi kapsamındaki değişiklikler sürümler arası fark olarak kaydedilir.</p>',
    ]

    if latest_diff:
        check_rows = ""
        for ch in latest_diff.get("audit_check_changes") or []:
            badge_cls = "urgent" if ch["direction"] == "removed" else "ok"
            arrow = f"{'VAR' if ch['from'] else 'YOK'} → {'VAR' if ch['to'] else 'YOK'}"
            check_rows += (
                f'<tr><th>{_esc(ch["label"])}</th>'
                f'<td><span class="badge {badge_cls}">{_esc(arrow)}</span></td></tr>'
            )
        sig_deltas = latest_diff.get("signal_page_deltas") or {}
        if sig_deltas:
            delta_str = ", ".join(
                f"{TR_SIGNAL_LABELS.get(k, k)}: {'+' if v > 0 else ''}{v} s."
                for k, v in sig_deltas.items()
            )
            check_rows += f"<tr><th>Bölüm Sayfa Değişimleri</th><td>{_esc(delta_str)}</td></tr>"
        if latest_diff.get("coordinate_shift_m") is not None:
            check_rows += (
                f'<tr><th>Koordinat Kayması</th>'
                f'<td><span class="badge urgent">{latest_diff["coordinate_shift_m"]:.0f} metre</span></td></tr>'
            )
        parts.append(
            f'<div class="callout rev">'
            f'<strong>PDF Revizyonu Tespit Edildi (v{latest_diff["from_version"]} → v{latest_diff["to_version"]}):</strong> '
            f'{_esc(latest_diff["summary_tr"])}'
            f'{f"<table class=kv style=margin-top:10px;>{check_rows}</table>" if check_rows else ""}'
            f'</div>'
        )

    if rev_hist:
        hist_rows = []
        for snap in rev_hist:
            hist_rows.append(
                f"<tr>"
                f"<td><code>v{snap.get('version', 1)}</code></td>"
                f"<td><code>{_esc(snap.get('observed_at') or '—')}</code></td>"
                f"<td>{_esc(snap.get('decision_type') or '—')}</td>"
                f"<td><code>{_esc(snap.get('pdf_upload_date') or snap.get('submitted_at') or '—')}</code></td>"
                f"<td>{_esc(snap.get('page_count') or '—')}</td>"
                f"<td><code>{_esc((snap.get('sha256') or '')[:16])}…</code></td>"
                f"</tr>"
            )
        parts.append(
            '<table class="data-tbl">'
            '<thead><tr><th>Sürüm</th><th>Arşiv Tarihi</th><th>Aşama</th><th>Yükleme Tarihi</th><th>Sayfa</th><th>SHA-256</th></tr></thead>'
            f'<tbody>{"".join(hist_rows)}</tbody></table>'
        )

    if len(timeline) >= 2:
        tl_items = "".join(
            f'<li><strong>{_esc(t["announcement_date_tr"])}</strong> — '
            f'<span class="badge">{_esc(t["decision_type"])}</span> '
            f'<span class="sub">(yükleme: <code>{_esc(t.get("pdf_upload_date") or t.get("submitted_at") or "—")}</code>)</span></li>'
            for t in timeline
        )
        parts.append(f'<h3>Dosya #{_esc(filing_id)} Süreç Zaman Çizelgesi</h3><ul class="timeline">{tl_items}</ul>')

    if portal_changes:
        pc_rows = "".join(
            f'<tr><td><code>{_esc(c.get("detected_at"))}</code></td>'
            f'<td><code>{_esc(", ".join(c.get("changed_fields") or []))}</code></td>'
            f'<td>{_esc(c.get("prev_submitted_at") or "—")} → {_esc(c.get("new_submitted_at") or "—")}</td></tr>'
            for c in portal_changes
        )
        parts.append(
            '<h3>Portal Değişiklik Kaydı</h3>'
            '<table class="data-tbl"><thead><tr><th>Tespit</th><th>Değişen Alanlar</th><th>Yükleme Zamanı</th></tr></thead>'
            f'<tbody>{pc_rows}</tbody></table>'
        )

    if related:
        rel_rows = []
        for r in related:
            rid = r["filing_id"]
            link_cell = (
                f'<a href="{_esc(rid)}.html"><strong>#{_esc(rid)} (Ön Özet)</strong></a>'
                if r.get("has_digest")
                else f'<code>#{_esc(rid)}</code>'
            )
            rel_rows.append(
                f"<tr><td>{link_cell}</td>"
                f"<td>{_esc(r.get('announcement_date_tr') or '—')}</td>"
                f"<td><span class='badge'>{_esc(r.get('decision_type') or '—')}</span></td>"
                f"<td>{_esc(r.get('project_name') or '')}<br/><span class='sub'>{_esc(r.get('detail') or '')}</span></td></tr>"
            )
        parts.append(
            '<h3>Aynı İlçede İlişkili / Tekrar veya Parçalı Başvurular</h3>'
            '<table class="data-tbl"><thead><tr><th>Dosya</th><th>Tarih</th><th>Aşama</th><th>Proje ve Eşleşme Nedeni</th></tr></thead>'
            f'<tbody>{"".join(rel_rows)}</tbody></table>'
        )

    return "\n".join(parts)


def _render_gis_section_html(
    gis_entry: dict[str, Any] | None,
    gis_alerts: list[dict[str, Any]],
) -> str:
    if not gis_entry:
        return ""
    cats = gis_entry.get("categories") or {}
    sev_cls = {"high": "urgent", "medium": "warn", "info": "info"}
    alerts_html = ""
    if gis_alerts:
        alert_items = "".join(
            f'<div class="hit"><span class="badge {sev_cls.get(a["severity"], "muted")}">'
            f'{_esc(TR_SEVERITY.get(a["severity"], "BİLGİ"))}</span> '
            f'<strong>{_esc(a["title"])}</strong> — {_esc(a["detail"])}</div>'
            for a in gis_alerts
        )
        alerts_html = f'<div class="callout rev" style="margin-top:10px;">{alert_items}</div>'

    def fmt_cat(key: str) -> str:
        c = cats.get(key) or {}
        cnt = c.get("count", 0)
        if not cnt:
            return '<span style="color:var(--muted)">3 km içinde kayıt tespit edilmedi</span>'
        d = c.get("min_distance_m")
        samples = []
        for s in (c.get("nearest") or [])[:3]:
            lbl = s.get("name") or s.get("kind") or ""
            samples.append(f"{lbl} (~{s['distance_m']} m)")
        return f"<strong>{cnt} kayıt</strong> · en yakın <code>~{d} m</code>" + (
            f" — {_esc(', '.join(samples))}" if samples else ""
        )

    return (
        '<h3>Bağımsız Mekânsal Doğrulama (3 km · OpenStreetMap)</h3>'
        f'{alerts_html}'
        '<table class="kv">'
        f'<tr><th>Zeytinlik / Meyve Bahçesi (3573 m.20)</th><td>{fmt_cat("olive_or_orchard")}</td></tr>'
        f'<tr><th>Akarsu / Sulak Alan / Su Kaynağı</th><td>{fmt_cat("water_bodies")}</td></tr>'
        f'<tr><th>Korunan Alan / Orman</th><td>{fmt_cat("protected_or_forest")}</td></tr>'
        f'<tr><th>En Yakın Yerleşimler (Yöre Sakinleri)</th><td>{fmt_cat("settlements")}</td></tr>'
        f'<tr><th>Okul / Sağlık Tesisleri</th><td>{fmt_cat("sensitive_facilities")}</td></tr>'
        '</table>'
        '<p class="sub"><em>Not:</em> OpenStreetMap gönüllü harita verisidir; haritada eksik veya eski kayıtlar olabilir. Kesin mesafe ve zeytinlik/korunan alan tespiti için uydu görüntüsü, İlçe Tarım kayıtları ve mahallinde keşif esas alınmalıdır.</p>'
    )


def render_digest_html(
    saved: dict[str, Any],
    raw_md_filename: str,
    rev_entry: dict[str, Any] | None = None,
    gis_entry: dict[str, Any] | None = None,
) -> str:
    filing = saved["filing"]
    docs = filing.get("documents") or [{}]
    doc_meta = docs[0]
    pdf_info = saved["pdf_info"]
    analysis = saved["analysis"]
    filing_id = doc_meta.get("filing_id") or "bilinmiyor"
    pdf_url = doc_meta["pdf_urls"][0]["url"] if doc_meta.get("pdf_urls") else ""

    geo = analysis.get("geo") or {}
    if geo.get("lat") and geo.get("lon"):
        g_lat, g_lon = geo["lat"], geo["lon"]
        g_prec = geo.get("precision", "province_centroid")
        g_pts = geo.get("points") or []
    else:
        g_lat, g_lon = province_centroid(filing.get("province", ""))
        g_prec = "province_centroid"
        g_pts = []

    geo_caption = (
        f"PDF metninden çıkarılan kesin proje koordinatları ({geo.get('point_count', len(g_pts))} nokta, "
        f"datum: {geo.get('datum') or 'WGS84'}, sayfa: {', '.join(f's.{p}' for p in (geo.get('pages') or [])[:6])})."
        if g_prec == "exact_pdf"
        else "PDF dosyasında metin olarak okunabilir koordinat tablosu tespit edilemediği için il merkezi yaklaşık konum olarak gösterilmektedir."
    )
    zoom_lvl = 12 if g_prec == "exact_pdf" else 8
    osm_url = f"https://www.openstreetmap.org/?mlat={g_lat}&mlon={g_lon}#map={zoom_lvl}/{g_lat}/{g_lon}"
    gmaps_url = f"https://www.google.com/maps/search/?api=1&query={g_lat},{g_lon}"

    checks = analysis["audit_checks"]
    check_rows = [
        ("Saha veya arazi çalışması ifadesi", checks.get("mentions_field_survey", False), "required"),
        ("Literatür taraması ifadesi", checks.get("mentions_literature_only_cue", False), "info"),
        ("Mevsimsel örnekleme ifadesi", checks.get("mentions_seasonal_sampling", False), "required"),
        ("Kümülatif etki değerlendirmesi ifadesi", checks.get("mentions_cumulative_impact", False), "required"),
        ("3573 sayılı Zeytincilik Kanunu veya zeytinlik ifadesi", checks.get("mentions_olive_law_3573", False), "required"),
        ("Yeraltı suyu, akifer veya hidrojeoloji ifadesi", checks.get("mentions_groundwater_or_aquifer", False), "required"),
        ("Endemik tür, IUCN veya Bern Sözleşmesi ifadesi", checks.get("mentions_iucn_or_endemic", False), "required"),
        ("Kapasite artışı, ilave ünite veya eşik değer ifadesi", checks.get("mentions_capacity_or_splitting", False), "watch"),
        ("2009/7 Genelgesi veya yargı kararı sonrası revizyon ifadesi", checks.get("mentions_circular_2009_7_or_revision", False), "watch"),
        ("Kurum görüşleri (DSİ, İl Tarım, OGM, MAPEG)", checks.get("mentions_agency_opinions", False), "required"),
        ("Deprem, fay hattı veya jeoteknik stabilite ifadesi", checks.get("mentions_seismic_or_geotech", False), "info"),
    ]
    checks_html_parts: list[str] = []
    for lbl, ok, mode in check_rows:
        if mode == "watch":
            badge = (
                '<span class="badge warn">Metinde geçmektedir — parçalama / 2009/7 kontrolü</span>'
                if ok
                else '<span class="badge muted">Tespit edilmedi</span>'
            )
        elif mode == "info":
            badge = (
                '<span class="badge warn">Literatür ifadesi mevcut</span>'
                if ok
                else '<span class="badge muted">Tespit edilmedi</span>'
            )
        else:
            badge = (
                '<span class="badge ok">Metinde yer almaktadır</span>'
                if ok
                else '<span class="badge urgent">Tespit edilemedi — PDF kontrolü gerekir</span>'
            )
        checks_html_parts.append(f"<tr><th>{_esc(lbl)}</th><td>{badge}</td></tr>")
    checks_html = "\n".join(checks_html_parts)

    sig_blocks: list[str] = []
    for k, sig in analysis["signals"].items():
        tr_label = TR_SIGNAL_LABELS.get(k, sig["label"])
        pages_preview = ", ".join(f"s.{p}" for p in sig["pages"][:14])
        if sig["page_count"] > 14:
            pages_preview += f" (+{sig['page_count'] - 14} sayfa)"
        hits_html = "\n".join(
            f'<div class="hit"><span class="pno">[s. {h["page"]}]</span> <code>{_esc(h["match"])}</code> — {_esc(h["snippet"])}</div>'
            for h in sig["samples"][:6]
        ) or '<div class="hit" style="color:var(--muted)">Eşleşme bulunamamıştır.</div>'
        sig_blocks.append(
            f'<div style="margin-bottom:14px;"><h3 style="margin-top:4px;">{_esc(tr_label)} '
            f'<span style="color:var(--muted);font-weight:400;font-size:0.83rem">({sig["page_count"]} sayfa: {_esc(pages_preview or "yok")})</span></h3>'
            f"{hits_html}</div>"
        )

    headings_html = "\n".join(
        f'<li><span class="pno">[s. {pno}]</span> {_esc(h)}</li>'
        for pno, h in analysis.get("headings", [])[:20]
    )

    clocks_html = " ".join(_clock_badge_html(c) for c in filing.get("statutory_clocks") or [])
    rev_badges_html = _revision_badges_html(rev_entry)
    rev_section_html = _render_revision_section_html(filing_id, pdf_info, doc_meta, rev_entry)
    gis_alerts = detect_spatial_omissions(gis_entry, checks)
    gis_section_html = _render_gis_section_html(gis_entry, gis_alerts)
    gis_high_badge = (
        '<span class="badge urgent">3 km Mekânsal Uyarı</span>'
        if any(a.get("severity") == "high" for a in gis_alerts)
        else ""
    )

    llm_block = ""
    llm = saved.get("llm_synthesis")
    if llm and llm.get("result"):
        res = llm["result"]
        ba = res["baseline_assessment"]
        pages_used = ", ".join(f"s.{p}" for p in llm.get("pages_sent") or [])
        facts_html = "\n".join(
            f'<tr><th>{_esc(kf["label"])}</th><td>{_esc(kf["value"])} <span class="pno">[s. {kf["page"]}]</span></td></tr>'
            for kf in res.get("key_facts") or []
        )
        sev_cls = {"high": "urgent", "medium": "warn", "low": "muted"}
        flags_html = "\n".join(
            f'<div class="hit"><span class="badge {sev_cls.get(rf["severity"], "muted")}">{_esc(TR_SEVERITY.get(rf["severity"], rf["severity"].upper()))}</span> '
            + (
                f'<span class="badge">{_esc(TR_DANISTAY_CATEGORIES.get(rf["category"], rf["category"]))}</span> '
                if rf.get("category")
                else ""
            )
            + f'<strong>{_esc(rf["title"])}</strong> '
            f'<span class="pno">[{", ".join(f"s. {p}" for p in rf.get("pages") or [])}]</span> — {_esc(rf["detail"])}</div>'
            for rf in res.get("red_flags") or []
        )
        bilirkisi = res.get("recommended_bilirkisi_disciplines") or []
        bilirkisi_html = ""
        if bilirkisi:
            pills_b = " ".join(f'<span class="badge info">{_esc(d)}</span>' for d in bilirkisi)
            bilirkisi_html = (
                f'<h3>Keşif ve Bilirkişi Heyeti İçin Önerilen Uzmanlık Alanları</h3>'
                f'<section class="card"><div class="badges" style="margin-top:0;">{pills_b}</div>'
                f'<p class="sub" style="margin-top:8px;">Bilirkişi heyetinin tek sayıda uzmandan oluşması, proje niteliğine uygun tüm disiplinleri içermesi ve plan kararlarıyla ilişkili davalarda Şehir ve Bölge Plancısına yer verilmesi gerekmektedir.</p></section>'
            )
        agency_sum = (res.get("agency_opinions_summary") or "").strip()
        agency_html = (
            f'<h3>Kurum Görüşleri (DSİ / İl Tarım / OGM / MAPEG)</h3>'
            f'<section class="card"><p style="margin:0;font-size:0.89rem;">{_esc(agency_sum)}</p></section>'
            if agency_sum
            else ""
        )
        comp_permits = res.get("companion_permits_to_watch") or []
        comp_html = ""
        if comp_permits:
            pills_p = " ".join(f'<span class="badge rev">{_esc(p)}</span>' for p in comp_permits)
            comp_html = (
                f'<h3>2009/7 Döngüsünü Kırmak İçin Paralel İzlenecek İzinler</h3>'
                f'<section class="card"><div class="badges" style="margin-top:0;">{pills_p}</div>'
                f'<p class="sub" style="margin-top:8px;">Emsal çevre davaları (Amasra HEMA, Eskişehir Alpu, Ordu Fatsa), yalnızca ÇED iptalinin 2009/7 Genelgesi ile aşılabildiğini; eşlikçi lisans, ruhsat veya plan işlemlerinin de izlenmesinin kalıcı koruma sağladığını göstermektedir.</p></section>'
            )
        q_list = res.get("hkt_and_petition_questions") or []
        qs_html = "\n".join(
            f'<li>{_esc(q["question_tr"])} <span class="pno">[{", ".join(f"s. {p}" for p in q.get("pages") or [])}]</span></li>'
            for q in q_list
        )
        qs_plain = "\n".join(
            f"{i}. {q['question_tr']} [{', '.join(f's. {p}' for p in q.get('pages') or [])}]"
            for i, q in enumerate(q_list, start=1)
        )
        en_details = ""
        if res.get("executive_summary_en"):
            en_details = (
                f'<details style="margin-top:10px;font-size:0.85rem;color:var(--muted);">'
                f'<summary style="cursor:pointer;">English summary</summary>'
                f'<p style="margin:6px 0 0;">{_esc(res["executive_summary_en"])}</p></details>'
            )
        llm_block = f"""
  <h2>Bilimsel Ön Değerlendirme <span class="badge">{_esc(llm.get('model'))}</span></h2>
  <p class="sub">Resmi PDF'ten seçilen {len(llm.get('pages_sent') or [])} sayfa ({_esc(pages_used)}) üzerinden üretilmiştir; her bulguyu <code>[s. N]</code> kaynağından doğrulayınız.</p>
  <section class="card ek1" style="margin-top:10px;">
    <p style="margin-top:0;"><strong>Özet:</strong> {_esc(res['executive_summary_tr'])}</p>
    {en_details}
    <div class="badges" style="margin-top:10px;">
      <span class="badge">Saha: {_esc(TR_BASELINE_STATUS.get(ba['field_survey_status'], ba['field_survey_status']))}</span>
      <span class="badge">Mevsimsellik: {_esc(TR_BASELINE_STATUS.get(ba['seasonal_sampling_status'], ba['seasonal_sampling_status']))}</span>
      <span class="badge">Kümülatif: {_esc(TR_BASELINE_STATUS.get(ba['cumulative_impact_status'], ba['cumulative_impact_status']))}</span>
    </div>
    <p class="sub" style="margin-top:10px;color:var(--text-secondary);"><strong>Zeytinlik ve Korunan Alanlar:</strong> {_esc(ba['olive_and_protected_status'])}<br/>{_esc(ba['explanation'])}</p>
  </section>
  {f'<h3>Danıştay Ölçütlerine Göre Bilimsel ve Hukuki Bulgular</h3><section class="card">{flags_html}</section>' if flags_html else ''}
  {f'<h3>Öne Çıkan Sayısal Bulgular</h3><table class="kv">{facts_html}</table>' if facts_html else ''}
  {agency_html}
  {comp_html}
  {bilirkisi_html}
  {f'<div class="section-head-row" style="margin-top:16px;"><h3 style="margin:0;">HKT Tutanakları ve Bilirkişi İçin Taslak Teknik Sorular</h3><button type="button" class="btn-secondary no-print" id="copy-qs-btn">Soruları Kopyala</button></div><section class="card" style="margin-top:8px;"><ul style="margin:0;padding-left:20px;">{qs_html}</ul><textarea id="qs-plain" style="display:none;">{_esc(qs_plain)}</textarea></section>' if qs_html else ''}
  <p class="sub" style="margin-top:10px;"><em>İnceleme sınırları:</em> {_esc(res.get('data_limitations', ''))}</p>
"""

    gis_markers: list[dict[str, Any]] = []
    if gis_entry:
        cats = gis_entry.get("categories") or {}
        cat_colors = {
            "olive_or_orchard": "#65a30d",
            "water_bodies": "#0284c7",
            "protected_or_forest": "#047857",
            "settlements": "#7c3aed",
            "sensitive_facilities": "#ea580c",
        }
        for ck, col in cat_colors.items():
            for item in ((cats.get(ck) or {}).get("nearest") or [])[:2]:
                gis_markers.append(
                    {
                        "lat": item["lat"],
                        "lon": item["lon"],
                        "color": col,
                        "label": f"{item.get('kind', '')}: {item.get('name') or 'Adsız'} (~{item['distance_m']} m)",
                    }
                )

    map_payload = json.dumps(
        {
            "lat": g_lat,
            "lon": g_lon,
            "zoom": zoom_lvl,
            "precision": g_prec,
            "points": g_pts,
            "gis_markers": gis_markers,
            "label": f"{filing['province']} / {filing['district']} — {filing['project_name'][:90]}",
        },
        ensure_ascii=False,
    )

    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>e-ÇED Ön Özet #{_esc(filing_id)} — {_esc(filing['province'])} / {_esc(filing['district'])}</title>
  <link rel="stylesheet" href="{LEAFLET_CSS}" />
  <style>{BASE_CSS}</style>
</head>
<body>
{_topbar_html('digest', prefix='../')}
<div class="wrap narrow">
  <header style="margin-bottom:16px;">
    <div class="card-ctx no-print" style="margin-bottom:8px;">
      <span><a href="../index.html">← Duyurulara dön</a> · <strong>{_esc(filing['province'])} / {_esc(filing['district'])}</strong> · {_esc(filing['project_type'])} · {_esc(filing['sector'])}</span>
      <span><code>#{_esc(filing_id)}</code> · {_esc(filing['announcement_date_tr'])}</span>
    </div>
    <h1>{_esc(filing['project_name'])}</h1>
    <p class="sub">{_esc(filing['project_owner'])}</p>
    <div class="badges" style="margin-top:10px;">
      <span class="badge">{_esc(filing['decision_type'])}</span>
      {clocks_html}
      {rev_badges_html}
      {gis_high_badge}
    </div>
    <div class="actions no-print" style="border-top:none;padding-top:4px;">
      <a class="btn-primary" href="{_esc(pdf_url)}" target="_blank" rel="noopener">Resmi PDF Dosyası ↗</a>
      <a class="btn-secondary" href="{_esc(doc_meta.get('portal_doc_url', ''))}" target="_blank" rel="noopener">e-ÇED Portal Kaydı ↗</a>
      <a class="btn-secondary" href="{_esc(raw_md_filename)}">Markdown (.md)</a>
      <button type="button" class="btn-secondary" onclick="window.print()">Yazdır / PDF</button>
    </div>
  </header>

  <table class="kv">
    <tr><th>Hazırlayan Kuruluş</th><td>{_esc(doc_meta.get('consulting_firm') or '—')}</td></tr>
    <tr><th>Sektör / Alt Sektör</th><td>{_esc(filing['sector'])} / {_esc(filing['sub_sector'])}</td></tr>
    <tr><th>Duyuru ve Yükleme</th><td>Duyuru: <code>{_esc(filing['announcement_date_tr'])}</code> · Yükleme: <code>{_esc(doc_meta.get('submitted_at') or '—')}</code></td></tr>
    <tr><th>PDF Kapsamı</th><td>{pdf_info['bytes'] / 1024 / 1024:.2f} MB · {analysis['page_count']} sayfa ({analysis['text_pages']} metin / {analysis['scanned_or_blank_pages']} taranmış) · <a href="{_esc(osm_url)}" target="_blank" rel="noopener">OpenStreetMap ↗</a> · <a href="{_esc(gmaps_url)}" target="_blank" rel="noopener">Google Haritalar ↗</a></td></tr>
  </table>

  {rev_section_html}

  {llm_block}

  <h2>Konum Haritası ve 3 km Çevre Taraması</h2>
  <div class="map-box">
    <div id="digest-map"></div>
    <div class="map-bar"><span>{_esc(geo_caption)}</span></div>
  </div>
  {gis_section_html}

  <h2>Ham Kayıt ve Derin Teknik Ekler</h2>
  <details class="accordion">
    <summary>Resmi Duyuru Metni (Bakanlık İlanı)</summary>
    <div class="accordion-body"><blockquote>{_esc(filing.get('detail_text', ''))}</blockquote></div>
  </details>
  <details class="accordion">
    <summary>Otomatik Metin Taraması (9 Deterministik Kontrol)</summary>
    <div class="accordion-body">
      <table class="kv" style="margin-top:0;">{checks_html}</table>
      <p class="sub">Metin katmanı (OCR) bulunmayan taranmış harita ve kurum görüşü ekleri otomatik taramaya dahil edilmemiştir.</p>
    </div>
  </details>
  <details class="accordion">
    <summary>Sayfa Kaynaklı Ham Alıntılar (7 Teknik Başlık)</summary>
    <div class="accordion-body">{''.join(sig_blocks)}</div>
  </details>
  <details class="accordion">
    <summary>Belge Bölüm Haritası ({len(analysis.get('headings') or [])} başlık)</summary>
    <div class="accordion-body"><ul style="margin:0;padding-left:20px;">{headings_html or '<li style="color:var(--muted)">Yapılandırılmış bölüm başlığı tespit edilememiştir.</li>'}</ul></div>
  </details>

  <div class="notice">
    Bu sayfa, T.C. Çevre, Şehircilik ve İklim Değişikliği Bakanlığı'nın kamuya açık <code>eced-duyuru.csb.gov.tr</code> duyuru portalındaki kayıtlar esas alınarak bilgilendirme amacıyla hazırlanmıştır. Alıntıların tamamı 1 tabanlı PDF sayfa numarasıyla (<code>[s. N]</code>) gösterilmektedir. Yasal sürelerin ve hukuki başvuru yollarının yetkili hukukçular tarafından teyit edilmesi gerekir.
  </div>
</div>
<script src="{LEAFLET_JS}"></script>
<script>
{THEME_JS}
{CARTO_TILE_HELPER_JS}
(() => {{
  const copyBtn = document.getElementById('copy-qs-btn');
  const qsTxt = document.getElementById('qs-plain');
  if (copyBtn && qsTxt) {{
    copyBtn.addEventListener('click', async () => {{
      try {{
        await navigator.clipboard.writeText(qsTxt.value);
        copyBtn.textContent = 'Kopyalandı ✓';
        setTimeout(() => (copyBtn.textContent = 'Soruları Kopyala'), 2200);
      }} catch (e) {{
        copyBtn.textContent = 'Kopyalanamadı';
      }}
    }});
  }}
  if (typeof L === 'undefined') return;
  const g = {map_payload};
  const map = L.map('digest-map').setView([g.lat, g.lon], g.zoom);
  let tileLayer = createCartoTileLayer(window.__ecedIsDark && window.__ecedIsDark()).addTo(map);
  window.addEventListener('eced-theme-change', (ev) => {{
    map.removeLayer(tileLayer);
    tileLayer = createCartoTileLayer(ev.detail.dark).addTo(map);
  }});
  if (g.precision === 'exact_pdf') {{
    L.circle([g.lat, g.lon], {{
      radius: 3000,
      color: '#d97706',
      weight: 1.5,
      dashArray: '6 5',
      fillColor: '#d97706',
      fillOpacity: 0.04
    }}).bindTooltip('3 km yasal referans çemberi (3573 m.20)').addTo(map);
    for (const gm of (g.gis_markers || [])) {{
      L.circleMarker([gm.lat, gm.lon], {{
        radius: 5,
        color: '#ffffff',
        fillColor: gm.color,
        fillOpacity: 0.9,
        weight: 1.5
      }}).bindPopup(gm.label).addTo(map);
    }}
  }}
  if (g.precision === 'exact_pdf' && g.points.length > 1) {{
    const latlngs = g.points.map(p => [p[0], p[1]]);
    const poly = L.polyline(latlngs, {{ color: '#175cd3', weight: 3, opacity: 0.85 }}).addTo(map);
    for (const ll of latlngs.slice(0, 30)) {{
      L.circleMarker(ll, {{ radius: 4, color: '#ffffff', fillColor: '#d92d20', fillOpacity: 0.9, weight: 1 }}).addTo(map);
    }}
    map.fitBounds(poly.getBounds().pad(0.25));
  }} else {{
    L.circleMarker([g.lat, g.lon], {{
      radius: g.precision === 'exact_pdf' ? 8 : 11,
      color: '#ffffff',
      fillColor: g.precision === 'exact_pdf' ? '#d92d20' : '#175cd3',
      fillOpacity: g.precision === 'exact_pdf' ? 0.9 : 0.45,
      weight: 2
    }}).bindPopup(g.label).addTo(map).openPopup();
  }}
}})();
</script>
</body>
</html>
"""


def build_rss(filings: list[dict[str, Any]], digests_index: set[str], site_url: str) -> str:
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Türkiye e-ÇED İzleme Platformu"
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = (
        "T.C. Çevre, Şehircilik ve İklim Değişikliği Bakanlığı'nın 81 ildeki kamuya açık e-ÇED duyuruları, "
        "10 günlük askı ve 30 günlük İYUK Madde 20/A süre takibi, belge revizyon arşivi ve sayfa kaynaklı teknik ön özetler."
    )
    ET.SubElement(channel, "language").text = "tr"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    for f in filings[:80]:
        docs = f.get("documents") or []
        doc_meta = docs[0] if docs else {}
        filing_id = doc_meta.get("filing_id")
        portal_url = doc_meta.get("portal_doc_url") or "https://eced-duyuru.csb.gov.tr/eced-prod/duyurular.xhtml"
        pdf_url = doc_meta["pdf_urls"][0]["url"] if doc_meta.get("pdf_urls") else None

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"[{f['province']}/{f['district']}] {f['decision_type']} ({f['project_type']}) — {f['project_name']}"
        )
        if filing_id and filing_id in digests_index and site_url.startswith("http"):
            ET.SubElement(item, "link").text = f"{site_url.rstrip('/')}/digests/{filing_id}.html"
        else:
            ET.SubElement(item, "link").text = portal_url

        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = f.get("filing_key") or portal_url

        ann_iso = f.get("announcement_date")
        if ann_iso:
            dt = datetime.fromisoformat(ann_iso).replace(tzinfo=timezone.utc)
            ET.SubElement(item, "pubDate").text = format_datetime(dt)

        clocks_txt = "; ".join(
            f"{c['kind']}: {c['deadline']} ({c['days_remaining']} gün kaldı)"
            if c.get("deadline")
            else c["kind"]
            for c in f.get("statutory_clocks") or []
        )
        desc_parts = [
            f"Proje Sahibi: {f.get('project_owner', '')}",
            f"Sektör: {f.get('sector', '')} / {f.get('sub_sector', '')} ({f.get('project_type', '')})",
            f"Yasal Süreler: {clocks_txt or 'Belirtilmemiş'}",
            f"Resmi Kayıt: {portal_url}",
        ]
        if pdf_url:
            desc_parts.append(f"Resmi PDF: {pdf_url}")
        if filing_id and filing_id in digests_index:
            desc_parts.append(f"Sayfa Kaynaklı Ön Özet: {site_url.rstrip('/')}/digests/{filing_id}.html")
        if f.get("detail_text"):
            desc_parts.append("")
            desc_parts.append(f["detail_text"])
        ET.SubElement(item, "description").text = "\n".join(desc_parts)

    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


def render_guide_html() -> str:
    template_text = """# Teknik İnceleme Notu — e-ÇED #[DOSYA_NO] ([İL] / [İLÇE])

- Resmi e-ÇED Kaydı: [e-ÇED portal bağlantısı]
- Aşama ve Yasal Son Tarih: [10 günlük askı süresi / HKT tarihi / 30 günlük İYUK Madde 20/A son günü]
- PDF Bütünlük Özeti (SHA-256 / Sürüm): [v1 veya v1→v2 fark özeti]

1. Başlangıç Verisi ve Örnekleme Eksiklikleri ([s. N]):
   - Raporda saha çalışması tarihleri, mevsimsel tekrar durumu veya örnekleme yöntemine ilişkin tespit edilen eksiklikleri sayfa numarasıyla belirtiniz.

2. Ekolojik, Hidrolojik veya Jeokimyasal Çelişkiler ([s. N]):
   - Su kaynakları, denizel/karasal ekosistemler, atık yönetimi veya emisyon varsayımlarındaki bilimsel tutarsızlıkları sayfa numarasıyla özetleyiniz.

3. Kümülatif Bölgesel Etki ve Mevzuat Boşlukları ([s. N]):
   - Çevredeki mevcut tesislerle birlikte ortaya çıkacak birikimli etkiler ile 3573 sayılı Zeytincilik Kanunu, 5403 sayılı Toprak Koruma Kanunu veya korunan alan statüsüne ilişkin eksiklikleri yazınız.

4. 2009/7 Genelgesi / Revizyon ve Proje Parçalama Kontrolü ([s. N]):
   - Önceki mahkeme iptali veya İptal/İade sonrası yeniden sunulan bir dosya ise, önceki sürümdeki eksikliklerin gerçekten giderilip giderilmediğini ya da eşik değer dolanımı bulunup bulunmadığını belirtiniz.

5. HKT Tutanağı veya Bilirkişi İncelemesi İçin Taslak Teknik Sorular:
   - [Somut, tarafsız ve ölçülebilir teknik soru 1] ([s. N])
   - [Somut, tarafsız ve ölçülebilir teknik soru 2] ([s. N])
   - [Somut, tarafsız ve ölçülebilir teknik soru 3] ([s. N])

6. İletilmesi Önerilen Kurum ve Paydaşlar:
   - İlgili TMMOB Meslek Odası / Yerel Çevre Derneği / İlgili Belediye Çevre Birimi / Yöre Sakinlerini Temsil Eden Çevre Hukukçuları"""

    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Kullanım ve Bilimsel İnceleme Rehberi — Türkiye e-ÇED İzleme Platformu</title>
  <style>{BASE_CSS}</style>
</head>
<body>
{_topbar_html('guide')}
<div class="wrap narrow">
  <header style="margin-bottom:18px;">
    <h1>Kullanım, Revizyon Takibi ve Bilimsel İnceleme Rehberi</h1>
    <p class="sub">Türkiye'nin <strong>81 ilindeki</strong> kamuya açık e-ÇED duyurularını izlemek, yasal süreleri kaçırmamak, rapor değişikliklerini (2009/7 Genelgesi dahil) belgelemek ve idari yargı düzeyinde teknik not hazırlamak için pratik başvuru kılavuzu.</p>
    <div class="toc-pills">
      <a href="#nasil">1. 3 Adımda Kullanım</a>
      <a href="#revizyon-2009-7">2. 2009/7 ve Revizyon Takibi</a>
      <a href="#emsaller">3. Emsal Başarılar (2019–2026)</a>
      <a href="#sureler">4. Yasal Süreler</a>
      <a href="#danistay">5. 7 Danıştay Ölçütü</a>
      <a href="#ehliyet">6. Dava Ehliyeti</a>
      <a href="#sablon">7. Teknik Not Şablonu</a>
    </div>
  </header>

  <h2 id="nasil">1. Platformu 3 Adımda Nasıl Kullanırsınız?</h2>
  <p class="sub">Platform <strong>Türkiye'nin tamamını (81 il)</strong> tarar; herhangi bir üyelik veya yazılım bilgisi gerektirmez:</p>
  <div class="step-grid">
    <div class="card">
      <div class="step-num">Adım 1 · 2 dakika</div>
      <div class="title">İlinizi veya Acil Süreleri Seçin</div>
      <p class="sub" style="margin-top:6px;">Ana sayfa varsayılan olarak <strong>en az günü kalan yasal sürelere</strong> göre sıralanır. İl menüsünden kendi ilinizi seçebilir, <strong>Revizyon / Süreç</strong> sekmesiyle değişen dosyaları ayıklayabilir ve filtrelenmiş görünümü tek tıkla paylaşabilirsiniz.</p>
    </div>
    <div class="card">
      <div class="step-num">Adım 2 · 30–60 dakika</div>
      <div class="title">Ön Özeti Resmi PDF ile Karşılaştırın</div>
      <p class="sub" style="margin-top:6px;"><strong>Ön Özet</strong> sayfasındaki her sayısal veri ve Danıştay bulgusu <code>[s. N]</code> sayfa numarası taşır. Doğrudan <strong>Resmi PDF Dosyası</strong> bağlantısını açarak ilgili sayfayı kendi uzmanlık süzgecinizden geçirin.</p>
    </div>
    <div class="card">
      <div class="step-num">Adım 3 · 10 dakika</div>
      <div class="title">Süre Dolmadan Yetkili Ağa İletin</div>
      <p class="sub" style="margin-top:6px;">Doğrulanmış bulguları ve hazır teknik soruları (tek tıkla kopyalayarak) süre dolmadan ilgili TMMOB odasına, yöredeki çevre derneğine, belediyeye veya yöre sakinlerini temsil eden avukatlara iletin.</p>
    </div>
  </div>

  <section id="revizyon-2009-7" class="callout rev">
    <h2 style="margin-top:0;">2. "Raporu Değiştirip Tekrar Onaylıyorlar — İzlemek Ne İşe Yarar?"</h2>
    <p>Bu soru Türkiye'de çevre hukukunu yakından bilen herkesin haklı olarak sorduğu en gerçekçi sorudur. Resmi Bakanlık istatistiklerine göre 1993–2023 arasında on binlerce projeye onay verilirken <em>ÇED Olumsuz</em> kararı oranı binde birin altındadır. Üstelik bir proje mahkeme kararıyla iptal edildiğinde dahi idare, <strong>2009/7 Sayılı Genelge</strong> kapsamında tüm süreci baştan işletmeden sadece mahkemenin eksik bulduğu bölümleri yeniletip kısa sürede yeniden <em>ÇED Olumlu</em> kararı verebilmektedir (hukukçuların deyimiyle <em>"ÇED döngüsü"</em>).</p>
    <p><strong>Buna rağmen şeffaf izleme ve revizyon arşivi üç somut nedenle kritik kaldıraç üretir:</strong></p>
    <ul>
      <li><strong>Muhatap Bakanlık değil, İdare Mahkemeleri ve Bilirkişi Heyetleridir:</strong> Gerçek hukuki sonuç, <strong>İYUK Madde 20/A</strong> kapsamındaki 30 günlük süre kaçırılmadan açılan iptal davaları ve <em>yürütmenin durdurulması</em> kararlarıyla alınır. 2009/7 ile yeniden verilen kararlar da teknik eksiklik sürüyorsa mahkemelerce tekrar iptal edilmektedir.</li>
      <li><strong>Zaman ve finansman sürtünmesi projeleri durdurur:</strong> Her yürütmeyi durdurma ve iptal kararı kredi/sigorta akışını dondurur, saha tahribatını geciktirir ve pek çok projenin ekonomik olarak sürdürülemez hale gelip rafa kalkmasına yol açar.</li>
      <li><strong>Sessiz değişiklikler kanıta dönüşür (SHA-256 ve v1 → v2 Fark Takibi):</strong> Platform, her PDF dosyasının <strong>SHA-256 kriptografik özetini</strong>, yükleme tarihini (<code>yuklemeTarihi</code>), sayfa sayısını, koordinatlarını ve mevzuat göstergelerini arşivler. Aynı dosya numarasında yeni PDF yüklendiğinde sürüm farkı (<code>v1 → v2</code>) otomatik olarak kaydedilir.</li>
    </ul>
  </section>

  <h2 id="emsaller">3. Emsal Başarılar — Türkiye'de Neler Gerçekten İşe Yaradı? (2019–2026)</h2>
  <p class="sub">Yakın dönemdeki somut çevre davaları incelendiğinde, projeleri kalıcı olarak durduran başarıların ortak özelliği <strong>tek başına ÇED iptaliyle yetinmemek</strong>, olumsuz kurum görüşlerini ve eşlikçi izin/ruhsatları birlikte hedeflemektir:</p>
  <table class="data-tbl">
    <thead><tr><th>Proje / Bölge</th><th>Sonuç</th><th>Belirleyici Hukuki ve Teknik Kaldıraç</th></tr></thead>
    <tbody>
      <tr><td><strong>Bartın Amasra HEMA Termik</strong></td><td><span class="badge ok">Kalıcı iptal</span></td><td>Danıştay proje parçalamadan ÇED'leri iptal etti; 1/100k plan iptali ve ardından Danıştay İDDK'nın <strong>EPDK üretim lisansını kesin iptal etmesi</strong> 2009/7 kapısını tamamen kapattı.</td></tr>
      <tr><td><strong>Eskişehir Alpu Termik</strong></td><td><span class="badge ok">Kalıcı iptal</span></td><td>Büyükşehir Belediyesi ve TMMOB, ÇED yanında <strong>5403 Büyük Ova tarım dışı kullanım izinlerini</strong> de dava etti; Bölge İdare Mahkemesi izinleri oybirliğiyle iptal etti.</td></tr>
      <tr><td><strong>Murat Dağı Altın Madeni</strong></td><td><span class="badge ok">ÇED Olumsuz (2× onandı)</span></td><td>Havza ölçeğinde su, tarım, orman ve termal turizm kanıtları Bakanlığın nadir <strong>ÇED Olumsuz</strong> kararı vermesini sağladı; Kütahya İdare Mahkemesi 2024 ve Aralık 2025'te bu reddi iki kez hukuka uygun buldu.</td></tr>
      <tr><td><strong>Ordu Fatsa Altın Madeni</strong></td><td><span class="badge ok">Faaliyet durduruldu</span></td><td>Mahkeme 10 yıllık <strong>maden ruhsatı yenileme (temdit) işlemini</strong> iptal edince Valilik Şubat 2024'te faaliyetleri durdurdu.</td></tr>
      <tr><td><strong>Bursa Kirazlıyayla 2. Atık Barajı</strong></td><td><span class="badge ok">Süreç sonlandırıldı</span></td><td><strong>MAPEG'in olumsuz kurum görüşü</strong> üzerine Çevre Bakanlığı süreci mahkemeye dahi gerek kalmadan Nisan 2025'te sonlandırdı.</td></tr>
      <tr><td><strong>İzmir Aliağa Batıçim Klinker</strong></td><td><span class="badge ok">Oybirliğiyle iptal</span></td><td>EGEÇEP ve Foça Platformu davasında İzmir 5. İdare Mahkemesi (Ekim 2026), 65 bin m² betonlaşmanın hidrojeolojiyi bozduğu ve Aliağa hava taşıma kapasitesinin dolduğu gerekçesiyle Ek-2 kararını iptal etti.</td></tr>
      <tr><td><strong>Karaburun Küçükbahçe &amp; Yaylaköy</strong></td><td><span class="badge ok">İptal / YD</span></td><td>ÖÇK kesin korunacak alan statüsü, <strong>3573 zeytinlik kuralı (~6.000 ağaç)</strong> ve imar/yapı ruhsatına paralel dava ile durduruldu.</td></tr>
      <tr><td><strong>Muğla Deştin Çimento</strong></td><td><span class="badge warn">2009/7 döngüsü uyarısı</span></td><td>Yargı iptallerine karşın eşlikçi izinler sürdüğü için 2009/7 Genelgesi ile Temmuz 2025'te 3. kez ÇED Olumlu verildi — <em>paralel ruhsat/plan takibinin neden zorunlu olduğunun kanıtı</em>.</td></tr>
    </tbody>
  </table>

  <h2 id="sureler">4. Hukuki Aşamalar ve Gerçek Yasal Süreler</h2>
  <p class="sub">29 Temmuz 2022 tarihli ve 31907 sayılı ÇED Yönetmeliği (2025–2026 güncellemeleriyle Ek-2 kararlarında <strong>"ÇED Olumlu (Kapsam Ek-2)"</strong> kullanımı) ve 2577 sayılı İYUK esas alınmaktadır:</p>
  <table class="kv">
    <tr><th>İYUK Madde 20/A İptal Davası (30 Takvim Günü)</th><td><em>ÇED Olumlu</em>, <em>ÇED Olumlu (Kapsam Ek-2)</em> veya <em>ÇED Gerekli Değildir</em> kararlarına karşı dava açma süresi ilan/tebliğden itibaren kesin <strong>30 takvim günüdür</strong>. <strong>İYUK Madde 11 başvuruları bu süreyi durdurmaz</strong>.</td></tr>
    <tr><th>Madde 14 Nihai ÇED Askısı (10 Takvim Günü)</th><td>İDK tarafından son şekli verilen Ek-1 Nihai ÇED Raporu, halkın görüş ve önerileri için <strong>10 takvim günü</strong> süreyle askıda ve internette ilan edilir.</td></tr>
    <tr><th>HKT (m. 9) ve İDK (m. 11–12)</th><td>HKT tutanaklarına geçirilen somut teknik sorular ve İDK öncesi yazılı görüşler, sonraki olası davada idari dosyanın resmi parçası haline gelir.</td></tr>
    <tr><th>ÇED Süreci Başlayan (m. 8 / m. 16)</th><td>Kesin bir 10 günlük düşme süresi doğurmaz; karar verilmeden önce dosyayı erkenden incelemek için erken uyarı aşamasıdır.</td></tr>
    <tr><th>İptal / İade ve 2009/7 Takibi</th><td>İptal/iade edilen veya geçmiş yıllardan yeniden açılan dosyalar aynı şirket/ruhsat üzerinden geri döndüğünde platformda <strong>Revizyon / İlişkili</strong> olarak işaretlenir.</td></tr>
  </table>

  <h2 id="danistay">5. İdari Yargıda Ne "Bulgu" Sayılır? (7 Temel Danıştay İptal Ölçütü)</h2>
  <table class="kv">
    <tr><th>1. 3573 Sayılı Zeytincilik Kanunu (m. 20)</th><td>Zeytinlik sahaları içinde ve <strong>en az 3 km mesafede</strong> zeytinyağı fabrikası hariç toz, duman veya kimyevi atık bırakan tesisler mutlak yasaktır; filtreleme taahhütleri bu yasağı kaldırmaz.</td></tr>
    <tr><th>2. Proje Parçalama (Eşik Değer Dolanılması)</th><td>Ek-1 kapsamına girmesi gereken bir yatırımın veya kapasite artışının yapay biçimde bölünerek Ek-2 üzerinden geçirilmesi bütüncül inceleme ilkesine aykırıdır.</td></tr>
    <tr><th>3. Kümülatif (Birikimli) Etki Eksikliği</th><td>Bölgedeki mevcut veya planlanan diğer maden, enerji, sanayi ve su yükleriyle birlikte taşıma kapasitesinin değerlendirilmemesi başlıca iptal gerekçesidir.</td></tr>
    <tr><th>4. Flora, Fauna ve Mevsimsellik Eksikliği</th><td>Yalnızca literatür taramasına (<code>L</code>) veya tek mevsimlik gözlemlere dayanan tür listeleri, göçmen kuşların ve endemik/IUCN/Bern türlerinin atlanması raporları sakatlar.</td></tr>
    <tr><th>5. Su Kaynakları ve Başlangıç Analizleri</th><td>Akifer, dere rejimi veya can suyu etkilerinin hidrojeolojik olarak modellenmemesi ya da başlangıç su analizlerinin onay sonrasına ertelenmesi ağır eksikliktir.</td></tr>
    <tr><th>6. 5403 Toprak Koruma, Orman, ÖÇK/SİT ve Kurum Görüşleri</th><td>Mutlak/dikili tarım arazilerinin vasfının bozulması, zorunlu kurum görüşlerinin (DSİ, İl Tarım, OGM) eksik olması veya yer/teknoloji alternatiflerinin irdelenmemesi hukuka aykırılık doğurur.</td></tr>
    <tr><th>7. Ölçüm Hataları ve İç Tutarlılık</th><td>Kapasite, koordinat veya parsel çelişkileri ile teknik olarak imkânsız izleme yöntemleri bilirkişi denetiminin doğrudan konusudur.</td></tr>
  </table>

  <h2 id="ehliyet">6. Kimler Dava Açabilir? (Dava Ehliyeti)</h2>
  <table class="kv">
    <tr><th>Yöre Sakinleri ve Taşınmaz Sahipleri</th><td>Projenin etki alanında ikamet eden yurttaşlar ve taşınmaz sahipleri en güçlü dava ehliyetine sahiptir.</td></tr>
    <tr><th>TMMOB ve Meslek Odaları</th><td>Çevre, Ziraat, Jeoloji, Orman, Maden ve Şehir Plancıları Odaları uzmanlık alanlarına giren projelerde doğrudan dava açabilir.</td></tr>
    <tr><th>Çevre Dernekleri &amp; Belediyeler</th><td>Tüzüğünde çevre koruma amacı bulunan bölge dernekleri ile ilgili büyükşehir/ilçe belediyelerinin dava ehliyeti kabul edilmektedir.</td></tr>
    <tr><th>Barolar (İçtihat Uyarısı)</th><td>Danıştay, <strong>baroların kendi tüzel kişilikleri adına ÇED iptal davası açma ehliyetini çoğunlukla reddetmektedir</strong>. Baro çevre komisyonları doğrudan davacı olarak değil, <strong>yöre sakinlerine hukuki temsil ve dilekçe desteği</strong> vererek sürece katılmaktadır.</td></tr>
  </table>

  <div class="section-head-row" id="sablon" style="margin-top:28px;">
    <h2 style="margin:0;">7. Bir Sayfalık Teknik İnceleme Notu Şablonu</h2>
    <button type="button" class="btn-secondary no-print" id="copy-tpl-btn">Şablonu Kopyala</button>
  </div>
  <pre class="template-box" id="tpl-pre">{_esc(template_text)}</pre>

  <div class="notice">
    <strong>Yasal Bilgilendirme:</strong> Bu platform yalnızca kamuoyu şeffaflığı ve bilgilendirme amacıyla hazırlanmış olup hukuki danışmanlık niteliği taşımaz. Tüm yasal sürelerin, dava ehliyeti şartlarının ve güncel mevzuat değişikliklerinin herhangi bir başvuru öncesinde avukat tarafından doğrulanması gerekmektedir.
  </div>
</div>
<script>
{THEME_JS}
(() => {{
  const btn = document.getElementById('copy-tpl-btn');
  const pre = document.getElementById('tpl-pre');
  if (btn && pre) {{
    btn.addEventListener('click', async () => {{
      try {{
        await navigator.clipboard.writeText(pre.textContent);
        btn.textContent = 'Kopyalandı ✓';
        setTimeout(() => (btn.textContent = 'Şablonu Kopyala'), 2200);
      }} catch (e) {{
        btn.textContent = 'Kopyalanamadı';
      }}
    }});
  }}
}})();
</script>
</body>
</html>
"""


def _urgency_rank_value(filing: dict[str, Any]) -> int:
    """Numeric rank for urgency sorting (lower = more urgent)."""
    clocks = filing.get("statutory_clocks") or []
    hard_days = [
        c["days_remaining"]
        for c in clocks
        if c.get("code") in ("iyuk_20a", "aski_10d")
        and c.get("days_remaining") is not None
        and c["days_remaining"] >= 0
    ]
    if hard_days:
        return min(hard_days)
    meeting_days = [
        c["days_remaining"]
        for c in clocks
        if c.get("code") in ("hkt", "idk")
        and c.get("days_remaining") is not None
        and c["days_remaining"] >= 0
    ]
    if meeting_days:
        return 200 + min(meeting_days)
    if any(c.get("code") in ("hkt", "idk") and c.get("days_remaining") is None for c in clocks):
        return 500
    if any(c.get("code") == "process_open" for c in clocks):
        return 800
    return 10000


def _urgency_sort_key(filing: dict[str, Any]) -> tuple[int, str]:
    ann = filing.get("announcement_date") or "0000-00-00"
    inv_date = "".join(chr(ord("9") - ord(ch) + ord("0")) if ch.isdigit() else ch for ch in ann)
    return (_urgency_rank_value(filing), inv_date)


def _format_rev_inline(rev_entry: dict[str, Any] | None) -> str:
    if not rev_entry or not rev_entry.get("has_audit_alert"):
        return ""
    bits: list[str] = []
    diff = rev_entry.get("latest_pdf_diff")
    if diff:
        bits.append(f"<strong>PDF Farkı (v{diff['from_version']}→v{diff['to_version']}):</strong> {_esc(diff['summary_tr'])}")
    tl = rev_entry.get("timeline") or []
    if len(tl) >= 2:
        chain = " → ".join(f"{t['announcement_date_tr']} {t['decision_type']}" for t in tl[-3:])
        bits.append(f"<strong>Süreç:</strong> {_esc(chain)}")
    rel = rev_entry.get("related_filings") or []
    if rel:
        rel_str = ", ".join(f"#{r['filing_id']} ({r['decision_type']})" for r in rel[:3])
        bits.append(f"<strong>İlişkili:</strong> {_esc(rel_str)}")
    if "circular_2009_7" in (rev_entry.get("flags") or []):
        bits.append("<strong>2009/7 / yargı sonrası</strong> ibaresi tespit edildi")
    if not bits:
        return ""
    return f'<div class="rev-inline">{" &nbsp;·&nbsp; ".join(bits)}</div>'


def build_site(
    filings: list[dict[str, Any]],
    *,
    digests_dir: Path,
    docs_dir: Path,
    site_url: str = "https://yanekyuk.github.io/eced-watchdog/",
    max_cards: int = 300,
    revisions_out: Path | None = None,
    gis_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    docs_digests = docs_dir / "digests"
    docs_digests.mkdir(parents=True, exist_ok=True)
    gis_cache = gis_cache or {}

    digests_map: dict[str, dict[str, Any]] = {}
    digests_index: set[str] = set()
    llm_summaries: dict[str, dict[str, Any]] = {}
    geo_by_fid: dict[str, dict[str, Any]] = {}
    gis_by_fid: dict[str, dict[str, Any]] = {}
    gis_alerts_by_fid: dict[str, list[dict[str, Any]]] = {}

    if digests_dir.exists():
        for json_file in sorted(digests_dir.glob("*_analysis.json")):
            try:
                saved = json.loads(json_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            fid = json_file.name.replace("_analysis.json", "")
            digests_map[fid] = saved
            digests_index.add(fid)
            if saved.get("llm_synthesis") and saved["llm_synthesis"].get("result"):
                llm_summaries[fid] = saved["llm_synthesis"]
            if saved.get("analysis") and saved["analysis"].get("geo"):
                g = saved["analysis"]["geo"]
                geo_by_fid[fid] = g
                if g.get("precision") == "exact_pdf" and g.get("lat") is not None and g.get("lon") is not None:
                    ck = coord_cache_key(float(g["lat"]), float(g["lon"]))
                    if ck in gis_cache:
                        gis_by_fid[fid] = gis_cache[ck]
                        gis_alerts_by_fid[fid] = detect_spatial_omissions(
                            gis_cache[ck],
                            (saved.get("analysis") or {}).get("audit_checks"),
                        )

    rev_index = build_revision_index(filings, digests_map)
    if revisions_out is not None:
        revisions_out.parent.mkdir(parents=True, exist_ok=True)
        revisions_out.write_text(
            json.dumps(rev_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    for fid, saved in sorted(digests_map.items()):
        md_src = digests_dir / f"{fid}_digest.md"
        md_dst_name = f"{fid}.md"
        if md_src.exists():
            shutil.copyfile(md_src, docs_digests / md_dst_name)
        rev_entry = rev_index["by_filing_id"].get(fid)
        html_out = render_digest_html(saved, md_dst_name, rev_entry=rev_entry, gis_entry=gis_by_fid.get(fid))
        (docs_digests / f"{fid}.html").write_text(html_out, encoding="utf-8")

    recent_pool = filings[:max_cards]
    shown_filings = sorted(recent_pool, key=_urgency_sort_key)
    total = len(shown_filings)
    prov_counts = Counter(f.get("province", "") for f in shown_filings if f.get("province"))
    provinces_present = sorted(prov_counts.keys())
    active_count = sum(
        1
        for f in shown_filings
        if any(
            c.get("days_remaining") is None or c.get("days_remaining", -1) >= 0
            for c in f.get("statutory_clocks") or []
        )
    )
    ek1_count = sum(1 for f in shown_filings if f.get("project_type") == "Ek-1")
    digested_count = sum(
        1
        for f in shown_filings
        if (f.get("documents") or [{}])[0].get("filing_id") in digests_index
    )

    cards_html: list[str] = []
    map_items: list[dict[str, Any]] = []
    exact_geo_count = 0
    rev_alert_cards = 0

    for idx, f in enumerate(shown_filings):
        docs = f.get("documents") or []
        doc_meta = docs[0] if docs else {}
        fid = doc_meta.get("filing_id") or ""
        portal_url = doc_meta.get("portal_doc_url") or ""
        pdf_url = doc_meta["pdf_urls"][0]["url"] if doc_meta.get("pdf_urls") else ""
        has_digest = fid in digests_index
        clock = _best_active_clock(f)
        urgency_rank = _urgency_rank_value(f)
        is_urgent = urgency_rank <= 7
        is_active = any(
            c.get("days_remaining") is None or c.get("days_remaining", -1) >= 0
            for c in f.get("statutory_clocks") or []
        )
        is_ek1 = f.get("project_type") == "Ek-1"
        stage_bucket = _stage_filter_bucket(f)

        rev_entry = rev_index["by_filing_key"].get(f.get("filing_key", "")) or rev_index["by_filing_id"].get(fid)
        has_rev_alert = bool(rev_entry and rev_entry.get("has_audit_alert"))
        if has_rev_alert:
            rev_alert_cards += 1

        geo = geo_by_fid.get(fid)
        if geo and geo.get("precision") == "exact_pdf" and geo.get("lat") and geo.get("lon"):
            lat, lon = geo["lat"], geo["lon"]
            precision = "exact_pdf"
            exact_geo_count += 1
        else:
            lat, lon = province_centroid(f.get("province", ""), jitter_key=f.get("filing_key") or str(idx))
            precision = "province_centroid"

        gis_alerts = gis_alerts_by_fid.get(fid) or []
        gis_high_badge = (
            '<span class="badge urgent">3 km Mekânsal Uyarı</span>'
            if any(a.get("severity") == "high" for a in gis_alerts)
            else ""
        )

        search_blob = " ".join(
            [
                f.get("province", ""),
                f.get("district", ""),
                f.get("project_name", ""),
                f.get("project_owner", ""),
                f.get("sector", ""),
                f.get("sub_sector", ""),
                f.get("decision_type", ""),
                f.get("detail_text", ""),
                fid,
                " ".join(rev_entry.get("flags") or []) if rev_entry else "",
                " ".join(a.get("title", "") for a in gis_alerts),
            ]
        ).lower()

        actions: list[str] = []
        if has_digest:
            actions.append(f'<a class="btn-primary" href="digests/{_esc(fid)}.html">Ön Özeti Aç →</a>')
            if pdf_url:
                actions.append(f'<a class="quiet-link" href="{_esc(pdf_url)}" target="_blank" rel="noopener">Resmi PDF ↗</a>')
            if portal_url:
                actions.append(f'<a class="quiet-link" href="{_esc(portal_url)}" target="_blank" rel="noopener">e-ÇED ↗</a>')
            actions.append(f'<a class="quiet-link" href="digests/{_esc(fid)}.md">Markdown</a>')
        else:
            if pdf_url:
                actions.append(f'<a class="btn-secondary" href="{_esc(pdf_url)}" target="_blank" rel="noopener">Resmi PDF ↗</a>')
            if portal_url:
                actions.append(f'<a class="quiet-link" href="{_esc(portal_url)}" target="_blank" rel="noopener">e-ÇED Kaydı #{_esc(fid)} ↗</a>')

        llm_info = llm_summaries.get(fid)
        llm_badge = ""
        body_html = ""
        if llm_info:
            lres = llm_info["result"]
            high_flags = sum(1 for rf in lres.get("red_flags") or [] if rf.get("severity") == "high")
            total_flags = len(lres.get("red_flags") or [])
            if high_flags:
                llm_badge = f'<span class="badge urgent">{high_flags} yüksek / {total_flags} bulgu</span>'
            else:
                llm_badge = f'<span class="badge ok">{total_flags} bulgu</span>'
            body_html = f'<p class="summary-clamp">{_esc(lres.get("executive_summary_tr", ""))}</p>'
        else:
            raw_det = (f.get("detail_text") or "").strip()
            if raw_det:
                body_html = f'<p class="summary-clamp muted">{_esc(raw_det[:260])}</p>'

        title_text = _esc(f.get("project_name", ""))
        if has_digest:
            title_html = f'<a href="digests/{_esc(fid)}.html">{title_text}</a>'
        elif portal_url:
            title_html = f'<a href="{_esc(portal_url)}" target="_blank" rel="noopener">{title_text}</a>'
        else:
            title_html = title_text

        # Tier 1 quiet metadata line (all location/scope/coord info preserved, zero boxes)
        ctx_parts = [
            f'<span class="ctx-loc">{_esc(f.get("province", ""))} / {_esc(f.get("district", ""))}</span>',
            f'<span class="{"ctx-ek1" if is_ek1 else ""}">{_esc(f.get("project_type", ""))}</span>',
            f'<span>{_esc(f.get("sector", ""))}</span>',
        ]
        if precision == "exact_pdf":
            ctx_parts.append('<span class="ctx-geo">● PDF Koordinatı</span>')
        ctx_left_html = '<span class="ctx-sep">·</span>'.join(ctx_parts)

        map_items.append(
            {
                "idx": idx,
                "lat": lat,
                "lon": lon,
                "precision": precision,
                "color": _marker_color(f, has_digest),
                "province": f.get("province", ""),
                "district": f.get("district", ""),
                "title": (f.get("project_name") or "")[:120],
                "stage": f.get("decision_type", ""),
                "annex": f.get("project_type", ""),
                "date": f.get("announcement_date_tr", ""),
                "digest_url": f"digests/{fid}.html" if has_digest else None,
                "portal_url": portal_url or None,
            }
        )

        card_classes = ["card"]
        if is_urgent:
            card_classes.append("urgent-edge")
        elif is_ek1:
            card_classes.append("ek1")
        if has_rev_alert:
            card_classes.append("has-rev")

        cards_html.append(
            f"""<article class="{' '.join(card_classes)}"
  data-idx="{idx}"
  data-urgency="{urgency_rank}"
  data-date="{_esc(f.get('announcement_date') or '0000-00-00')}"
  data-province="{_esc(f.get('province', ''))}"
  data-stage="{_esc(stage_bucket)}"
  data-active="{'1' if is_active else '0'}"
  data-digest="{'1' if has_digest else '0'}"
  data-rev="{'1' if has_rev_alert else '0'}"
  data-exactgeo="{'1' if precision == 'exact_pdf' else '0'}"
  data-annex="{_esc(f.get('project_type', ''))}"
  data-search="{_esc(search_blob)}">
  <div class="card-ctx">
    <div class="ctx-left">{ctx_left_html}</div>
    <div class="ctx-right">{f'#{_esc(fid)} · ' if fid else ''}{_esc(f.get('announcement_date_tr', ''))}</div>
  </div>
  <div class="title">{title_html}</div>
  <div class="owner-line">{_esc(f.get('project_owner', ''))}</div>
  <div class="badges">
    <span class="badge">{_esc(f.get('decision_type', ''))}</span>
    {_clock_badge_html(clock)}
    {llm_badge}
    {_revision_badges_html(rev_entry)}
    {gis_high_badge}
  </div>
  {body_html}
  {_format_rev_inline(rev_entry)}
  <div class="actions">{''.join(actions)}</div>
</article>"""
        )

    prov_options = "\n".join(
        f'<option value="{_esc(p)}">{_esc(p)} ({prov_counts[p]})</option>'
        for p in provinces_present
    )

    built_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    map_json = json.dumps(map_items, ensure_ascii=False)

    index_html = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Türkiye e-ÇED İzleme Platformu — 81 İl Yasal Süre ve Revizyon Takibi</title>
  <link rel="alternate" type="application/rss+xml" title="Türkiye e-ÇED İzleme RSS" href="feed.xml" />
  <link rel="stylesheet" href="{LEAFLET_CSS}" />
  <style>{BASE_CSS}</style>
</head>
<body>
{_topbar_html('index')}
<div class="wrap">
  <header class="masthead">
    <div class="masthead-left">
      <h1>Türkiye e-ÇED İzleme Platformu</h1>
      <p class="sub">81 ildeki kamuya açık ÇED duyuruları, 10/30 günlük yasal süreler, SHA-256 PDF revizyon takibi ve sayfa kaynaklı teknik ön özetler.</p>
    </div>
    <div class="masthead-right">
      <span>Güncelleme: <code>{_esc(built_at)}</code></span>
      <a class="btn-secondary" href="rehber.html">Nasıl Kullanılır? →</a>
    </div>
  </header>

  <section class="kpi-line" aria-label="Özet göstergeler">
    <span class="kpi-item"><strong>{total}</strong> duyuru ({len(provinces_present)} ilde aktif)</span>
    <span class="kpi-sep">·</span>
    <span class="kpi-item accent"><strong>{active_count}</strong> aktif yasal süre</span>
    <span class="kpi-sep">·</span>
    <span class="kpi-item"><strong>{ek1_count}</strong> Ek-1</span>
    <span class="kpi-sep">·</span>
    <span class="kpi-item"><strong>{digested_count}</strong> ön özet hazır</span>
    <span class="kpi-sep">·</span>
    <span class="kpi-item rev"><strong>{rev_alert_cards}</strong> revizyon / süreç</span>
  </section>

  <section class="map-box" id="map-box">
    <div class="map-bar">
      <div class="map-legend-inline">
        <strong>Harita</strong>
        <span><span class="dot" style="background:#d92d20"></span>≤7g acil</span>
        <span><span class="dot" style="background:#d97706"></span>8–15g / HKT-İDK</span>
        <span><span class="dot" style="background:#16a34a"></span>&gt;15g aktif</span>
        <span><span class="dot" style="background:#175cd3"></span>m. 8/16</span>
        <span><span class="dot" style="background:#667085"></span>Süresi doldu</span>
      </div>
      <button type="button" class="ghost-btn" id="map-toggle">Haritayı Gizle</button>
    </div>
    <div id="map"></div>
  </section>

  <section class="controls-panel">
    <div class="controls-row">
      <input id="q" type="search" placeholder="İl, ilçe, proje adı, şirket, sektör veya #ID ara…" />
      <select id="prov" class="filter-select" aria-label="İl filtresi">
        <option value="">Tüm İller ({len(provinces_present)})</option>
        {prov_options}
      </select>
      <select id="sort" class="filter-select" aria-label="Sıralama ölçütü">
        <option value="urgent" selected>Sırala: En acil süre</option>
        <option value="newest">Sırala: En yeni</option>
        <option value="rev">Sırala: Revizyon / süreç</option>
        <option value="digest">Sırala: Ön özetliler</option>
        <option value="ek1">Sırala: Ek-1 öncelikli</option>
      </select>
      <button type="button" class="ghost-btn" id="adv-toggle">Gelişmiş ▾</button>
    </div>
    <div class="controls-row advanced-row" id="adv-row">
      <select id="stage" class="filter-select" aria-label="Aşama filtresi">
        <option value="">Tüm Hukuki Aşamalar</option>
        <option value="iyuk_20a">İYUK 20/A (30 gün)</option>
        <option value="aski_10d">Madde 14 Askı (10 gün)</option>
        <option value="hkt_idk">HKT / İDK Toplantısı</option>
        <option value="process_open">Karar Öncesi (m. 8/16)</option>
        <option value="iptal_iade">İptal / İade</option>
      </select>
      <span class="sub" style="font-size:0.8rem;">Beyaz çerçeveli harita noktaları PDF metninden çıkarılmış kesin koordinatları gösterir.</span>
    </div>
    <div class="controls-row">
      <button class="pill active" data-filter="all" type="button">Tümü</button>
      <button class="pill" data-filter="active" type="button">Aktif Süreler</button>
      <button class="pill" data-filter="digest" type="button">Ön Özeti Hazır</button>
      <button class="pill" data-filter="ek1" type="button">Ek-1</button>
      <button class="pill rev-pill" data-filter="rev" type="button">Revizyon / Süreç ({rev_alert_cards})</button>
      <div class="ctrl-right">
        <button class="ghost-btn" id="share-btn" type="button">Bağlantıyı Kopyala</button>
        <button class="ghost-btn" id="reset-btn" type="button" style="display:none;">Sıfırla</button>
      </div>
    </div>
  </section>

  <div class="list-meta">
    <span id="count">Toplam {total} duyuru</span>
    <span id="page-info"></span>
  </div>
  <main class="cards" id="cards">
    {''.join(cards_html)}
  </main>
  <div class="pager" id="pager" style="display:none;">
    <button type="button" id="load-more-btn">Daha fazla göster</button>
    <button type="button" class="pager-all" id="show-all-btn">Tümünü göster</button>
  </div>

  <div class="notice">
    <strong>Yasal Bilgilendirme:</strong> Tüm kayıtlar T.C. Çevre, Şehircilik ve İklim Değişikliği Bakanlığı'nın kamuya açık e-ÇED duyuru portalından alınmaktadır. İYUK Madde 20/A uyarınca ÇED kararlarına karşı iptal davası süresi <strong>30 gündür</strong> ve <em>İYUK Madde 11 başvuruları bu süreyi durdurmaz</em>. Kesin tarih ve süreçler için hukukçulara danışınız.
  </div>
</div>
<script src="{LEAFLET_JS}"></script>
<script>
{THEME_JS}
{CARTO_TILE_HELPER_JS}
(() => {{
  const PAGE_SIZE = 20;
  const cardsContainer = document.getElementById('cards');
  const cards = [...document.querySelectorAll('#cards article')];
  const pills = [...document.querySelectorAll('button.pill')];
  const q = document.getElementById('q');
  const prov = document.getElementById('prov');
  const stageSel = document.getElementById('stage');
  const sortSel = document.getElementById('sort');
  const advToggle = document.getElementById('adv-toggle');
  const advRow = document.getElementById('adv-row');
  const resetBtn = document.getElementById('reset-btn');
  const shareBtn = document.getElementById('share-btn');
  const countEl = document.getElementById('count');
  const pageInfoEl = document.getElementById('page-info');
  const pagerEl = document.getElementById('pager');
  const loadMoreBtn = document.getElementById('load-more-btn');
  const showAllBtn = document.getElementById('show-all-btn');
  const mapBox = document.getElementById('map-box');
  const mapToggle = document.getElementById('map-toggle');
  const mapItems = {map_json};
  let mode = 'all';
  let pageLimit = PAGE_SIZE;

  // Restore filters from shareable URL query params (?il=...&filtre=...&q=...&asama=...&sira=...)
  const params = new URLSearchParams(window.location.search);
  if (params.get('q')) q.value = params.get('q');
  if (params.get('il')) prov.value = params.get('il');
  if (params.get('asama')) {{
    stageSel.value = params.get('asama');
    advRow.classList.add('open');
  }}
  if (params.get('sira')) sortSel.value = params.get('sira');
  if (params.get('filtre')) {{
    const fm = params.get('filtre');
    if (['all', 'active', 'digest', 'ek1', 'rev'].includes(fm)) {{
      mode = fm;
      pills.forEach(x => x.classList.toggle('active', x.dataset.filter === fm));
    }}
  }}

  function syncUrl() {{
    const p = new URLSearchParams();
    if (q.value.trim()) p.set('q', q.value.trim());
    if (prov.value) p.set('il', prov.value);
    if (mode !== 'all') p.set('filtre', mode);
    if (stageSel.value) p.set('asama', stageSel.value);
    if (sortSel.value !== 'urgent') p.set('sira', sortSel.value);
    const qs = p.toString();
    const next = qs ? `${{window.location.pathname}}?${{qs}}` : window.location.pathname;
    window.history.replaceState(null, '', next);
  }}

  let map = null;
  let layerGroup = null;
  let tileLayer = null;
  if (typeof L !== 'undefined') {{
    map = L.map('map').setView([39.0, 35.2], 6);
    tileLayer = createCartoTileLayer(window.__ecedIsDark && window.__ecedIsDark()).addTo(map);
    layerGroup = L.layerGroup().addTo(map);
    window.addEventListener('eced-theme-change', (ev) => {{
      if (!map || !tileLayer) return;
      map.removeLayer(tileLayer);
      tileLayer = createCartoTileLayer(ev.detail.dark).addTo(map);
    }});
  }}

  // Collapsible map state persisted in localStorage
  if (localStorage.getItem('eced_map_hidden') === '1') {{
    mapBox.classList.add('collapsed');
    mapToggle.textContent = 'Haritayı Göster';
  }}
  mapToggle.addEventListener('click', () => {{
    const collapsed = mapBox.classList.toggle('collapsed');
    mapToggle.textContent = collapsed ? 'Haritayı Göster' : 'Haritayı Gizle';
    localStorage.setItem('eced_map_hidden', collapsed ? '1' : '0');
    if (!collapsed && map) {{
      setTimeout(() => map.invalidateSize(), 60);
    }}
  }});

  advToggle.addEventListener('click', () => {{
    const open = advRow.classList.toggle('open');
    advToggle.textContent = open ? 'Gelişmiş ▴' : 'Gelişmiş ▾';
  }});

  function sortCards() {{
    const s = sortSel.value;
    cards.sort((a, b) => {{
      const ua = Number(a.dataset.urgency);
      const ub = Number(b.dataset.urgency);
      const da = a.dataset.date;
      const db = b.dataset.date;
      if (s === 'newest') {{
        if (db !== da) return db.localeCompare(da);
        return ua - ub;
      }}
      if (s === 'rev') {{
        const ra = Number(b.dataset.rev) - Number(a.dataset.rev);
        if (ra !== 0) return ra;
        if (ua !== ub) return ua - ub;
        return db.localeCompare(da);
      }}
      if (s === 'digest') {{
        const ha = Number(b.dataset.digest) - Number(a.dataset.digest);
        if (ha !== 0) return ha;
        if (ua !== ub) return ua - ub;
        return db.localeCompare(da);
      }}
      if (s === 'ek1') {{
        const ea = (b.dataset.annex === 'Ek-1' ? 1 : 0) - (a.dataset.annex === 'Ek-1' ? 1 : 0);
        if (ea !== 0) return ea;
        if (ua !== ub) return ua - ub;
        return db.localeCompare(da);
      }}
      if (ua !== ub) return ua - ub;
      return db.localeCompare(da);
    }});
    for (const c of cards) cardsContainer.appendChild(c);
  }}

  function escHtml(s) {{
    return String(s || '').replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
  }}

  function renderMap(matchedIdxSet) {{
    if (!layerGroup) return;
    layerGroup.clearLayers();
    const bounds = [];
    for (const item of mapItems) {{
      if (!matchedIdxSet.has(item.idx)) continue;
      const isExact = item.precision === 'exact_pdf';
      const marker = L.circleMarker([item.lat, item.lon], {{
        radius: isExact ? 7 : 5.5,
        color: isExact ? '#ffffff' : item.color,
        weight: isExact ? 2 : 1,
        fillColor: item.color,
        fillOpacity: isExact ? 0.92 : 0.52
      }});
      const links = [];
      if (item.digest_url) links.push(`<a href="${{item.digest_url}}"><strong>Ön Özeti Aç →</strong></a>`);
      if (item.portal_url) links.push(`<a href="${{item.portal_url}}" target="_blank" rel="noopener">e-ÇED ↗</a>`);
      const locNote = isExact ? 'Kesin PDF koordinatı' : 'Yaklaşık il merkezi';
      marker.bindPopup(
        `<strong>${{escHtml(item.province)}} / ${{escHtml(item.district)}}</strong><br/>` +
        `${{escHtml(item.title)}}<br/>` +
        `<span style="color:#667085">${{escHtml(item.stage)}} · ${{escHtml(item.annex)}} · ${{escHtml(item.date)}} · ${{locNote}}</span><br/>` +
        links.join(' · ')
      );
      marker.addTo(layerGroup);
      bounds.push([item.lat, item.lon]);
    }}
    if (prov.value && bounds.length > 0) {{
      map.fitBounds(bounds, {{ maxZoom: 10, padding: [30, 30] }});
    }} else if (!prov.value && !q.value.trim()) {{
      map.setView([39.0, 35.2], 6);
    }}
  }}

  function apply(resetPaging = false) {{
    if (resetPaging) pageLimit = PAGE_SIZE;
    const term = q.value.trim().toLowerCase();
    const selectedProv = prov.value;
    const selectedStage = stageSel.value;
    const matchedCards = [];
    const matchedSet = new Set();

    for (const c of cards) {{
      let ok = true;
      if (mode === 'active') ok = c.dataset.active === '1';
      else if (mode === 'digest') ok = c.dataset.digest === '1';
      else if (mode === 'ek1') ok = c.dataset.annex === 'Ek-1';
      else if (mode === 'rev') ok = c.dataset.rev === '1';
      if (ok && selectedProv) ok = c.dataset.province === selectedProv;
      if (ok && selectedStage) ok = c.dataset.stage === selectedStage;
      if (ok && term) ok = c.dataset.search.includes(term);
      if (ok) {{
        matchedCards.push(c);
        matchedSet.add(Number(c.dataset.idx));
      }}
      c.style.display = 'none';
    }}

    const shownNow = Math.min(matchedCards.length, pageLimit);
    for (let i = 0; i < shownNow; i++) {{
      matchedCards[i].style.display = '';
    }}

    const anyFilter = mode !== 'all' || Boolean(selectedProv) || Boolean(selectedStage) || Boolean(term);
    resetBtn.style.display = anyFilter ? '' : 'none';
    countEl.textContent = `${{matchedCards.length}} eşleşen duyuru (toplam ${{cards.length}})`;
    pageInfoEl.textContent = matchedCards.length > shownNow ? `${{shownNow}} / ${{matchedCards.length}} gösteriliyor` : '';
    if (matchedCards.length > shownNow) {{
      pagerEl.style.display = 'flex';
      const remaining = matchedCards.length - shownNow;
      loadMoreBtn.textContent = `${{Math.min(PAGE_SIZE, remaining)}} duyuru daha göster`;
    }} else {{
      pagerEl.style.display = 'none';
    }}
    syncUrl();
    renderMap(matchedSet);
  }}

  loadMoreBtn.addEventListener('click', () => {{
    pageLimit += PAGE_SIZE;
    apply(false);
  }});
  showAllBtn.addEventListener('click', () => {{
    pageLimit = cards.length;
    apply(false);
  }});
  shareBtn.addEventListener('click', async () => {{
    try {{
      await navigator.clipboard.writeText(window.location.href);
      shareBtn.textContent = 'Kopyalandı ✓';
      setTimeout(() => (shareBtn.textContent = 'Bağlantıyı Kopyala'), 2000);
    }} catch (e) {{
      shareBtn.textContent = 'Kopyalanamadı';
    }}
  }});
  pills.forEach(p => p.addEventListener('click', () => {{
    pills.forEach(x => x.classList.remove('active'));
    p.classList.add('active');
    mode = p.dataset.filter;
    apply(true);
  }}));
  resetBtn.addEventListener('click', () => {{
    q.value = '';
    prov.value = '';
    stageSel.value = '';
    mode = 'all';
    pills.forEach(x => x.classList.toggle('active', x.dataset.filter === 'all'));
    apply(true);
  }});
  q.addEventListener('input', () => apply(true));
  prov.addEventListener('change', () => apply(true));
  stageSel.addEventListener('change', () => apply(true));
  sortSel.addEventListener('change', () => {{
    sortCards();
    apply(true);
  }});
  sortCards();
  apply(false);
}})();
</script>
</body>
</html>
"""
    (docs_dir / "index.html").write_text(index_html, encoding="utf-8")
    (docs_dir / "rehber.html").write_text(render_guide_html(), encoding="utf-8")
    rss_xml = build_rss(shown_filings, digests_index, site_url)
    (docs_dir / "feed.xml").write_text(rss_xml, encoding="utf-8")

    return {
        "total": total,
        "provinces": len(provinces_present),
        "active": active_count,
        "digests_rendered": len(digests_index),
        "exact_geo": exact_geo_count,
        "audit_alerts": rev_alert_cards,
        "gis_verified": len(gis_by_fid),
        "gis_high_alerts": sum(1 for al in gis_alerts_by_fid.values() if any(a.get("severity") == "high" for a in al)),
        "revision_summary": rev_index["summary"],
        "index_path": str(docs_dir / "index.html"),
        "feed_path": str(docs_dir / "feed.xml"),
    }
