const TAIPEI_BOUNDS = [
  [24.95, 121.45],
  [25.22, 121.67],
];

// Initialize Leaflet Map
const map = L.map("map", {
  maxBounds: TAIPEI_BOUNDS,
  maxBoundsViscosity: 0.9,
}).setView([25.0478, 121.5319], 12);

// Standard Light Theme Tile Layer
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap",
}).addTo(map);

// Define Layer Groups
const routeLayer = L.layerGroup().addTo(map);
const markerLayer = L.layerGroup().addTo(map);
const boundaryLayer = L.layerGroup().addTo(map);
const mrtLayer = L.layerGroup().addTo(map);
const trainLayer = L.layerGroup().addTo(map);
const busLayer = L.layerGroup().addTo(map);

// Colors for rank 1, 2, 3 paths
const colors = ["#0284c7", "#f59e0b", "#10b981"]; // Premium Light Blue, Gold, Emerald Green

// Store boundary locally
let taipeiBoundaryCoords = null;

// Initialize page
bindEvents();
loadTaipeiBoundary();
addMapLegend();

function bindEvents() {
  document.getElementById("recommend-btn").addEventListener("click", recommend);
  document.getElementById("origin-search").addEventListener("click", () => searchAddress("origin"));
  document.getElementById("destination-search").addEventListener("click", () => searchAddress("destination"));
  document.getElementById("origin-results").addEventListener("change", () => chooseResult("origin"));
  document.getElementById("destination-results").addEventListener("change", () => chooseResult("destination"));
  document.getElementById("private-weight").addEventListener("change", togglePrivateWeight);
  
  // Hidden layers still bind internally to prevent script crashes
  document.getElementById("toggle-mrt").addEventListener("change", toggleStations);
  document.getElementById("toggle-train").addEventListener("change", toggleStations);
  document.getElementById("toggle-bus").addEventListener("change", toggleStations);
  
  // Clear hidden coordinates and route geometry on map when starting to type new inputs
  document.getElementById("origin-address").addEventListener("input", (e) => {
    document.getElementById("origin").value = "";
    clearRoutingResults();
    if (!e.target.value.trim()) {
      markerLayer.clearLayers();
      drawSelectedMarkers();
    }
  });
  document.getElementById("destination-address").addEventListener("input", (e) => {
    document.getElementById("destination").value = "";
    clearRoutingResults();
    if (!e.target.value.trim()) {
      markerLayer.clearLayers();
      drawSelectedMarkers();
    }
  });
  
  map.on("click", fillPointFromMap);
}

// Fetch Taipei City boundary shapefile coordinates from backend for mask & checks
async function loadTaipeiBoundary() {
  try {
    const res = await fetch("/api/taipei-boundary");
    if (res.ok) {
      taipeiBoundaryCoords = await res.json();
      addTaipeiMaskAndBoundary();
    }
  } catch (e) {
    console.error("Failed to load Taipei boundary", e);
    addApproximateMask();
  }
}

function addTaipeiMaskAndBoundary() {
  boundaryLayer.clearLayers();
  if (!taipeiBoundaryCoords || !taipeiBoundaryCoords.exterior) {
    addApproximateMask();
    return;
  }
  
  const outer = [[90, -180], [90, 180], [-90, 180], [-90, -180]];
  const inner = taipeiBoundaryCoords.exterior;
  
  // 1. Draw inverse mask (world box with Taipei exterior as hole)
  L.polygon([outer, inner], {
    color: "none",
    fillColor: "#e0f2fe",
    fillOpacity: 0.55,
    interactive: false,
  }).addTo(boundaryLayer);
  
  // 2. Draw red dotted boundary line
  L.polygon(inner, {
    color: "#ef4444",
    dashArray: "6 6",
    fillOpacity: 0,
    weight: 2,
    interactive: false,
  }).addTo(boundaryLayer);
  
  // Strict bounding box setting
  const bounds = L.latLngBounds(inner);
  map.setMaxBounds(bounds);
  map.fitBounds(bounds);
}

