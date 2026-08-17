"""Weather, AQI, and town-level weather logic."""

import time
from dataclasses import dataclass
import requests
from typing import Optional, List, Dict
from backend.config import WEATHER_API_KEY, MOENV_API_KEY

#WeatherSnapshot：封裝單一行政區的所有環境指標（溫度、風速、AQI、警報標籤等
@dataclass
class WeatherSnapshot:
    """Taipei district environmental snapshot."""
    district: str = "臺北市"
    weather_desc: Optional[str] = None
    rain_24h: Optional[float] = None
    rain_probability: Optional[float] = None
    aqi: Optional[float] = None
    temperature: Optional[float] = None
    wind_speed: Optional[float] = None
    extreme_weather_alert: str = "正常"
    heat_warning_level: Optional[str] = None
    # 🆕 新增資料品質/來源標記
    is_realtime: bool = True               # 是否為即時資料
    data_source: str = "CWA_TOWN_API"      # 可選值：CWA_TOWN_API / MICROCLIMATE_MOCK / GLOBAL_FALLBACK


def fetch_weather_snapshot() -> WeatherSnapshot:
    """
    Fetch the overall base Taipei weather. 
    Maintained for backwards compatibility in other modules.
    """
    return fetch_district_weather_snapshot("臺北市")

#利用字典安行政區名稱做記憶體快取，並設定10分鐘為快取效期，避免頻繁發送api導致被氣象署限劉
_WEATHER_CACHE: Dict[str, tuple[float, WeatherSnapshot]] = {}
CACHE_TTL_SECONDS = 600.0  # 10 minutes cache

def fetch_district_weather_snapshot(district: str) -> WeatherSnapshot:
    """
    Fetch weather for a specific Taipei town/district (e.g. 信義區, 大安區)
    using a 10-minute TTL cache to prevent slow API requests.
    """
    global _WEATHER_CACHE
    now = time.time()
    if district in _WEATHER_CACHE:
        timestamp, cached_snapshot = _WEATHER_CACHE[district]
        if now - timestamp < CACHE_TTL_SECONDS:
            return cached_snapshot
            
    snapshot = _fetch_district_weather_snapshot_uncached(district)
    _WEATHER_CACHE[district] = (now, snapshot)
    return snapshot

#三層式資料抓取與模擬機制
def _fetch_district_weather_snapshot_uncached(district: str) -> WeatherSnapshot:
    """Actual network fetch or microclimate mock fallback."""
    snapshot = WeatherSnapshot(district=district)
    
    # 1. 取得臺北市的大致基礎觀測數據作為基底與 fallback
    base_temp = 28.5
    base_wind = 2.0
    base_rain_24h = 0.0
    base_rain_prob = 20.0
    base_aqi = 35.0
    base_desc = "晴"

    if WEATHER_API_KEY:
        # Fetch CWA station overall average temperature
        base_temp, base_wind, base_rain_24h, base_desc = get_cwa_base_observation(WEATHER_API_KEY)
        base_rain_prob = get_cwa_base_forecast(WEATHER_API_KEY)
    
    if MOENV_API_KEY:
        base_aqi = get_moenv_base_aqi(MOENV_API_KEY)

    # 2. 嘗試用 CWA 鄉鎮市區 API (F-D0047-089) 精準抓取該區預報
    cwa_success = False
    if WEATHER_API_KEY and district != "臺北市" and district != "境外":
        cwa_success = query_cwa_town_api(snapshot, WEATHER_API_KEY, district)
   # 3. 狀態標記與備援降級機制 (Graceful Degradation)
    if cwa_success:
       snapshot.is_realtime = True
        snapshot.data_source = "CWA_TOWN_API"
    else:
        # 當 CWA 鄉鎮 API 失敗或無 Key 時，標記為非即時數據，啟動學術微氣候模型/預設備援 進行模擬
        snapshot.is_realtime = False
        snapshot.data_source = "MICROCLIMATE_MOCK" if WEATHER_API_KEY else "DEFAULT_FALLBACK"

        # 溫度與空氣品質偏移量 (Urban heat island & vegetation cooling)
        offset = (hash(district) % 7) / 10.0
        aqi_offset = hash(district) % 9 - 4
        if district in ["萬華區", "大同區", "中正區"]:
            offset += 0.4
            aqi_offset += 3
        elif district in ["北投區", "文山區", "內湖區"]:
            offset -= 0.5
            aqi_offset -= 5
            
        snapshot.temperature = base_temp + offset
        snapshot.aqi = max(0.0, base_aqi + aqi_offset)
        snapshot.weather_desc = base_desc
        snapshot.rain_24h = base_rain_24h
        snapshot.rain_probability = base_rain_prob
        snapshot.wind_speed = base_wind

    apply_extreme_weather(snapshot)
    return snapshot

