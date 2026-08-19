import os
import tomllib  # Python 3.11+ 內建，若為舊版可自動降級處理
from pathlib import Path
from functools import lru_cache
import streamlit as st  # 匯入 streamlit 以讀取雲端 Secrets

# ==========================================
# 專案根目錄與 secrets.toml 定位
# ==========================================
# BASE_DIR 定位為 C:\3s\ (即 backend 的上一層)
BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_FILE = BASE_DIR / ".streamlit" / "secrets.toml"

# ==========================================
# 輔助函式：自動從 Streamlit Secrets、實體檔案 或 環境變數 抓取金鑰
# ==========================================
def get_secret(key_name):
    # 1. 優先嘗試由 Streamlit 原生 Secrets 讀取 (適用於 Streamlit Cloud)
    try:
        if hasattr(st, "secrets") and key_name in st.secrets:
            return st.secrets[key_name]
    except Exception:
        pass

    # 2. 做法 B：若 Streamlit 原生機制報錯/找不到，強制依照專案絕對路徑讀取 secrets.toml
    if SECRETS_FILE.exists():
        try:
            with open(SECRETS_FILE, "rb") as f:
                secrets_data = tomllib.load(f)
                if key_name in secrets_data:
                    return secrets_data[key_name]
        except Exception as e:
            print(f"[Warning] 讀取 {SECRETS_FILE} 發生錯誤: {e}")

    # 3. 降級備案：從系統環境變數讀取
    return os.environ.get(key_name)

# ==========================================
# 1. API 金鑰設定
# ==========================================
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
# 支援多種別名，確保氣象署金鑰能被抓到
WEATHER_API_KEY = get_secret("WEATHER_API_KEY") or get_secret("CWA_API_KEY")
MOENV_API_KEY = get_secret("MOENV_API_KEY")

# 交通部 TDX API 金鑰
TDX_APP_ID = get_secret("TDX_APP_ID")
TDX_APP_KEY = get_secret("TDX_APP_KEY")

if not GEMINI_API_KEY:
    print("[Warning] 未偵測到 GEMINI_API_KEY，將採用靜態預設值。")

# ==========================================
# 2. 模型與參數設定
# ==========================================
GEMINI_MODEL_NAME = get_secret("GEMINI_MODEL") or "gemini-3.5-flash"

# ==========================================
# 3. 專案路徑設定
# ==========================================
DATA_DIR = BASE_DIR / "backend" / "data"
GRAPH_CACHE_DIR = DATA_DIR / "graphs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

class Settings:
    """FastAPI settings adapter."""
    app_name: str = "Empathetic Route Recommendation"
    frontend_dir: Path = BASE_DIR / "frontend"
    data_dir: Path = DATA_DIR
    graph_cache_dir: Path = GRAPH_CACHE_DIR
    gemini_api_key: str | None = GEMINI_API_KEY
    cwa_api_key: str | None = WEATHER_API_KEY
    moenv_api_key: str | None = MOENV_API_KEY
    gemini_model: str = GEMINI_MODEL_NAME
    taipei_center: tuple[float, float] = (25.040, 121.540)
    search_dist_m: int = 9000
    default_travel_period: str = os.environ.get("TRAVEL_PERIOD", "離峰期")
    allow_osm_download: bool = str(os.environ.get("ALLOW_OSM_DOWNLOAD", "true")).lower() == "true"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
