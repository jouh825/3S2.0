import os
import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import Point, Polygon

from backend.config import get_settings
from backend.routing.graph import build_graphs
from backend.routing.routing import RouteRequestData, recommend_routes, parse_place
from backend.ai.gemini import get_gemini_weights
from backend.api.weather import fetch_district_weather_snapshot, WeatherSnapshot
from backend.utils.gis_helper import get_all_stations, get_taipei_boundary_coords, get_district_by_coords

# Set page config
st.set_page_config(
    page_title="臺北市大眾運輸同理心路線推薦系統",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Alice Blue & Glassmorphism Styling
st.markdown(
    """
    <style>
    .stApp {
        background-color: #f4f9fd;
    }
    .main-title {
        color: #0284c7;
        font-family: 'Outfit', 'Inter', sans-serif;
        font-weight: 700;
        font-size: 2.2rem;
        margin-bottom: 5px;
    }
    .sub-title {
        color: #64748b;
        font-size: 1.1rem;
        margin-bottom: 25px;
    }
    .glass-card {
        background: rgba(255, 255, 255, 0.85);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.4);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 4px 12px rgba(2, 132, 199, 0.05);
    }
    .route-card {
        border-left: 6px solid #0284c7;
        background: rgba(255, 255, 255, 0.9);
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 12px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
    }
    .badge-weather {
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
        margin-right: 8px;
    }
    .badge-aqi {
        background-color: #fef3c7;
        color: #b45309;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =====================================================================
# ⚡️ 【效能優化區：Streamlit 記憶體快取】 (Server Warmup Cache)
# =====================================================================
@st.cache_resource
def load_cached_networks():
    """Load cached road/transit network graphs and prebuild routing tables once."""
    st.write("🔧 正在初始化臺北市路網圖資並預建路由表 (僅在首次啟動時執行)...")
    return build_graphs()

@st.cache_resource
def load_cached_gis():
    """Load shapefiles for stations and city boundary boundaries once."""
    stations = get_all_stations()
    boundary = get_taipei_boundary_coords()
    return stations, boundary
# =====================================================================

# Trigger startup resource loading
graphs = load_cached_networks()
stations, boundary = load_cached_gis()

# Address Geocoder using OSM Nominatim
def geocode_address(address: str) -> tuple[float, float, str] | None:
    query = address if any(k in address for k in ["台北", "臺北"]) else f"台北市 {address}"
    params = {"q": query, "format": "json", "limit": 1, "accept-language": "zh-TW"}
    headers = {"User-Agent": "empathetic-route-recommendation-streamlit/1.0"}
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers, timeout=8)
        if r.status_code == 200:
            records = r.json()
            if records:
                return float(records[0]["lat"]), float(records[0]["lon"]), records[0]["display_name"]
    except Exception as e:
        st.error(f"地標解析失敗: {e}")
    return None

# Check boundary inclusion
def is_point_in_taipei(lat: float, lon: float, boundary_coords: dict) -> bool:
    if not boundary_coords or not boundary_coords.get("exterior"):
        # Fallback bounding box
        return 24.95 <= lat <= 25.22 and 121.45 <= lon <= 121.67
    poly = Polygon([(c[1], c[0]) for c in boundary_coords["exterior"]])
    return poly.contains(Point(lon, lat))

# Helper to map vehicle keys
VEHICLE_MAP = {
    "捷運 (MRT)": "mrt",
    "火車 (Train)": "train",
    "公車 (Bus)": "bus",
    "YouBike": "ubike",
    "汽車 (Car)": "car",
    "機車 (Scooter)": "scooter",
    "計程車 (Taxi)": "taxi",
    "步行 (Walk)": "walking"
}

# Sidebar inputs
st.sidebar.markdown("### 📋 使用者輸入與偏好表單")

origin_addr = st.sidebar.text_input("起點位置 (Origin)", value="台北車站", placeholder="請輸入起點地址或地標")
dest_addr = st.sidebar.text_input("終點位置 (Destination)", value="台北101", placeholder="請輸入終點地址或地標")

st.sidebar.markdown("---")
st.sidebar.markdown("### 👤 個人身分屬性 (安全與票價計算)")
age = st.sidebar.slider("年齡 (Age)", min_value=0, max_value=110, value=30)
gender = st.sidebar.selectbox("性別 (Gender)", options=["男性", "女性", "其他"], index=0)
weight = st.sidebar.slider("體重 (Weight - kg)", min_value=30, max_value=150, value=60)

st.sidebar.markdown("---")
st.sidebar.markdown("### 💡 心情與出行場景 (AI 智能語意分析)")
mood_text = st.sidebar.text_area(
    "輸入您的出行偏好 / 心情需求",
    value="外面天氣很熱，我背著沉重的行李，想坐得舒服一點，不想走太多路，有冷氣最好。",
    placeholder="例如：我剛下班很累，希望快速回家。或是：今天天氣很好，我想做點有氧運動健行。"
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚗 交通工具選擇")
selected_vehicles = st.sidebar.multiselect(
    "選擇可接受的移動工具",
    options=list(VEHICLE_MAP.keys()),
    default=["捷運 (MRT)", "公車 (Bus)", "YouBike", "步行 (Walk)"]
)

backend_vehicles = [VEHICLE_MAP[v] for v in selected_vehicles]

# Layout header
st.markdown("<div class='main-title'>臺北市大眾運輸同理心路線推薦系統</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-title'>整合 AI 心情偏好權重、即時鄉鎮市區氣象與 AQI、OSMnx 多向性軌道路網及票價補貼計算</div>", unsafe_allow_html=True)

# Recommendation Execution
if st.sidebar.button("🚗 開始規劃路線", type="primary"):
    if not origin_addr.strip() or not dest_addr.strip():
        st.error("⚠️ 起點與終點位置不能為空！")
    elif not backend_vehicles:
        st.error("⚠️ 請至少勾選一種交通工具！")
    else:
        with st.spinner("🔍 正在定位並規劃路徑，請稍候..."):
            # 1. Geocode locations
            orig_res = geocode_address(origin_addr)
            dest_res = geocode_address(dest_addr)
            
            if not orig_res:
                st.error(f"❌ 無法解析起點位置: {origin_addr}")
            elif not dest_res:
                st.error(f"❌ 無法解析終點位置: {dest_addr}")
            else:
                orig_lat, orig_lon, orig_name = orig_res
                dest_lat, dest_lon, dest_name = dest_res
                
                # 2. Check Taipei bounds inclusion
                orig_in = is_point_in_taipei(orig_lat, orig_lon, boundary)
                dest_in = is_point_in_taipei(dest_lat, dest_lon, boundary)
                
                if not orig_in or not dest_in:
                    st.warning("⚠️ 搜尋超出範圍！您搜尋的位置位於臺北市境外，請重新輸入。")
                    st.write(f"起點: {orig_name} ({'台北市內' if orig_in else '境外'})")
                    st.write(f"終點: {dest_name} ({'台北市內' if dest_in else '境外'})")
                else:
                    # 3. Fetch district-level CWA Weather & AQI
                    orig_district = get_district_by_coords(orig_lat, orig_lon)
                    dest_district = get_district_by_coords(dest_lat, dest_lon)
                    
                    orig_weather = fetch_district_weather_snapshot(orig_district)
                    dest_weather = fetch_district_weather_snapshot(dest_district)
                    
                    # Display weather badges
                    col_weather1, col_weather2 = st.columns(2)
                    with col_weather1:
                        st.markdown(
                            f"<div class='glass-card'>"
                            f"🌐 <b>起點天氣 ({orig_district})</b><br/>"
                            f"<span class='badge-weather'>🌤️ {orig_weather.weather_desc or '晴時多雲'} | {orig_weather.temp or 28.5}°C</span>"
                            f"<span class='badge-aqi'>🌬️ AQI {orig_weather.aqi or 35}</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                    with col_weather2:
                        st.markdown(
                            f"<div class='glass-card'>"
                            f"📍 <b>終點天氣 ({dest_district})</b><br/>"
                            f"<span class='badge-weather'>🌤️ {dest_weather.weather_desc or '晴時多雲'} | {dest_weather.temp or 28.5}°C</span>"
                            f"<span class='badge-aqi'>🌬️ AQI {dest_weather.aqi or 35}</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                    
                    # 4. Invoke Gemini AI Weights Analysis
                    ai_result = get_gemini_weights(mood_text)
                    
                    # 5. Route calculation data preparation
                    req_data = RouteRequestData(
                        origin=f"{orig_lat},{orig_lon}",
                        destination=f"{dest_lat},{dest_lon}",
                        gender=gender,
                        age=age,
                        weight=weight,
                        vehicles=backend_vehicles,
                        ai_result=ai_result,
                        weather=orig_weather
                    )
                    
                    routes = recommend_routes(req_data)
                    
                    if not routes:
                        st.info("ℹ️ 在目前設定與路網約束下，未找到可抵達的路線推薦。")
                    else:
                        # Split Layout for Map and Cards
                        col_map, col_details = st.columns([3, 2])
                        
                        # Left side: Interactive Folium Map
                        with col_map:
                            st.markdown("### 🗺️ 推薦路線地圖")
                            # Build folium
                            center_lat = (orig_lat + dest_lat) / 2
                            center_lon = (orig_lon + dest_lon) / 2
                            m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
                            
                            # Draw Taipei boundary
                            if boundary and boundary.get("exterior"):
                                folium.Polygon(
                                    locations=boundary["exterior"],
                                    color="#94a3b8",
                                    weight=1.5,
                                    fill=True,
                                    fill_color="#cbd5e1",
                                    fill_opacity=0.08,
                                    tooltip="臺北市邊界"
                                ).add_to(m)
                                
                            route_colors = ["#0284c7", "#f59e0b", "#10b981"]
                            
                            for idx, r in enumerate(routes):
                                color = route_colors[idx] if idx < len(route_colors) else "#64748b"
                                # Plot polyline
                                folium.PolyLine(
                                    locations=r["coordinates"],
                                    color=color,
                                    weight=5 if idx == 0 else 3.5,
                                    opacity=0.9 if idx == 0 else 0.7,
                                    tooltip=f"推薦路線 {idx+1} ({r['vehicle']})"
                                ).add_to(m)
                                
                                # Add stations
                                if r.get("board_station"):
                                    bs = r["board_station"]
                                    folium.Marker(
                                        location=[bs["lat"], bs["lon"]],
                                        popup=f"上車點: {bs['name']}",
                                        icon=folium.DivIcon(
                                            html=f'<div style="font-size: 14px; background: white; border: 2px solid {color}; border-radius: 50%; width: 22px; height: 22px; display:flex; align-items:center; justify-content:center; box-shadow: 0 1px 3px rgba(0,0,0,0.3)">🚇</div>',
                                            icon_size=(22, 22),
                                            icon_anchor=(11, 11)
                                        )
                                    ).add_to(m)
                                if r.get("alight_station"):
                                    as_pt = r["alight_station"]
                                    folium.Marker(
                                        location=[as_pt["lat"], as_pt["lon"]],
                                        popup=f"下車點: {as_pt['name']}",
                                        icon=folium.DivIcon(
                                            html=f'<div style="font-size: 14px; background: white; border: 2px solid {color}; border-radius: 50%; width: 22px; height: 22px; display:flex; align-items:center; justify-content:center; box-shadow: 0 1px 3px rgba(0,0,0,0.3)">🚇</div>',
                                            icon_size=(22, 22),
                                            icon_anchor=(11, 11)
                                        )
                                    ).add_to(m)
                                    
                            # Draw origin and destination markers
                            folium.Marker(
                                location=[orig_lat, orig_lon],
                                popup=f"起點: {orig_name}",
                                icon=folium.DivIcon(
                                    html='<div style="background-color: #10b981; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.4)"></div>',
                                    icon_size=(14, 14),
                                    icon_anchor=(7, 7)
                                )
                            ).add_to(m)
                            
                            folium.Marker(
                                location=[dest_lat, dest_lon],
                                popup=f"終點: {dest_name}",
                                icon=folium.DivIcon(
                                    html='<div style="background-color: #ef4444; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.4)"></div>',
                                    icon_size=(14, 14),
                                    icon_anchor=(7, 7)
                                )
                            ).add_to(m)
                            
                            # Render folium in Streamlit
                            st_folium(m, width=700, height=520, returned_objects=[])
                            
                        # Right side: Empathetic AI feedback & route cards
                        with col_details:
                            st.markdown("### 💬 AI 同理心小建議")
                            ai_commentary = ai_result.get("recommendation", "根據您的情況與當前天氣，我們已為您規畫了最合適的移動方案。")
                            st.info(ai_commentary)
                            
                            st.markdown("### 📊 規劃路線清單")
                            route_chinese = {
                                "walking": "步行", "ubike": "YouBike", "mrt": "捷運",
                                "train": "火車", "bus": "公車", "car": "汽車",
                                "scooter": "機車", "taxi": "計程車"
                            }
                            
                            for idx, r in enumerate(routes):
                                color = route_colors[idx] if idx < len(route_colors) else "#64748b"
                                vehicle_zh = route_chinese.get(r["vehicle"], r["vehicle"])
                                distance_km = round(r["distance_meters"] / 1000.0, 2)
                                
                                st.markdown(
                                    f"<div class='route-card' style='border-left: 6px solid {color};'>"
                                    f"<b>第 {r['rank']} 推薦 ｜ {vehicle_zh}</b><br/>"
                                    f"⏱️ <b>預計耗時:</b> {r['time_minutes']} 分鐘<br/>"
                                    f"💰 <b>估算費用:</b> {r['fare']} 元<br/>"
                                    f"🛣️ <b>路線長度:</b> {distance_km} 公里"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )
                                
                                # Extra info if board/alight stations are resolved
                                if r.get("board_station") and r.get("alight_station"):
                                    st.caption(
                                        f"➡️ <b>乘車點:</b> {r['board_station']['name']} "
                                        f"| <b>下車點:</b> {r['alight_station']['name']}"
                                    )
