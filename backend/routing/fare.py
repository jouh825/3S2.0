"""Fare formulas preserved from the notebook."""

import math

#youbike的計費方式(ubike_fare)
def ubike_fare(minutes: float, identity: str = "adult") -> float:
    """
    計算臺北市 YouBike 2.0 騎乘費率 (對齊臺北市政府現行補助政策)
    - 2024/02/28 起，於臺北市借車，會員享前 30 分鐘免費 ($0 元)。
    - 超過 30 分鐘，每 30 分鐘收費 10 元 (未滿 30 分鐘以 30 分鐘計)。
    """
    # 1. 前 30 分鐘由市府全額補助，費用為 0 元
    if minutes <= 30:
        return 0.0
    
    # 2. 超過 30 分鐘後的遞增計費 (每 30 分鐘 10 元)
    extra_units = math.ceil((minutes - 30) / 30)
    return extra_units * 10.0

# =====================================================================
# 🚖 【使用者自訂區域：計程車費率公式】 (User-modifiable Taxi Fare Formula)
# 後續若有需要調整計程車起跳價、每段加成距離或夜間加成，請修改此處。
# =====================================================================
def taxi_fare(length_km: float, is_night_surge: bool = False) -> float:
    """
    Calculate taxi fare based on Taipei City statutory rates.
    - Base fare: 85 NTD for first 1.25 km.
    - Progressive fare: 5 NTD for every additional 200m (0.2 km).
    - Night surge: Add 20 NTD if active.
    """
    # 1. 計算基本里程與起跳價
    if length_km <= 1.25:
        fare = 85.0
    else:
        # 2. 超過基本里程，每200公尺加收5元 (無條件進位)
        extra_dist_m = (length_km - 1.25) * 1000.0
        fare = 85.0 + (math.ceil(extra_dist_m / 200.0) * 5.0)
    
    # 3. 夜間加成加收 20 元 (23:00 - 06:00)
    if is_night_surge:
        fare += 20.0
        
    return fare
# =====================================================================


# =====================================================================
# 🚌 【使用者自訂區域：公車費率公式】 (User-modifiable Bus Fare Formula)
# 後續若有需要調整公車分段收費或身分優惠金額，請修改此處。
# =====================================================================
def bus_fare(age: int) -> float:
    """
    依據年齡 (Age) 自動判定雙北公車票價：
    - 未滿 6 歲: 免費 ($0 元)
    - 6 歲至 11 歲 (兒童) 或 65 歲以上 (敬老): 半票 ($8 元)
    - 12 歲至 64 歲 (全票): $15 元
    """
    if age < 6:
        return 0.0
    elif age < 12 or age >= 65:
        return 8.0  # 半票 (兒童/敬老)
    return 15.0     # 全票 (12~64 歲)

# =====================================================================


def mrt_fare(length_km: float, age: int) -> float:
    """
    依據年齡 (Age) 自動判定臺北捷運票價：
    - 未滿 6 歲: 免費 ($0 元)
    - 基本里程: 5 公里內 20 元，之後每 4 公里 +5 元
    - 6~11 歲與 65 歲以上: 法定 5 折優惠
    """
    if age < 6:
        return 0.0

    # 1. 計算全票基準票價
    if length_km <= 5.0:
        base_fare = 20.0
    else:
        base_fare = 20.0 + (math.ceil((length_km - 5.0) / 4.0) * 5.0)
    # 2. 依年齡判定折扣
    if age < 12 or age >= 65:
        return float(math.ceil(base_fare * 0.5))
    return float(base_fare)
    
# =====================================================================


def train_fare(length_km: float, age: int) -> float:
    """
    依據年齡 (Age) 自動判定臺鐵區間車票價：
    - 未滿 6 歲: 免費 ($0 元)
    - 基準費率: 每公里 1.46 元 (最低消費 15 元)
    - 6~11 歲與 65 歲以上: 法定 5 折優惠
    """
    if age < 6:
        return 0.0

    base_fare = max(15.0, length_km * 1.46)
    if age < 12 or age >= 65:
        return float(math.ceil(base_fare * 0.5))
    return float(math.ceil(base_fare))
