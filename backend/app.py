#app.py這個檔案只負責前端介面與資料傳遞，細項資訊應該都放在backend目錄下的各檔案裡
#匯入套件與模組
import os   #python標準庫，處理作業系統相關操作
import streamlit as st  #匯入streamlit套件，建立互動式web前端互動介面
import folium           #繪製互動式地圖(e.g.畫標記、路線圖層等)
from streamlit_folium import st_folium   #將folium地圖元件
import requests   #呼叫ArcGIS地理編碼(地址轉經緯度)用
from shapely.geometry import Point, Polygon  #幾何運算(在此用於判別經緯度是否位於台北市多邊形內)

#自訂後端模組匯入邏輯
from backend.config import get_settings       #get_settings：讀取系統設定
from backend.routing.graph import build_graphs  #build_graphs：載入路網圖資
from backend.routing.routing import RouteRequestData, recommend_routes, parse_place  #RouteRequestData, recommend_routes, parse_place：路徑規劃資料結構與核心推薦演算法
from backend.ai.gemini import get_gemini_weights   #get_gemini_weights：呼叫gemini將使用者心情轉換為路徑選擇的權重
from backend.api.weather import fetch_district_weather_snapshot, WeatherSnapshot   #fetch_district_weather_snapshot, WeatherSnapshot：抓取特定行政區氣象及空氣品質資料
from backend.utils.gis_helperget_all_stations, get_taipei_boundary_coords, get_district_by_coords
# import get_all_stations, get_taipei_boundary_coords, get_district_by_coords：GIS 工具，用來取得車站清單、台北市邊界座標，以及根據經緯度查詢所屬行政區

# Set page config 網頁基本設定與CSS(控制網頁外觀與排版的電腦語言)樣式美化
st.set_page_config(
    page_title="臺北市大眾運輸同理心路線推薦系統",
    page_icon="🚇",
    layout="wide",   #寬螢幕模式
    initial_sidebar_state="expanded"
)

