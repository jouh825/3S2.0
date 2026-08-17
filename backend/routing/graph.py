"""Graph construction and edge attribute injection from the notebook."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any
import networkx as nx

from backend.config import get_settings
from backend.routing.fare import bus_fare, mrt_fare, taxi_fare, train_fare, ubike_fare
from backend.routing.waiting_time import match_mrt_wait_seconds, mrt_wait_minutes
from backend.routing.walking_speed import calculate_walk_speed, fare_identity

# =====================================================================
# 🛡️ 【使用者自訂區域：各運具之環境安全係數】 (User-modifiable Safety Coefficients)
# =====================================================================
#環境風險敏感加權係數：定義不同運具對安全風險（如路燈明亮度、治安/事故率）的敏感程度，分數越高表越相對不安全
SAFETY_COEFFICIENTS = {
    "walking": 1.0,        # 步行安全敏感係數
    "walk": 1.0,
    "ubike": 1.0,          # YouBike 安全敏感係數
    "youbike": 1.0,
    "mrt": 0.0,            # 捷運
    "train": 0.0,          # 火車
    "bus": 0.5,            # 公車安全敏感係數
    "car": 0.5,            # 汽車安全敏感係數
    "scooter": 0.8,        # 機車安全敏感係數
    "motorcycle": 0.8,
    "taxi": 0.5,           # 計程車安全敏感係數
}
# =====================================================================

@dataclass
class RoutingGraphs:
    """Container for Taipei multimodal graphs."""
    drive: nx.MultiDiGraph
    rail: nx.MultiDiGraph
    walk: nx.MultiDiGraph
    di_graphs: dict[str, nx.DiGraph] = None


def build_graphs() -> RoutingGraphs:
    """Load cached graphs or build Taipei graphs with the notebook method."""
    settings = get_settings()
    cached = load_cached_graphs(settings.graph_cache_dir)
    if cached:
        prebuild_all_di_graphs(cached)
        return cached
    if not settings.allow_osm_download:
        demo = build_demo_graphs()
        prebuild_all_di_graphs(demo)
        return demo
    try:
        graphs = download_osmnx_graphs(settings.taipei_center, settings.search_dist_m)
        save_cached_graphs(graphs, settings.graph_cache_dir)
        prebuild_all_di_graphs(graphs)
        return graphs
    except Exception as e:
        print(f"[Error] Failed to build Taipei graphs: {e}")
        demo = build_demo_graphs()
        prebuild_all_di_graphs(demo)
        return demo


def load_cached_graphs(cache_dir: Path) -> RoutingGraphs | None:
    """Load GraphML cache if present (checks both .graphml and .graphml.gz)."""
    paths = {}
    for name in ("drive", "rail", "walk"):
        gz_path = cache_dir / f"{name}.graphml.gz"
        if gz_path.exists():
            paths[name] = gz_path
        else:
            paths[name] = cache_dir / f"{name}.graphml"
            
    if not all(path.exists() for path in paths.values()):
        return None
    try:
        import osmnx as ox
        drive = ox.load_graphml(paths["drive"])
        rail = ox.load_graphml(paths["rail"])
        walk = ox.load_graphml(paths["walk"])
        
        # Verify if precalculated bike speed is cached on the edges.
        # If absent (first migration run), calculate and write it back.
        has_precalc = False
        for _, _, data in walk.edges(data=True):
            if "precalc_bike_speed" in data:
                has_precalc = True
                break
                
        if not has_precalc and walk.number_of_edges() > 0:
            print("=== [Warmup] Pre-calculating YouBike speeds on walk edges (running once) ===")
            precalculate_bike_speeds(walk)
            print("=== [Warmup] Saving YouBike precalculated speeds back to GraphML cache ===")
            ox.save_graphml(walk, paths["walk"])
            
        return RoutingGraphs(drive=drive, rail=rail, walk=walk)
    except Exception as e:
        print(f"[Error] Failed to load cached GraphML graphs: {e}")
        return None


def save_cached_graphs(graphs: RoutingGraphs, cache_dir: Path) -> None:
    """Save graphs to GraphML cache."""
    try:
        import osmnx as ox
        ox.save_graphml(graphs.drive, cache_dir / "drive.graphml")
        ox.save_graphml(graphs.rail, cache_dir / "rail.graphml")
        ox.save_graphml(graphs.walk, cache_dir / "walk.graphml")
    except Exception as e:
        print(f"[Error] Failed to save GraphML cache: {e}")


def download_osmnx_graphs(center: tuple[float, float], dist: int) -> RoutingGraphs:
    """Build Taipei graphs using the notebook's OSMnx graph_from_point calls."""
    import networkx as nx_local
    import osmnx as ox

    print(f"=== [OSM] Downloading Taipei drive, rail, and walk networks with radius {dist}m ===")
    drive = ox.graph_from_point(center, dist=dist, network_type="drive")
    rail = ox.graph_from_point(center, dist=dist, custom_filter='["railway"~"subway|rail|light_rail"]')
    walk = ox.graph_from_point(center, dist=dist, network_type="walk")
    
    print("=== [OSM] Isolating strongly connected components ===")
    drive = keep_largest_strong_component(drive, nx_local)
    rail = keep_largest_strong_component(rail, nx_local)
    walk = keep_largest_strong_component(walk, nx_local)
    
    print("=== [OSM] Pre-calculating YouBike wind-resistance speeds ===")
    precalculate_bike_speeds(walk)
    
    return RoutingGraphs(drive=drive, rail=rail, walk=walk)