function addApproximateMask() {
  boundaryLayer.clearLayers();
  const outer = [[90, -180], [90, 180], [-90, 180], [-90, -180]];
  const inner = [
    [TAIPEI_BOUNDS[0][0], TAIPEI_BOUNDS[0][1]],
    [TAIPEI_BOUNDS[0][0], TAIPEI_BOUNDS[1][1]],
    [TAIPEI_BOUNDS[1][0], TAIPEI_BOUNDS[1][1]],
    [TAIPEI_BOUNDS[1][0], TAIPEI_BOUNDS[0][1]],
  ];
  L.polygon([outer, inner], {
    color: "#0369a1",
    weight: 1.5,
    fillColor: "#e0f2fe",
    fillOpacity: 0.55,
    interactive: false,
  }).addTo(boundaryLayer);
}

// Ray-casting point-in-polygon algorithm to check if a point is inside Taipei City boundary
function isPointInPolygon(point, polygon) {
  const x = point[0], y = point[1];
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];
    const intersect = ((yi > y) !== (yj > y))
      && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function fillPointFromMap(event) {
  const lat = event.latlng.lat;
  const lon = event.latlng.lng;
  
  // Restrict clicking outside Taipei county boundary shapefile
  if (taipeiBoundaryCoords && taipeiBoundaryCoords.exterior) {
    if (!isPointInPolygon([lat, lon], taipeiBoundaryCoords.exterior)) {
      alert("超出範圍！您點選的位置位於臺北市境外。");
      setStatus("⚠️ 請點選臺北市範圍內的位置。");
      return;
    }
  } else if (!insideTaipei(lat, lon)) {
    setStatus("⚠️ 請選擇臺北市範圍內的位置。");
    return;
  }
  
  const originVal = document.getElementById("origin-address").value.trim();
  const target = !originVal ? "origin" : "destination";
  setPoint(target, lat, lon, `地圖點選位點 (${lat.toFixed(4)}, ${lon.toFixed(4)})`);
}

async function searchAddress(kind) {
  const address = document.getElementById(`${kind}-address`).value.trim();
  if (!address) {
    setStatus("⚠️ 請先輸入地址或地標。");
    return;
  }
  setStatus("🔍 正在搜尋位置...");
  try {
    const results = await geocode(address);
    renderSearchResults(kind, results);
    setStatus(results.length ? "請在下拉選單中選擇正確的位置。" : "❌ 找不到臺北市內符合的位置。");
  } catch (err) {
    setStatus(`發生錯誤: ${err.message}`);
  }
}

async function geocode(address) {
  const response = await fetch(`/geocode?q=${encodeURIComponent(address)}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function renderSearchResults(kind, results) {
  const select = document.getElementById(`${kind}-results`);
  select.innerHTML = "";
  
  if (results.length === 0) {
    select.hidden = true;
    return;
  }
  
  results.forEach((item) => {
    const option = document.createElement("option");
    option.value = JSON.stringify(item);
    option.textContent = item.label;
    select.appendChild(option);
  });
  
  select.hidden = false;
  chooseResult(kind);
}

function chooseResult(kind) {
  const select = document.getElementById(`${kind}-results`);
  if (!select.value) return;
  const item = JSON.parse(select.value);
  
  // Restrict choosing search results outside Taipei City boundary shapefile
  if (taipeiBoundaryCoords && taipeiBoundaryCoords.exterior) {
    if (!isPointInPolygon([item.lat, item.lon], taipeiBoundaryCoords.exterior)) {
      alert("超出範圍！您搜尋的位置位於臺北市境外，請重新輸入。");
      setStatus("⚠️ 搜尋位置超出臺北市範圍！");
      return;
    }
  } else if (!insideTaipei(item.lat, item.lon)) {
    setStatus("⚠️ 搜尋位置超出臺北市範圍！");
    return;
  }
  
  setPoint(kind, item.lat, item.lon, item.label);
}

function setPoint(kind, lat, lon, label) {
  document.getElementById(kind).value = `${Number(lat).toFixed(6)},${Number(lon).toFixed(6)}`;
  document.getElementById(`${kind}-address`).value = label;
  
  // Clean all previous routing layers & results panel for initialization
  clearRoutingResults();
  
  markerLayer.clearLayers();
  drawSelectedMarkers();
}

function clearRoutingResults() {
  routeLayer.clearLayers();
  mrtLayer.clearLayers();
  trainLayer.clearLayers();
  busLayer.clearLayers();
  
  const routesContainer = document.getElementById("routes");
  if (routesContainer) {
    routesContainer.innerHTML = "";
  }
  
  const reasoningContainer = document.getElementById("reasoning-container");
  if (reasoningContainer) {
    reasoningContainer.hidden = true;
    document.getElementById("reasoning").textContent = "";
  }
  
  const weatherBox = document.getElementById("weather-badge");
  if (weatherBox) {
    weatherBox.textContent = "氣象監測就緒";
  }
  
  const statusBox = document.getElementById("status");
  if (statusBox) {
    statusBox.textContent = "";
  }
}

function drawSelectedMarkers() {
  ["origin", "destination"].forEach((kind) => {
    const point = parsePoint(document.getElementById(kind).value);
    if (!point) return;
    const color = kind === "origin" ? "green" : "red";
    const label = kind === "origin" ? "🟢 起點" : "🔴 終點";
    
    L.marker(point, {
      title: label,
      icon: L.divIcon({
        className: 'custom-div-icon',
        html: `<div style="background-color: ${color}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.4)"></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7]
      })
    })
    // 起終點標記也同步加入浮現提示 (bindTooltip)
    .bindTooltip(label, { permanent: false, direction: 'top', offset: [0, -8] })
    .bindPopup(label)
    .addTo(markerLayer);
  });
}

