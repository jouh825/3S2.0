# backend/ai/gemini.py
#套進引入
import json
import logging
from typing import Dict, Any

# 從設定檔與提示詞檔引入必要變數
from backend.config import GEMINI_API_KEY, GEMINI_MODEL_NAME
from backend.ai.prompt import SYSTEM_PROMPT

# 初始化日誌紀錄器
logger = logging.getLogger(__name__)

# 建立防呆預設值：若 AI 判斷失敗，則回傳全正常的標準權重，確保系統不崩潰
DEFAULT_AI_RESULT: Dict[str, Any] = {
    "reasoning": "系統暫時無法連線至 AI 引擎，已為您自動規劃標準路線。",
    "walking_speed_multiplier": 1.0,
    "banned_vehicles": [],
    "weights": {
        "walking": 1.0, "ubike": 1.0, "mrt": 1.0, 
        "bus": 1.0, "train": 1.0, "taxi": 1.0, 
        "scooter": 1.0, "car": 1.0
    }
}

def get_route_weights(user_input: str, user_profile: dict, weather_info: str) -> dict:
    """
    接收前端資料與天氣，呼叫 Gemini 進行情境判斷，回傳路網權重 JSON。
    """
    if not GEMINI_API_KEY:
        logger.warning("⚠️ Warning: GEMINI_API_KEY is not set. Using default routing weights.")
        return DEFAULT_AI_RESULT.copy()
        
    try:
        from google import genai
        from google.genai import types
        
        # 延遲初始化 genai.Client 避免 import 時崩潰
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # 組裝交給 AI 判斷的上下文資訊
        context = f"""
        【使用者生理基礎與資料】：{json.dumps(user_profile, ensure_ascii=False)}
        【即時環境與天氣資訊】：{weather_info}
        【使用者對話與需求】：{user_input}
        """

        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=context,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2, # 保持低隨機性，確保權重數值穩定
            )
        )
        
        # 解析並回傳 Dictionary
        return normalize_ai_result(json.loads(response.text))

    except json.JSONDecodeError as e:
        logger.error("Gemini 回傳格式非標準 JSON，解析失敗: %s", str(e))
        return DEFAULT_AI_RESULT.copy()
        
    except Exception as e:
        logger.error("呼叫 Gemini API 時發生未知錯誤: %s", str(e))
        return DEFAULT_AI_RESULT.copy()

def get_gemini_weights(user_input: str, weather: str, profile: str) -> dict:
    """
    Alias or wrapper of get_route_weights to conform with other submodules.
    """
    # Parse profile text back to dict if needed, or pass as is
    profile_dict = {"profile_text": profile}
    return get_route_weights(user_input, profile_dict, weather)
#資料正規化
def normalize_ai_result(result: dict) -> dict:
    """Ensure Gemini output has all expected routing fields."""
    normalized = DEFAULT_AI_RESULT.copy()
    normalized.update({k: v for k, v in result.items() if k != "weights"})
    weights = DEFAULT_AI_RESULT["weights"].copy()
    weights.update(result.get("weights", {}))
    normalized["weights"] = weights
    normalized["banned_vehicles"] = result.get("banned_vehicles", [])
    return normalized