def keep_largest_strong_component(graph: nx.MultiDiGraph, nx_module: Any = nx) -> nx.MultiDiGraph:
    """Keep the largest strongly connected component, matching the notebook."""
    nodes = max(nx_module.strongly_connected_components(graph), key=len)
    return graph.subgraph(nodes).copy()


def precalculate_bike_speeds(graph: nx.MultiDiGraph) -> None:
    """Assign YouBike speed based on OSM highway tag (Heuristic Speed Table)."""
    for _, _, _, data in graph.edges(data=True, keys=True):
        highway = data.get("highway", "residential")
        if isinstance(highway, list):
            highway = highway[0] if highway else "residential"
        highway = str(highway).lower()
        
        if highway == "cycleway":
            speed_kmh = 18.0
        elif highway == "residential":
            speed_kmh = 15.0
        else:
            speed_kmh = 12.0
            
        # Store in meters per second
        data["precalc_bike_speed"] = speed_kmh * 1000 / 3600


def prebuild_all_di_graphs(graphs: RoutingGraphs) -> None:
    """Pre-build simple DiGraphs for all vehicles to completely bypass request-time loops."""
    print("=== [Warmup] Pre-building multimodal DiGraphs for fast routing ===")
    graphs.di_graphs = {}
    
    # 1. Run all base attribute injections once
    inject_safety_defaults(graphs)
    inject_drive_edges(graphs.drive, identity="adult")
    
    # Precalculate walk travel times for a baseline speed of 1.34 m/s (4.8 km/h)
    # The shortest path remains identical regardless of walking speed, as walk_speed is a constant factor.
    inject_walk_edges(graphs.walk, identity="adult", walk_speed=1.34)
    
    # 2. Build simple DiGraphs for static modes
    graphs.di_graphs["walking"] = build_mode_digraph(graphs.walk, "walk")
    graphs.di_graphs["ubike"] = build_mode_digraph(graphs.walk, "youbike")
    graphs.di_graphs["car"] = build_mode_digraph(graphs.drive, "car")
    graphs.di_graphs["taxi"] = build_mode_digraph(graphs.drive, "taxi")
    graphs.di_graphs["bus"] = build_mode_digraph(graphs.drive, "bus")
    
    # Scooter graph: uses filtered drive network excluding motorway/trunk
    scooter_sub = get_filtered_drive_subgraph(graphs.drive, "motorcycle")
    graphs.di_graphs["scooter"] = build_mode_digraph(scooter_sub, "motorcycle")
    
    # 3. Build simple DiGraphs for MRT and Train for the 3 distinct travel periods (peak, offpeak, night)
    for period in ["peak", "offpeak", "night"]:
        wait_table = mrt_wait_minutes(period)
        
        # MRT
        mrt_multi = get_filtered_rail_subgraph(graphs.rail, "mrt")
        inject_rail_edges(mrt_multi, "adult", wait_table)
        graphs.di_graphs[f"mrt_{period}"] = build_mode_digraph(mrt_multi, "mrt")
        
        # Train
        train_multi = get_filtered_rail_subgraph(graphs.rail, "train")
        inject_rail_edges(train_multi, "adult", wait_table)
        graphs.di_graphs[f"train_{period}"] = build_mode_digraph(train_multi, "train")
        
    print(f"=== [Warmup] Pre-building complete! {len(graphs.di_graphs)} routing tables loaded ===")


