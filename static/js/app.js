// FIR Selector — map + sidebar wiring.

const PALETTE = [
  "#EF4444", "#F97316", "#F59E0B", "#EAB308",
  "#84CC16", "#22C55E", "#10B981", "#14B8A6",
  "#06B6D4", "#0EA5E9", "#3B82F6", "#6366F1",
  "#8B5CF6", "#A855F7", "#D946EF", "#EC4899",
];

const DEFAULT_EDGE = "#4A5568";

const state = {
  activeColor: PALETTE[10],       // color applied on next click
  background: "#1C242B",
  selections: new Map(),          // fir id -> color
  features: new Map(),            // fir id -> {name, icao, layer}
  filterText: "",
};

// ── Map setup ────────────────────────────────────────────────────────────

const map = L.map("map", {
  center: [20, 10],
  zoom: 3,
  minZoom: 2,
  maxZoom: 8,
  // A single, clamped world copy — with worldCopyJump the FIR overlay only
  // ever exists in the original copy, so panning into a repeated copy (e.g.
  // scrolling left past the edge to reach Australia) shows tiles that look
  // right but sit over no clickable geometry at all. Capping the bounds
  // means there's never a non-functional copy to scroll into.
  worldCopyJump: false,
  maxBounds: [[-90, -180], [90, 180]],
  maxBoundsViscosity: 1.0,
  preferCanvas: true,
  attributionControl: false, // re-added bottom-left below, freeing bottom-right for the logo control
});

L.control.attribution({ position: "bottomleft" }).addTo(map);

const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

const darkTiles = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: TILE_ATTRIBUTION,
  subdomains: "abcd",
  maxZoom: 19,
});

const lightTiles = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: TILE_ATTRIBUTION,
  subdomains: "abcd",
  maxZoom: 19,
});

darkTiles.addTo(map);

function hexIsDark(hex) {
  const c = hex.replace("#", "");
  const r = parseInt(c.substr(0, 2), 16) / 255;
  const g = parseInt(c.substr(2, 2), 16) / 255;
  const b = parseInt(c.substr(4, 2), 16) / 255;
  const l = (Math.max(r, g, b) + Math.min(r, g, b)) / 2;
  return l < 0.5;
}

function applyMapTheme(bgColor) {
  const wanted = hexIsDark(bgColor) ? darkTiles : lightTiles;
  const other = wanted === darkTiles ? lightTiles : darkTiles;
  if (map.hasLayer(other)) map.removeLayer(other);
  if (!map.hasLayer(wanted)) wanted.addTo(map);
}

const renderer = L.canvas({ padding: 0.4 });
let geoLayer = null;

function baseStyle() {
  return { color: DEFAULT_EDGE, weight: 0.6, opacity: 0.55, fillOpacity: 0 };
}

function selectedStyle(color) {
  return { color, weight: 1.6, opacity: 0.95, fillColor: color, fillOpacity: 0.22 };
}

function styleFor(id) {
  return state.selections.has(id) ? selectedStyle(state.selections.get(id)) : baseStyle();
}

function restyle(id) {
  const f = state.features.get(id);
  if (f && f.layer) f.layer.setStyle(styleFor(id));
}

// ── Load FIR polygons ───────────────────────────────────────────────────

fetch("/api/firs")
  .then((r) => r.json())
  .then((geojson) => {
    geoLayer = L.geoJSON(geojson, {
      renderer,
      style: (feature) => styleFor(feature.properties.id),
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        state.features.set(p.id, { name: p.volumeName, icao: p.icaoID, layer });

        layer.bindTooltip(
          `${p.volumeName}${p.icaoID ? `<span class="icao"> ${p.icaoID}</span>` : ""}`,
          { className: "fir-tooltip", sticky: true }
        );

        layer.on("click", () => toggleSelection(p.id));
        layer.on("mouseover", () => layer.setStyle({ weight: state.selections.has(p.id) ? 2.4 : 1.4 }));
        layer.on("mouseout", () => restyle(p.id));
      },
    }).addTo(map);

    document.getElementById("firCount").textContent = `(${state.features.size})`;
    renderList();
  })
  .catch((err) => {
    console.error("Failed to load FIR data", err);
    document.getElementById("firList").textContent = "Failed to load FIR data.";
  });