function toggleStations() {
  // Legacy toggle logic left intact for DOM event binding, actual station layers are automated
}

async function recommend() {
  const button = document.getElementById("recommend-btn");
  setLoading(button, true);
  try {
    await ensureAddressResolved("origin");
    await ensureAddressResolved("destination");
    const payload = formPayload();
    if (!pointsInsideTaipei(payload)) throw new Error("起點與終點都必須在臺北市範圍內。");
    
    const response = await fetch("/recommend", requestOptions(payload));
    if (!response.ok) throw new Error(await response.text());
    
    renderResult(await response.json());
    setStatus("🎉 規劃完成！");
  } catch (error) {
    setStatus(`發生錯誤：${error.message}`);
  } finally {
    setLoading(button, false);
  }
}

async function ensureAddressResolved(kind) {
  if (document.getElementById(kind).value) return;
  const results = await geocode(document.getElementById(`${kind}-address`).value.trim());
  if (!results.length) throw new Error(`${kind === "origin" ? "起點" : "終點"}找不到臺北市內符合之地址。`);
  
  const item = results[0];
  if (taipeiBoundaryCoords && taipeiBoundaryCoords.exterior) {
    if (!isPointInPolygon([item.lat, item.lon], taipeiBoundaryCoords.exterior)) {
      alert("超出範圍！您搜尋的位置位於臺北市境外，請重新輸入。"); // Popup warning
      throw new Error(`${kind === "origin" ? "起點" : "終點"}的位置位於臺北市境外，請輸入臺北市區。`);
    }
  }
  
  setPoint(kind, item.lat, item.lon, item.label);
}

function requestOptions(payload) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

function formPayload() {
  return {
    origin: valueOf("origin"),
    destination: valueOf("destination"),
    gender: valueOf("gender"),
    age: Number(valueOf("age")),
    weight: selectedWeight(),
    vehicles: checkedVehicles(),
    complaint: valueOf("complaint"),
  };
}

function selectedWeight() {
  if (document.getElementById("private-weight").checked) return 60;
  const weight = Number(valueOf("weight"));
  return Number.isFinite(weight) && weight > 0 ? weight : 60;
}

function togglePrivateWeight() {
  const input = document.getElementById("weight");
  input.disabled = document.getElementById("private-weight").checked;
  if (input.disabled) input.value = 60;
}

function checkedVehicles() {
  return Array.from(document.querySelectorAll('input[name="vehicles"]:checked')).map((input) => input.value);
}

function pointsInsideTaipei(payload) {
  const origin = parsePoint(payload.origin);
  const destination = parsePoint(payload.destination);
  
  if (taipeiBoundaryCoords && taipeiBoundaryCoords.exterior) {
    return origin && destination 
      && isPointInPolygon(origin, taipeiBoundaryCoords.exterior) 
      && isPointInPolygon(destination, taipeiBoundaryCoords.exterior);
  }
  
  return origin && destination && insideTaipei(origin[0], origin[1]) && insideTaipei(destination[0], destination[1]);
}