# 鄉鎮 API 查詢與解析 (query_cwa_town_api & parse_town_weather_elements)
def query_cwa_town_api(snapshot: WeatherSnapshot, api_key: str, district: str) -> bool:
    """
    Query CWA F-D0047-089 Town Weather API to extract weather variables for a given district.
    """
    # Force clean name (ensure '區' is present, e.g. '信義' -> '信義區')
    search_name = district
    if not search_name.endswith("區") and len(search_name) == 2:
        search_name += "區"
        
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089"
    params = {"Authorization": api_key, "locationName": search_name}
    try:
        res = requests.get(url, params=params, timeout=8)
        if res.status_code == 200:
            data = res.json()
            locations = data["records"]["locations"][0]["location"]
            for loc in locations:
                if loc["locationName"] == search_name:
                    parse_town_weather_elements(snapshot, loc["weatherElement"])
                    # Use overall average AQI as base, then offset it slightly for the district
                    base_aqi = 35.0
                    if MOENV_API_KEY:
                        base_aqi = get_moenv_base_aqi(MOENV_API_KEY)
                    aqi_offset = hash(search_name) % 9 - 4
                    if search_name in ["萬華區", "大同區", "中正區"]:
                        aqi_offset += 3
                    elif search_name in ["北投區", "文山區", "內湖區"]:
                        aqi_offset -= 5
                    snapshot.aqi = max(0.0, base_aqi + aqi_offset)
                    return True
    except Exception as e:
        print(f"[Warning] Failed to query CWA Town API: {e}")
    return False


def parse_town_weather_elements(snapshot: WeatherSnapshot, elements: List[Dict]) -> None:
    """Parse district-specific weather elements from CWA response."""
    for elem in elements:
        name = elem.get("elementName")
        try:
            # Get the first/upcoming time value
            val = elem["time"][0]["elementValue"][0]["value"]
            if name == "T": # Temperature
                snapshot.temperature = float(val)
            elif name == "Wx": # Weather description
                snapshot.weather_desc = str(val)
            elif name == "PoP12h": # Precipitation probability
                snapshot.rain_probability = float(val)
            elif name == "WS": # Wind speed
                # Wind speed might contain text like '1 公尺/秒' or '2 m/s'
                speed_str = "".join(c for c in val if c.isdigit() or c == '.')
                snapshot.wind_speed = float(speed_str) if speed_str else 2.0
        except Exception:
            pass

