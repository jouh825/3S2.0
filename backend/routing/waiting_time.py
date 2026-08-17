"""Waiting time formulas preserved from the notebook."""

def mrt_wait_minutes(travel_period: str) -> dict[str, dict[str, float]]:
    """Return MRT line speeds and wait times from the notebook."""
    peak = travel_period == "上下班尖峰期" or travel_period == "尖峰"
    return {
        "文湖線": {"avg_speed": 32.50, "wait_time": (2.01 / 2) if peak else (4.13 / 2)},
        "淡水信義線": {"avg_speed": 39.47, "wait_time": (4.14 / 2) if peak else (6.16 / 2)},
        "松山新店線": {"avg_speed": 39.47, "wait_time": (3.33 / 2) if peak else (6.11 / 2)},
        "中和新蘆線": {"avg_speed": 39.47, "wait_time": (4.46 / 2) if peak else (7.07 / 2)},
        "板南線": {"avg_speed": 39.47, "wait_time": (3.24 / 2) if peak else (4.53 / 2)},
        "預設": {"avg_speed": 39.47, "wait_time": 2.8},
    }

def match_mrt_wait_seconds(edge_data: dict, wait_table: dict[str, dict[str, float]]) -> float:
    """Return the matched MRT waiting time in seconds."""
    line_name = edge_data.get("line", edge_data.get("name", "預設"))
    matched_line = "預設"
    for line in wait_table:
        if line in str(line_name):
            matched_line = line
            break
    return wait_table[matched_line]["wait_time"] * 60.0