function parsePoint(value) {
  const parts = value.split(",").map(Number);
  if (parts.length !== 2 || parts.some((part) => !Number.isFinite(part))) return null;
  return parts;
}

function insideTaipei(lat, lon) {
  return lat >= TAIPEI_BOUNDS[0][0] && lat <= TAIPEI_BOUNDS[1][0]
    && lon >= TAIPEI_BOUNDS[0][1] && lon <= TAIPEI_BOUNDS[1][1];
}

function valueOf(id) {
  return document.getElementById(id).value.trim();
}

function setStatus(message) {
  document.getElementById("status").textContent = message;
}

function setLoading(button, loading) {
  button.disabled = loading;
  button.textContent = loading ? "推薦中..." : "🚀 開始路線推薦";
  if (loading) setStatus("💬 正在理解需求並計算黃金路線...");
}

function renderResult(data) {
  routeLayer.clearLayers();
  mrtLayer.clearLayers();
  trainLayer.clearLayers();
  busLayer.clearLayers();
  
  // Show reasoning
  const container = document.getElementById("reasoning-container");
  container.hidden = !data.reasoning;
  document.getElementById("reasoning").textContent = data.reasoning || "";
  
  // Update weather badge - displays district weather for BOTH origin and destination
  const weatherBox = document.getElementById("weather-badge");
  if (data.weather && data.weather.origin && data.weather.destination) {
    const wo = data.weather.origin;
    const wd = data.weather.destination;
    
    weatherBox.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:4px; font-size:12.5px; text-align:left;">
        <div>🟢 <b>起點 (${wo.district})</b>: ${wo.temperature ? wo.temperature.toFixed(1) : '--'}°C | 🌦️ ${wo.weather_desc || '未知'} | ☔ 降雨率 ${wo.rain_probability ? wo.rain_probability.toFixed(0) : '0'}% | 😷 AQI ${wo.aqi ? wo.aqi.toFixed(0) : '--'}</div>
        <div>🔴 <b>終點 (${wd.district})</b>: ${wd.temperature ? wd.temperature.toFixed(1) : '--'}°C | 🌦️ ${wd.weather_desc || '未知'} | ☔ 降雨率 ${wd.rain_probability ? wd.rain_probability.toFixed(0) : '0'}% | 😷 AQI ${wd.aqi ? wd.aqi.toFixed(0) : '--'}</div>
        ${wo.extreme_weather_alert !== "正常" ? `<div style="color:#ef4444; font-weight:700; margin-top:2px;">⚠️ 災害警報: ${wo.extreme_weather_alert}</div>` : ''}
      </div>
    `;
  } else {
    weatherBox.textContent = "氣象監測就緒";
  }

  // Draw routes
  const routes = document.getElementById("routes");
  routes.innerHTML = "";
  const bounds = [];
  
  data.routes.forEach((route, index) => {
    renderRoute(route, index, routes, bounds);
    
    // Draw specific boarding and alighting stations for transit routes on the map
    if (route.board_station) {
      drawRouteStation(route.board_station, "board", route.vehicle);
    }
    if (route.alight_station) {
      drawRouteStation(route.alight_station, "alight", route.vehicle);
    }
  });
  
  // Ensure the relevant transit station layers are automatically active
  if (!map.hasLayer(mrtLayer)) map.addLayer(mrtLayer);
  if (!map.hasLayer(trainLayer)) map.addLayer(trainLayer);
  if (!map.hasLayer(busLayer)) map.addLayer(busLayer);
  
  if (bounds.length) {
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

function renderRoute(route, index, container, bounds) {
  const color = colors[index % colors.length];
  const latLngs = route.coordinates.map((point) => [point[0], point[1]]);
  
  // Draw polyline
  L.polyline(latLngs, { color, weight: 6, opacity: 0.85 }).addTo(routeLayer);
  latLngs.forEach((point) => bounds.push(point));
  
  container.insertAdjacentHTML("beforeend", routeCard(route, color, index + 1));
}

// 核心修改處：將 bindPopup 改為 bindTooltip，使滑鼠懸停（Hover）時站點名稱自動浮現！
function drawRouteStation(st, type, vehicle) {
  const iconHtml = type === "board" 
    ? '<div class="station-marker board-marker">🚇</div>' 
    : '<div class="station-marker alight-marker">🛑</div>';
    
  const stationLabel = type === "board"
    ? `🟢 乘車站點 (${vehicleLabel(vehicle)})：${st.name}`
    : `🔴 下車站點 (${vehicleLabel(vehicle)})：${st.name}`;
    
  const marker = L.marker([st.lat, st.lon], {
    icon: L.divIcon({
      className: "transit-station-icon",
      html: iconHtml,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    })
  })
  // 1. 滑鼠移上去時自動浮現站名提示框
  .bindTooltip(stationLabel, {
    permanent: false, // 設為 false：滑鼠移上去自動浮現；若想直接固定顯示在畫面上可改為 true
    direction: 'top',
    offset: [0, -12],
    opacity: 0.95
  })
  // 2. 點擊時依然保留詳細氣泡視窗
  .bindPopup(`<b>${stationLabel}</b>`);
  
  if (vehicle === "mrt") {
    marker.addTo(mrtLayer);
  } else if (vehicle === "train") {
    marker.addTo(trainLayer);
  } else if (vehicle === "bus") {
    marker.addTo(busLayer);
  }
}

function routeCard(route, color, rank) {
  return `
    <article class="route-card" style="border-left: 6px solid ${color}">
      <div class="route-title">
        <span>第 ${rank} 推薦 ｜ ${vehicleLabel(route.vehicle)}</span>
        <span class="route-duration">${route.time_minutes} 分鐘</span>
      </div>
      <div class="route-details">
        <div class="route-detail-row">
          <span class="detail-label">預計耗時</span>
          <span class="detail-val">${route.time_minutes} 分鐘</span>
        </div>
        <div class="route-detail-row">
          <span class="detail-label">估算費用</span>
          <span class="detail-val">${route.fare} 元</span>
        </div>
        <div class="route-detail-row">
          <span class="detail-label">路線長度</span>
          <span class="detail-val">${(route.distance_meters / 1000).toFixed(2)} 公里</span>
        </div>
        ${route.board_station ? `
        <div class="route-detail-row" style="margin-top:4px; font-size:12px; color:#10b981;">
          <span>🟢 乘車：${route.board_station.name}</span>
        </div>
        ` : ''}
        ${route.alight_station ? `
        <div class="route-detail-row" style="font-size:12px; color:#ef4444;">
          <span>🔴 下車：${route.alight_station.name}</span>
        </div>
        ` : ''}
      </div>
    </article>
  `;
}

function vehicleLabel(vehicle) {
  const labels = {
    walking: "🚶 步行",
    mrt: "🚇 捷運",
    bus: "🚌 公車",
    train: "🚂 台鐵",
    ubike: "🚲 YouBike",
    taxi: "🚖 計程車",
    car: "🚗 汽車",
    scooter: "🛵 機車",
  };
  return labels[vehicle] || vehicle;
}

// Add map legend to bottom right corner
function addMapLegend() {
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = function () {
    const div = L.DomUtil.create("div", "map-legend");
    div.innerHTML = `
      <h4>🗺️ 地圖圖例</h4>
      <div class="legend-item"><div class="legend-line" style="background:#0284c7;"></div> 第一推薦路線</div>
      <div class="legend-item"><div class="legend-line" style="background:#f59e0b;"></div> 第二推薦路線</div>
      <div class="legend-item"><div class="legend-line" style="background:#10b981;"></div> 第三推薦路線</div>
      <div class="legend-item"><div class="legend-icon">🟢</div> 起點位置</div>
      <div class="legend-item"><div class="legend-icon">🔴</div> 終點位置</div>
      <div class="legend-item"><div class="legend-icon"><div class="station-marker board-marker" style="width:12px; height:12px; font-size:7px; border-width:1.5px;">🚇</div></div> 路線乘車站點</div>
      <div class="legend-item"><div class="legend-icon"><div class="station-marker alight-marker" style="width:12px; height:12px; font-size:7px; border-width:1.5px;">🛑</div></div> 路線下車站點</div>
    `;
    return div;
  };
  legend.addTo(map);
}