#基礎觀測站與環境部 AQI 查詢 - 向 O-A0001-001 (自動氣象站觀測資料) 查詢台北主要觀測站（如台北站 466920），過濾掉異常值（如 -999.0 表示儀器故障），計算全台北市平均氣溫、風速與累積雨量。
def get_cwa_base_observation(api_key: str) -> tuple:
    """Fetch CWA station observations to calculate Taipei average baseline weather."""
    station_ids = "466920,C0A980,C0A9C0,C0A9F0,C0AC70"
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001"
    try:
        res = requests.get(url, params={"Authorization": api_key, "StationId": station_ids}, timeout=6)
        if res.status_code == 200:
            stations = res.json()["records"]["Station"]
            rains, temps, winds, descriptions = [], [], [], []
            for station in stations:
                element = station.get("WeatherElement", {})
                try:
                    rain = float(element["Now"]["Rainfall24hr"])
                    rains.append(0.0 if rain in {-998.0, -999.0} else rain)
                except Exception: pass
                try:
                    temp = float(element["AirTemperature"])
                    if -50 <= temp <= 60: temps.append(temp)
                except Exception: pass
                try:
                    wind = float(element["WindSpeed"])
                    if wind >= 0: winds.append(wind)
                except Exception: pass
                weather = element.get("Weather")
                if weather and weather not in {"-99", "-999"}: descs.append(weather)
                
            avg_temp = sum(temps) / len(temps) if temps else 28.5
            avg_wind = sum(winds) / len(winds) if winds else 2.0
            avg_rain = sum(rains) / len(rains) if rains else 0.0
            desc = descriptions[0] if descriptions else "晴"
            return avg_temp, avg_wind, avg_rain, desc
    except Exception:
        pass
    return 28.5, 2.0, 0.0, "晴"

#基礎觀測站與環境部 AQI 查詢 - 向 F-C0032-001 查詢台北市整體 PoP 降雨機率預報
def get_cwa_base_forecast(api_key: str) -> float:
    """Fetch base rain probability forecast for Taipei City."""
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
    params = {"Authorization": api_key, "locationName": "臺北市", "elementName": "PoP"}
    try:
        res = requests.get(url, params=params, timeout=6)
        if res.status_code == 200:
            data = res.json()
            val = data["records"]["location"][0]["weatherElement"][0]["time"][0]["parameter"]["parameterName"]
            return float(val)
    except Exception:
        pass
    return 20.0

#向環境部 API（頻道 aqx_p_432 / aqx_p_434）取得台北市監測站的 AQI 數值並取平均
def get_moenv_base_aqi(api_key: str) -> float:
    """Fetch base AQI average value for Taipei City."""
    channels = ["aqx_p_432", "aqx_p_434"]
    for channel in channels:
        url = f"https://data.moenv.gov.tw/api/v2/{channel}"
        try:
            res = requests.get(url, params={"language": "zh", "api_key": api_key}, timeout=6)
            if res.status_code == 200:
                data = res.json()
                records = []
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = data.get("records", [])
                
                aqi_values = []
                for rec in records:
                    county = rec.get("county") or rec.get("County") or rec.get("sitename")
                    aqi_val = rec.get("aqi") or rec.get("AQI")
                    if county in {"臺北市", "台北市"} and str(aqi_val).strip() not in {"", "None", "-999"}:
                        aqi_values.append(float(aqi_val))
                if aqi_values:
                    return sum(aqi_values) / len(aqi_values)
        except Exception:
            continue
    return 35.0

#警報與極端天氣判定
def apply_extreme_weather(snapshot: WeatherSnapshot) -> None:
    """Apply the notebook's heat, rain, and wind alert thresholds."""
    if snapshot.temperature is not None:
        if snapshot.temperature >= 38.0:
            snapshot.heat_warning_level = "紅色燈號（極端高溫）"
        elif snapshot.temperature >= 37.0:
            snapshot.heat_warning_level = "橙色燈號（非常高溫）"
        elif snapshot.temperature >= 36.0:
            snapshot.heat_warning_level = "黃色燈號（高溫提示）"
    if snapshot.rain_24h is not None and snapshot.rain_24h >= 80.0:
        snapshot.extreme_weather_alert = "豪雨特報" if snapshot.rain_24h >= 200.0 else "大雨特報"
    if snapshot.wind_speed is not None and snapshot.wind_speed >= 10.0:
        snapshot.extreme_weather_alert = "陸上強風特報"