// ── Selection logic ─────────────────────────────────────────────────────

function toggleSelection(id) {
  if (state.selections.has(id)) {
    state.selections.delete(id);
  } else {
    state.selections.set(id, state.activeColor);
  }
  restyle(id);
  renderRowState(id);
  updateFooter();
}

function setSelectionColor(id, color) {
  state.selections.set(id, color);
  restyle(id);
  renderRowState(id);
}

function clearAll() {
  const ids = [...state.selections.keys()];
  state.selections.clear();
  ids.forEach((id) => {
    restyle(id);
    renderRowState(id);
  });
  updateFooter();
}

function selectAllFiltered() {
  const ids = filteredIds();
  ids.forEach((id) => {
    state.selections.set(id, state.activeColor);
    restyle(id);
    renderRowState(id);
  });
  updateFooter();
}

function updateFooter() {
  const n = state.selections.size;
  document.getElementById("selectedCount").textContent = `${n} selected`;
  document.getElementById("exportBtn").disabled = n === 0;
}

// ── Sidebar: palette ─────────────────────────────────────────────────────

const paletteEl = document.getElementById("palette");
PALETTE.forEach((color) => {
  const btn = document.createElement("button");
  btn.style.background = color;
  btn.dataset.color = color;
  btn.title = color;
  if (color === state.activeColor) btn.classList.add("active");
  btn.addEventListener("click", () => setActiveColor(color));
  paletteEl.appendChild(btn);
});

const customColorInput = document.getElementById("customColor");
customColorInput.addEventListener("input", (e) => setActiveColor(e.target.value.toUpperCase(), true));

function setActiveColor(color, fromCustom = false) {
  state.activeColor = color;
  document.getElementById("activeColorSwatch").style.background = color;
  [...paletteEl.children].forEach((b) => b.classList.toggle("active", b.dataset.color === color));
  if (!fromCustom) customColorInput.value = color;
}
setActiveColor(state.activeColor);

// ── Sidebar: background ──────────────────────────────────────────────────

const bgButtons = document.querySelectorAll(".bg-chip");
const customBgInput = document.getElementById("customBg");

function setBackground(color) {
  state.background = color;
  bgButtons.forEach((b) => b.classList.toggle("active", b.dataset.bg === color));
  customBgInput.value = color;
  map.getContainer().style.background = color;
  applyMapTheme(color);
  updateLogoPreview();
}
bgButtons.forEach((b) => b.addEventListener("click", () => setBackground(b.dataset.bg)));
customBgInput.addEventListener("input", (e) => setBackground(e.target.value.toUpperCase()));

// ── Sidebar: logo ────────────────────────────────────────────────────────

state.includeLogo = false;

const includeLogoCheckbox = document.getElementById("includeLogo");
const logoPreviewSwatch = document.getElementById("logoPreviewSwatch");
const logoPreviewImg = document.getElementById("logoPreview");

function updateLogoPreview() {
  logoPreviewImg.src = hexIsDark(state.background)
    ? "/static/img/aireon_logo_white.png"
    : "/static/img/aireon_logo_dark.png";
  logoPreviewSwatch.style.background = state.background;
  logoPreviewSwatch.hidden = !state.includeLogo;
}

includeLogoCheckbox.addEventListener("change", (e) => {
  state.includeLogo = e.target.checked;
  updateLogoPreview();
});

setBackground(state.background);

// ── Sidebar: FIR list ─────────────────────────────────────────────────────

const firListEl = document.getElementById("firList");
const searchBox = document.getElementById("searchBox");

function filteredIds() {
  const q = state.filterText.trim().toLowerCase();
  const ids = [...state.features.keys()];
  if (!q) return ids;
  return ids.filter((id) => {
    const f = state.features.get(id);
    return f.name.toLowerCase().includes(q) || (f.icao && f.icao.toLowerCase().includes(q));
  });
}