# Custom Alice Blue & Glassmorphism Styling
#寫入自訂 CSS 樣式，採用 毛玻璃風格 (Glassmorphism) 與淡藍/愛麗絲藍配色（Alice Blue），用來美化主標題、卡片、天氣標籤與狀態文字。
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
    .status-msg {
        font-weight: 500;
        color: #0284c7;
        padding: 4px 8px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =====================================================================
# ⚡️ 【效能優化區：Streamlit 記憶體快取】 (Server Warmup Cache)
# =====================================================================
@st.cache_resource               #Streamlit 的裝飾器（Decorator），用於快取消耗大量 CPU/記憶體的全局資源
def load_cached_networks():      #呼叫 build_graphs() 建立並回傳路網圖
    """Load cached road/transit network graphs and prebuild routing tables once."""
    st.write("🔧 正在初始化臺北市路網圖資並預建路由表 (僅在首次啟動時執行)...")
    return build_graphs()

@st.cache_resource
def load_cached_gis():  #讀取所有車站資訊與回傳路網圖
    """Load shapefiles for stations and city boundary boundaries once."""
    stations = get_all_stations()
    boundary = get_taipei_boundary_coords()
    return stations, boundary
# =====================================================================

# Trigger startup resource loading
#執行上述函數，將載入後的路網 (graphs)、車站 (stations) 和邊界 (boundary) 存在記憶體中備用
graphs = load_cached_networks()
stations, boundary = load_cached_gis()

# Address Geocoder using Esri ArcGIS World Geocoding Service (Robust on Cloud Platforms)
#地理編碼（地址轉經緯度）
#search_arcgis_candidates：使用 Esri ArcGIS 免費 API 將地名轉為經緯度
def search_arcgis_candidates(query: str) -> list[dict]:
    """Search addresses using Esri ArcGIS Geocoder (not rate-limited or blocked on AWS cloud)."""
    full_query = query if any(k in query for k in ["台北", "臺北"]) else f"台北市 {query}"
    url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
    params = {
        "f": "json",
        "singleLine": full_query,
        "maxLocations": 6,  #只抓取最多6個結果
        "outFields": "Addr_type"
    }
    try:
        r = requests.get(url, params=params, timeout=6)
        if r.status_code == 200:
            data = r.json()
            candidates = []
            for c in data.get("candidates", []):
                lat = float(c["location"]["y"])
                lon = float(c["location"]["x"])
                # Bounding box filter for Taipei City to ensure relevant results，建立台北市概略邊界盒
                if 24.95 <= lat <= 25.22 and 121.45 <= lon <= 121.67:    #建立經緯度篩選條件
                    candidates.append({
                        "address": c["address"],
                        "lat": lat,
                        "lon": lon
                    })
            return candidates
    except Exception as e:
        st.error(f"ArcGIS 搜尋失敗: {e}")
    return []

# =====================================================================

# Check boundary inclusion (Ray casting using shapely)
#is_point_in_taipei：使用shapely套件進行放射線法。利用台北市外圍座標建立多邊形 Polygon，並檢查經緯度點 Point(lon, lat) 是否落在市內。若邊界圖資缺失，則退回簡單框線範圍檢查。
def is_point_in_taipei(lat: float, lon: float, boundary_coords: dict) -> bool:
    if not boundary_coords or not boundary_coords.get("exterior"):
        return 24.95 <= lat <= 25.22 and 121.45 <= lon <= 121.67
    poly = Polygon([(c[1], c[0]) for c in boundary_coords["exterior"]])
    return poly.contains(Point(lon, lat))

# Helper to map vehicle keys
#建立一個運具字典
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

# Initialize session state for geocoding candidate lists & selections
# st.session_state： Streamlit 的跨跨頁/刷新狀態儲存區。
#初始化 "origin_candidates" 這個字典，因為記憶體中沒有"origin_candidates"這個key所以給予他一個空列表
if "origin_candidates" not in st.session_state:
    st.session_state["origin_candidates"] = []
if "destination_candidates" not in st.session_state:
    st.session_state["destination_candidates"] = []
#在這裡預先初始化起點/終點的搜尋候選名單，並設定預設起點（台北車站）與終點（台北101)
if "origin_selected" not in st.session_state:
    st.session_state["origin_selected"] = {"lat": 25.0478, "lon": 121.5319, "label": "臺北車站 (預設)"}
if "destination_selected" not in st.session_state:
    st.session_state["destination_selected"] = {"lat": 25.0339, "lon": 121.5644, "label": "臺北101 (預設)"}

# Sidebar inputs
st.sidebar.markdown("### 📋 1. 設定起迄位置")

# --- Origin geocoder ---
#使用者輸入關鍵字後點擊「🔍 搜尋起點」，呼叫 API 並將候選結果存入 st.session_state["origin_candidates"]。
origin_query = st.sidebar.text_input("搜尋起點 (Origin)", value="", placeholder="輸入起點關鍵字，如：台北車站")
col_s1, col_c1 = st.sidebar.columns([1, 1])
with col_s1:
    if st.button("🔍 搜尋起點"):
        if origin_query.strip():
            with st.spinner("搜尋中..."):
                cands = search_arcgis_candidates(origin_query)
                if cands:
                    st.session_state["origin_candidates"] = cands
                else:
                    st.error("找不到相符的臺北市地址！")
        else:
            st.warning("請輸入關鍵字")
with col_c1:
    if st.button("❌ 清除起點結果"):
        st.session_state["origin_candidates"] = []
#若有候選地址，會動態跳出 selectbox（下拉選單）讓使用者點選精確地址。
#選定後，將座標與標籤更新至 st.session_state["origin_selected"] 並顯示目前綠色起點狀態
if st.session_state["origin_candidates"]:
    orig_labels = [c["address"] for c in st.session_state["origin_candidates"]]
    selected_orig = st.sidebar.selectbox("請選擇確切起點候選地址：", options=orig_labels, key="origin_selectbox")
    # Store the chosen candidate details
    match = next(c for c in st.session_state["origin_candidates"] if c["address"] == selected_orig)
    st.session_state["origin_selected"] = {
        "lat": match["lat"],
        "lon": match["lon"],
        "label": match["address"]
    }
st.sidebar.markdown(f"<div class='status-msg'>🟢 起點：{st.session_state['origin_selected']['label']}</div>", unsafe_allow_html=True)

# --- Destination geocoder ---
dest_query = st.sidebar.text_input("搜尋終點 (Destination)", value="", placeholder="輸入終點關鍵字，如：台北101")
col_s2, col_c2 = st.sidebar.columns([1, 1])
with col_s2:
    if st.button("🔍 搜尋終點"):
        if dest_query.strip():
            with st.spinner("搜尋中..."):
                cands = search_arcgis_candidates(dest_query)
                if cands:
                    st.session_state["destination_candidates"] = cands
                else:
                    st.error("找不到相符的臺北市地址！")
        else:
            st.warning("請輸入關鍵字")
with col_c2:
    if st.button("❌ 清除終點結果"):
        st.session_state["destination_candidates"] = []

if st.session_state["destination_candidates"]:
    dest_labels = [c["address"] for c in st.session_state["destination_candidates"]]
    selected_dest = st.sidebar.selectbox("請選擇確切終點候選地址：", options=dest_labels, key="dest_selectbox")
    # Store the chosen candidate details
    match = next(c for c in st.session_state["destination_candidates"] if c["address"] == selected_dest)
    st.session_state["destination_selected"] = {
        "lat": match["lat"],
        "lon": match["lon"],
        "label": match["address"]
    }
st.sidebar.markdown(f"<div class='status-msg'>🔴 終點：{st.session_state['destination_selected']['label']}</div>", unsafe_allow_html=True)

#=======================================================================================================================
#側邊攔：個人屬性、心情場景及運具選擇
st.sidebar.markdown("---")
st.sidebar.markdown("### 👤 2. 個人身分屬性 (安全與票價計算)")
age = st.sidebar.slider("年齡 (Age)", min_value=0, max_value=110, value=30)
gender = st.sidebar.selectbox("性別 (Gender)", options=["男性", "女性"], index=0)
weight = st.sidebar.slider("體重 (Weight - kg)", min_value=30, max_value=150, value=60)

st.sidebar.markdown("---")
st.sidebar.markdown("### 💡 3. 心情與出行場景 (AI 智能語意分析)")
mood_text = st.sidebar.text_area(
    "輸入您的出行偏好 / 心情需求",
    value="外面天氣很熱，我背著沉重的行李，想坐得舒服一點，不想走太多路，有冷氣最好。",
    placeholder="例如：我剛下班很累，希望快速回家。或是：今天天氣很好，我想做點有氧運動健行。"
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚗 4. 交通工具選擇")
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
    if not backend_vehicles:
        st.error("⚠️ 請至少選取一種移動工具！")
    else:
        with st.spinner("🔍 正在定位並規劃路徑，請稍候..."):
            orig_lat = st.session_state["origin_selected"]["lat"]
            orig_lon = st.session_state["origin_selected"]["lon"]
            orig_name = st.session_state["origin_selected"]["label"]
            
            dest_lat = st.session_state["destination_selected"]["lat"]
            dest_lon = st.session_state["destination_selected"]["lon"]
            dest_name = st.session_state["destination_selected"]["label"]
            
            # Check Taipei bounds ray-casting precision inclusion
            orig_in = is_point_in_taipei(orig_lat, orig_lon, boundary)
            dest_in = is_point_in_taipei(dest_lat, dest_lon, boundary)
            
            if not orig_in or not dest_in:
                st.error("超出範圍！您選擇的位置位於臺北市境外，請重新輸入並搜尋。")
                st.write(f"起點: {orig_name} ({'台北市內' if orig_in else '境外'})")
                st.write(f"終點: {dest_name} ({'台北市內' if dest_in else '境外'})")
            else:
                # Fetch district-level CWA Weather & AQI
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
                
                # Invoke Gemini AI Weights Analysis
                ai_result = get_gemini_weights(mood_text)
                
                # Route calculation data preparation
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
                            
                            # Add boarding/alighting stations
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
                            
                            if r.get("board_station") and r.get("alight_station"):
                                st.caption(
                                    f"➡️ <b>乘車點:</b> {r['board_station']['name']} "
                                    f"| <b>下車點:</b> {r['alight_station']['name']}"
                                )
