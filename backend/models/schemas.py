#schemas.py的核心職責是：確保前端傳進來的資料（如年齡、體重、地點）完全合法，並為後端輸出的路線、氣象與車站資料建立統一的格式標準。
from pydantic import BaseModel, Field
from typing import Any, List, Optional

#當前端發送 POST /api/route 請求時，接收並驗證使用者輸入的個人化條件
class RouteRequest(BaseModel):
    """前端 POST /api/route 發送之個人化路線規劃請求條件"""
    origin: str = Field(..., description="Starting location as address or 'lat,lon' coordinates")   #標示為必填欄位，接受地址或經緯度
    destination: str = Field(..., description="Ending location as address or 'lat,lon' coordinates")#標示為必填欄位，接受地址或經緯度
    gender: str = Field(..., description="Biological gender: '男性' or '女性'")
    age: int = Field(..., ge=0, le=120, description="Age of the traveler")                         #age（年齡）：限制在 0 ~ 120歲
    weight: float = Field(default=60.0, gt=0, le=300, description="Weight of the traveler in kg")  #weight（體重）：預設 60.0 kg，限制在 0 ~ 300 kg
    vehicles: List[str] = Field(default_factory=list, description="List of allowed vehicles")     #vehicles（允許運具）：如 ["mrt", "bus", "walk"]，預設為空清單
    complaint: str = Field(default="", description="Natural language complaint describing user preferences")
    #complaint（自然語言偏好/抱怨）：例如 "今天太熱不想曬太陽"，供後端 LLM 或 LLM 路由器進行語意分析與權重調整

#計算單一路徑項目
#代表計算出來的單一運具路線（例如：單車方案、捷運方案、公車方案）
# 2. 站點與運具詳細資訊模型 (Station & Route Item Schemas)
# ==============================================================================

class StationDetails(BaseModel):
    """
    精準對接 QGIS 圖層屬性與 YouBike 即時 API 之站點資料結構
    """
    id: Optional[str] = Field(None, description="站點編號 (QGIS: landmarkid / BSM_BUSSTO / YouBike: sno)")
    name: str = Field(..., description="站點名稱 (QGIS: landmarkna / BSM_CHINES / YouBike: sna)")
    lat: float = Field(..., description="站點緯度 WGS84 (QGIS Geometry / YouBike: latitude)")
    lon: float = Field(..., description="站點經度 WGS84 (QGIS Geometry / YouBike: longitude)")
    line_info: Optional[str] = Field(None, description="路線/區域 (QGIS: mrtcode, railcode / YouBike: sarea)")
    
    # YouBike 動態即時資訊屬性 (僅當運具包含 YouBike 時填寫，其餘運具為 None)
    available_rent_bikes: Optional[int] = Field(None, description="YouBike 可借車輛數 (API: available_rent_bikes)")
    available_return_bikes: Optional[int] = Field(None, description="YouBike 可還空位數 (API: available_return_bikes)")


class RouteItem(BaseModel):
    """單一推薦運具路線說明"""
    rank: int = Field(..., description="路線推薦排名 (1 代表最推薦)")
    vehicle: str = Field(..., description="運具類別 (如: '捷運', '公車', 'YouBike', '步行')")
    time_seconds: float = Field(..., description="物理預估時間 (秒)")
    time_minutes: float = Field(..., description="物理預估時間 (分鐘)")
    adjusted_time_seconds: float = Field(..., description="經個人化/氣象校正後之感知時間 (秒)")
    fare: float = Field(..., description="預估車資 (TWD)")
    distance_meters: float = Field(..., description="總移動距離 (公尺)")
    coordinates: List[List[float]] = Field(..., description="路線經緯度軌跡點清單 [[lat, lon], ...]")
    
    board_station: Optional[StationDetails] = Field(None, description="上車站點/借車點資訊 (全程步行/騎車時為 None)")
    alight_station: Optional[StationDetails] = Field(None, description="下車站點/還車點資訊 (全程步行/騎車時為 None)")

# ==============================================================================
# 3. 氣象與環境數據模型 (Weather Schemas)
# ==============================================================================

class WeatherData(BaseModel):
    """行政區即時環境氣象快照"""
    district: str = Field(..., description="行政區名稱 (如: '信義區')")
    weather_desc: Optional[str] = Field(None, description="天氣現象描述 (如: '多雲時晴')")
    rain_24h: Optional[float] = Field(None, description="24小時累積雨量 (mm)")
    rain_probability: Optional[float] = Field(None, description="降雨機率 (%)")
    aqi: Optional[float] = Field(None, description="空氣品質指數 (AQI)")
    temperature: Optional[float] = Field(None, description="氣溫 (°C)")
    wind_speed: Optional[float] = Field(None, description="風速 (m/s)")
    extreme_weather_alert: str = Field(default="正常", description="警報狀態 (如: '豪雨特報')")
    heat_warning_level: Optional[str] = Field(None, description="高溫燈號 (如: '黃色燈號')")
    
    # 資料可信度與降級機制標記
    is_realtime: bool = Field(default=True, description="是否為氣象署 API 即時資料")
    data_source: str = Field(default="CWA_LIVE", description="資料來源標記 ('CWA_TOWN_API', 'FALLBACK')")


class WeatherDataResponse(BaseModel):
    """起終點環境氣象對比回應"""
    origin: WeatherData = Field(..., description="起點氣象資料")
    destination: WeatherData = Field(..., description="終點氣象資料")


# ==============================================================================
# 4. 主回應與圖資地標模型 (Response Schemas)
# ==============================================================================

class RouteResponse(BaseModel):
    """POST /api/route 最終輸出之完整 JSON 結構"""
    reasoning: str = Field(..., description="LLM 評估與路線推薦決策說明")
    routes: List[RouteItem] = Field(..., description="多運具推薦路線清單")
    ai: Dict[str, Any] = Field(..., description="AI 分析指標 (如: 卡路里消耗、碳足跡減少量)")
    weather: WeatherDataResponse = Field(..., description="起終點環境氣象對比")


class StationItem(BaseModel):
    """前端地圖載入時繪製地標 (Marker) 專用之極簡站點模型"""
    name: str = Field(..., description="站點名稱")
    lat: float = Field(..., description="緯度")
    lon: float = Field(..., description="經度")


class StationsResponse(BaseModel):
    """GET /api/stations 回傳之全區交通站點圖資列表"""
    mrt: List[StationItem] = Field(default_factory=list, description="捷運站清單")
    train: List[StationItem] = Field(default_factory=list, description="火車站清單")
    bus: List[StationItem] = Field(default_factory=list, description="公車站清單")
    youbike: List[StationItem] = Field(default_factory=list, description="YouBike 即時站點清單")