function renderList() {
  const ids = filteredIds().sort((a, b) =>
    state.features.get(a).name.localeCompare(state.features.get(b).name)
  );

  firListEl.innerHTML = "";
  const frag = document.createDocumentFragment();

  ids.forEach((id) => {
    const f = state.features.get(id);
    const row = document.createElement("div");
    row.className = "fir-row";
    row.dataset.id = id;

    const dot = document.createElement("span");
    dot.className = "dot";

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = f.name;

    const icao = document.createElement("span");
    icao.className = "icao";
    icao.textContent = f.icao || "";

    const remove = document.createElement("button");
    remove.className = "remove";
    remove.textContent = "×";
    remove.title = "Remove";
    remove.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.selections.has(id)) toggleSelection(id);
    });

    row.append(dot, name, icao, remove);
    row.addEventListener("click", () => {
      toggleSelection(id);
      focusFeature(id);
    });

    applyRowState(row, id);
    frag.appendChild(row);
  });

  firListEl.appendChild(frag);
}

function applyRowState(row, id) {
  const selected = state.selections.has(id);
  row.classList.toggle("selected", selected);
  row.querySelector(".dot").style.background = selected ? state.selections.get(id) : "transparent";
}

function renderRowState(id) {
  const row = firListEl.querySelector(`.fir-row[data-id="${CSS.escape(id)}"]`);
  if (row) applyRowState(row, id);
}

function focusFeature(id) {
  const f = state.features.get(id);
  if (f && f.layer && f.layer.getBounds) {
    map.fitBounds(f.layer.getBounds(), { maxZoom: 6, padding: [40, 40] });
  }
}

let searchDebounce;
searchBox.addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    state.filterText = e.target.value;
    renderList();
  }, 120);
});

document.getElementById("selectAllBtn").addEventListener("click", selectAllFiltered);
document.getElementById("clearBtn").addEventListener("click", clearAll);

// ── Sidebar: lists ───────────────────────────────────────────────────────

const listSelect = document.getElementById("listSelect");
state.lists = {};

fetch("/api/lists")
  .then((r) => r.json())
  .then((lists) => {
    state.lists = lists;
    Object.keys(lists).sort().forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      listSelect.appendChild(opt);
    });
  })
  .catch((err) => console.error("Failed to load lists", err));

listSelect.addEventListener("change", (e) => {
  const listName = e.target.value;
  listSelect.value = ""; // reset to placeholder immediately — this is a one-shot action, not a persistent filter
  if (!listName || !state.lists[listName]) return;

  const nameToId = new Map();
  state.features.forEach((f, id) => nameToId.set(f.name.toUpperCase(), id));

  const missing = [];
  state.lists[listName].forEach((wantedName) => {
    const id = nameToId.get(wantedName.toUpperCase());
    if (!id) {
      missing.push(wantedName);
      return;
    }
    state.selections.set(id, state.activeColor);
    restyle(id);
    renderRowState(id);
  });

  if (missing.length) {
    console.warn(`List "${listName}": no FIR found matching`, missing);
  }
  updateFooter();
});

// ── Export ────────────────────────────────────────────────────────────────

const exportBtn = document.getElementById("exportBtn");
const overlay = document.getElementById("loadingOverlay");

exportBtn.addEventListener("click", async () => {
  if (state.selections.size === 0) return;
  overlay.classList.remove("hidden");
  exportBtn.disabled = true;

  try {
    const body = {
      selections: Object.fromEntries(state.selections),
      background: state.background,
      include_logo: state.includeLogo,
    };
    const resp = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`Render failed: ${resp.status}`);

    const disposition = resp.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "fir_map.png";

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error(err);
    alert("Export failed. Check the server console for details.");
  } finally {
    overlay.classList.add("hidden");
    exportBtn.disabled = state.selections.size === 0;
  }
});

updateFooter();