def build_mode_digraph(graph: nx.MultiDiGraph, mode: str) -> nx.DiGraph:
    """Flatten a MultiDiGraph to a DiGraph by keeping the best edge based on mode-specific travel time."""
    result = nx.DiGraph()
    result.graph["crs"] = graph.graph.get("crs", "EPSG:4326")
    # Copy node coordinate attributes needed for distance and rendering
    for node, data in graph.nodes(data=True):
        result.add_node(node, y=data["y"], x=data["x"])
        
    time_key = f"pure_time_{mode}"
    safety_key = f"safety_cost_{mode}"
    safety_coef = SAFETY_COEFFICIENTS.get(mode, 1.0)
    
    for u, v, edge_data in graph.edges(data=True):
        # Apply strict YouBike road rights constraints: skip freeways & expressways
        if mode == "youbike":
            highway = edge_data.get("highway", "residential")
            if isinstance(highway, list):
                highway = highway[0] if highway else "residential"
            highway = str(highway).lower()
            if highway in ["motorway", "motorway_link", "trunk", "trunk_link"]:
                continue
                
        time_value = edge_data.get(time_key)
        if time_value is None:
            # Fallback to travel time based on length and 30 km/h default speed (8.33 m/s)
            length_m = float(edge_data.get("length", 1.0))
            time_value = length_m / (30.0 * 1000 / 3600)
        else:
            time_value = float(time_value)
            
        safety_val = float(edge_data.get(safety_key, 0.0)) * safety_coef
        
        # Base weight minimizes travel time adjusted by safety risks
        base_weight = time_value * (1.0 + safety_val)
        
        if result.has_edge(u, v) and result[u][v]["weight"] <= base_weight:
            continue
            
        result.add_edge(
            u, v,
            weight=base_weight,
            length=float(edge_data.get("length", 1.0)),
            pure_time=time_value,
            safety_cost=float(edge_data.get(safety_key, 0.0))
        )
    return result


def get_filtered_rail_subgraph(graph: nx.MultiDiGraph, mode: str) -> nx.MultiDiGraph:
    """Return a subgraph of the rail network filtered for either MRT or Train edges."""
    valid_edges = []
    for u, v, k, data in graph.edges(data=True, keys=True):
        railway = data.get("railway")
        
        # Infer railway type from name if the tag is missing
        if railway is None or str(railway).strip() == "" or str(railway) == "nan":
            name = str(data.get("name", "")).lower()
            if any(k in name for k in ["台鐵", "台灣鐵路", "縱貫", "tra", "train", "rail"]):
                railway = "rail"
            else:
                railway = "subway"
                
        if isinstance(railway, list):
            railway = railway[0] if railway else "subway"
        railway = str(railway).lower()
        
        if mode == "mrt":
            if railway in ["subway", "light_rail"] or "subway" in railway:
                valid_edges.append((u, v, k))
        elif mode == "train":
            if railway in ["rail"] or "rail" in railway:
                valid_edges.append((u, v, k))
                
    return graph.edge_subgraph(valid_edges).copy()


def get_filtered_drive_subgraph(graph: nx.MultiDiGraph, mode: str) -> nx.MultiDiGraph:
    """Return a subgraph of the drive network filtered for Scooter (motorcycle)."""
    valid_edges = []
    for u, v, k, data in graph.edges(data=True, keys=True):
        highway = data.get("highway", "")
        if isinstance(highway, list):
            highway = highway[0] if highway else ""
        highway = str(highway).lower()
        
        # Scooter is banned on motorways and expressways (trunk) in Taiwan
        if mode == "motorcycle":
            if highway in ["motorway", "motorway_link", "trunk", "trunk_link"]:
                continue
        valid_edges.append((u, v, k))
        
    return graph.edge_subgraph(valid_edges).copy()


def prepare_graphs(
    graphs: RoutingGraphs,
    age: int,
    gender: str,
    weight: float,
    walk_multiplier: float,
    travel_period: str,
    wind_speed: float = 2.5,
    wind_direction: float = 90.0,
) -> RoutingGraphs:
    """Prepare graphs (identity and attributes are now preloaded, this function returns instantly)."""
    # Attribute injections are run once during startup warmups to eliminate request latency
    return graphs


def inject_drive_edges(graph: nx.MultiDiGraph, identity: str) -> None:
    """Inject car, motorcycle, taxi, and bus time/fare attributes based on highway class."""
    for _, _, _, data in graph.edges(data=True, keys=True):
        length_m = float(data.get("length", 1.0))
        length_km = length_m / 1000.0
        
        highway = data.get("highway", "residential")
        if isinstance(highway, list):
            highway = highway[0] if highway else "residential"
        highway = str(highway).lower()
        
        # Define speeds in km/h based on highway type to route like Google Maps
        if highway == "motorway":
            car_speed = 80.0
        elif highway == "trunk":
            car_speed = 65.0
        elif highway == "primary":
            car_speed = 48.66
        elif highway == "secondary":
            car_speed = 37.86
        elif highway == "tertiary":
            car_speed = 32.44
        elif highway in ["residential", "unclassified"]:
            car_speed = 19.46
        elif highway in ["living_street", "service"]:
            car_speed = 10.81
        else:
            car_speed = 16.22
            
        if highway == "primary":
            scooter_speed = 47.25
        elif highway == "secondary":
            scooter_speed = 41.34
        elif highway == "tertiary":
            scooter_speed = 35.44
        elif highway in ["residential", "unclassified"]:
            scooter_speed = 23.63
        elif highway in ["living_street", "service"]:
            scooter_speed = 14.18
        else:
            scooter_speed = 17.72
            
        taxi_speed = car_speed
        
        if highway == "primary":
            bus_speed = 34.18
        elif highway == "secondary":
            bus_speed = 27.34
        elif highway in ["tertiary", "residential", "unclassified"]:
            bus_speed = 20.51
        else:
            bus_speed = 13.67
            
        data["pure_time_car"] = seconds_by_speed(length_m, car_speed)
        data["pure_fare_car"] = length_km * 3.5
        
        data["pure_time_motorcycle"] = seconds_by_speed(length_m, scooter_speed)
        data["pure_fare_motorcycle"] = length_km * 0.8
        
        data["pure_time_taxi"] = seconds_by_speed(length_m, taxi_speed)
        data["pure_fare_taxi"] = taxi_fare(length_km)
        
        data["pure_time_bus"] = seconds_by_speed(length_m, bus_speed)
        data["pure_fare_bus"] = bus_fare(identity)


def inject_rail_edges(graph: nx.MultiDiGraph, identity: str, wait_table: dict) -> None:
    """Inject MRT and train time/fare attributes."""
    for _, _, _, data in graph.edges(data=True, keys=True):
        length_m = float(data.get("length", 1.0))
        length_km = length_m / 1000.0
        run_time_mrt = seconds_by_speed(length_m, 39.47)
        data["pure_time_mrt"] = run_time_mrt + match_mrt_wait_seconds(data, wait_table)
        data["pure_fare_mrt"] = mrt_fare(length_km, identity)
        data["pure_time_train"] = seconds_by_speed(length_m, 50.00)
        data["pure_fare_train"] = train_fare(length_km, identity)


def inject_walk_edges(
    graph: nx.MultiDiGraph,
    identity: str,
    walk_speed: float,
) -> None:
    """Inject walk and YouBike attributes using precalculated speeds to avoid slow loops."""
    for _, _, _, data in graph.edges(data=True, keys=True):
        length_m = float(data.get("length", 1.0))
        data["pure_time_walk"] = seconds_by_speed(length_m, walk_speed)
        
        # Use precalculated bike speed (avoiding Newton iterations)
        bike_ms = 12.0 * 1000 / 3600
        data["pure_time_youbike"] = length_m / bike_ms
        data["pure_fare_walk"] = 0.0
        data["pure_fare_youbike"] = ubike_fare(data["pure_time_youbike"] / 60.0, identity)


def seconds_by_speed(length_m: float, speed_kmh: float) -> float:
    """Convert edge length and km/h speed to seconds."""
    return length_m / (speed_kmh * 1000 / 3600)


# =====================================================================
# 🛡️ 【使用者自訂區域：安全係數 (環境風險值) 注入與初始化】
# =====================================================================
def inject_safety_defaults(graphs: RoutingGraphs) -> None:
    """
    Preserve safety-cost attributes, using neutral defaults if data is absent.
    """
    for _, _, _, data in graphs.walk.edges(data=True, keys=True):
        data.setdefault("safety_cost_walk", 0.0)
        data.setdefault("safety_cost_youbike", 0.0)
        
    for _, _, _, data in graphs.drive.edges(data=True, keys=True):
        data.setdefault("safety_cost_bus", 0.0)
        data.setdefault("safety_cost_car", 0.0)
        data.setdefault("safety_cost_motorcycle", 0.0)
        
    for _, _, _, data in graphs.rail.edges(data=True, keys=True):
        data.setdefault("safety_cost_mrt", 0.0)
        data.setdefault("safety_cost_train", 0.0)
# =====================================================================


def build_demo_graphs() -> RoutingGraphs:
    """Build a tiny Taipei-shaped fallback graph for local smoke tests."""
    drive = build_demo_graph("drive", 8)
    rail = build_demo_graph("rail", 5)
    walk = build_demo_graph("walk", 10)
    
    # Precalculate bike speed for walk demo graph
    for _, _, data in walk.edges(data=True):
        data["precalc_bike_speed"] = 12.0 * 1000 / 3600
        
    return RoutingGraphs(drive=drive, rail=rail, walk=walk)


def build_demo_graph(name: str, count: int) -> nx.MultiDiGraph:
    """Create a deterministic fallback MultiDiGraph."""
    graph = nx.MultiDiGraph(name=name, crs="EPSG:4326")
    for index in range(count):
        graph.add_node(index, y=25.02 + index * 0.006, x=121.50 + index * 0.008)
    for index in range(count - 1):
        length = 900 + index * 120
        edge_attrs = {"length": length, "name": f"{name}-{index}"}
        if name == "rail":
            edge_attrs["railway"] = "subway" if index % 2 == 0 else "rail"
        graph.add_edge(index, index + 1, **edge_attrs)
        
        edge_attrs_r = {"length": length, "name": f"{name}-{index}-r"}
        if name == "rail":
            edge_attrs_r["railway"] = "subway" if index % 2 == 0 else "rail"
        graph.add_edge(index + 1, index, **edge_attrs_r)
    add_demo_shortcuts(graph, count)
    return graph


def add_demo_shortcuts(graph: nx.MultiDiGraph, count: int) -> None:
    """Add alternative paths so top-three routing has candidates."""
    for index in range(count - 2):
        edge_attrs = {"length": 1900 + index * 140, "name": f"shortcut-{index}"}
        if graph.name == "rail":
            edge_attrs["railway"] = "subway" if index % 2 == 0 else "rail"
        graph.add_edge(index, index + 2, **edge_attrs)
        
        edge_attrs_r = {"length": 1900 + index * 140, "name": f"shortcut-{index}-r"}
        if graph.name == "rail":
            edge_attrs_r["railway"] = "subway" if index % 2 == 0 else "rail"
        graph.add_edge(index + 2, index, **edge_attrs_r)
