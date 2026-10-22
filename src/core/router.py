from time import perf_counter
from typing import Any

import networkx as nx
from shapely.geometry import LineString

from .config import MAX_ROUTE_SNAP_DISTANCE_M
from .utils import haversine_distance_m

Coordinate = tuple[float, float]


class RoadDataUnavailableError(RuntimeError):
    pass


class SnapDistanceExceededError(ValueError):
    pass


class EvacRouter:
    """Find the shortest driving route while excluding flooded graph edges."""

    def __init__(
        self,
        graph: nx.Graph,
        max_snap_distance_m: float = MAX_ROUTE_SNAP_DISTANCE_M,
    ):
        self.graph = graph
        self.max_snap_distance_m = max_snap_distance_m

    @staticmethod
    def _node_coordinate(graph: nx.Graph, node: Any) -> Coordinate:
        data = graph.nodes[node]
        if "lat" in data and "lon" in data:
            return float(data["lat"]), float(data["lon"])
        if (
            isinstance(node, tuple)
            and len(node) == 2
            and all(isinstance(value, (int, float)) for value in node)
        ):
            return float(node[0]), float(node[1])
        raise ValueError(f"Node {node!r} has no geographic coordinates")

    def _find_nearest_node(
        self,
        graph: nx.Graph,
        coordinate: Coordinate,
    ) -> tuple[Any, float]:
        candidates = (node for node in graph.nodes if graph.degree(node) > 0)
        best_node = None
        best_distance = float("inf")

        for node in candidates:
            node_coordinate = self._node_coordinate(graph, node)
            distance = haversine_distance_m(coordinate, node_coordinate)
            if distance < best_distance:
                best_distance = distance
                best_node = node

        if best_node is None:
            raise RoadDataUnavailableError("Graf nie zawiera przejezdnych odcinków")
        if best_distance > self.max_snap_distance_m:
            raise SnapDistanceExceededError(
                "Punkt znajduje się zbyt daleko od pobranej sieci dróg "
                f"({best_distance:.0f} m; limit {self.max_snap_distance_m:.0f} m)"
            )
        return best_node, best_distance

    def _walkable_graph(self) -> nx.Graph:
        walkable = self.graph.__class__()
        walkable.graph.update(self.graph.graph)
        walkable.add_nodes_from(self.graph.nodes(data=True))

        if self.graph.is_multigraph():
            for source, target, key, data in self.graph.edges(keys=True, data=True):
                if not data.get("blocked", False):
                    walkable.add_edge(source, target, key=key, **data)
        else:
            for source, target, data in self.graph.edges(data=True):
                if not data.get("blocked", False):
                    walkable.add_edge(source, target, **data)
        return walkable

    @staticmethod
    def _edge_length(graph: nx.Graph, source: Any, target: Any) -> float:
        edge_data = graph.get_edge_data(source, target)
        if not edge_data:
            return 0.0
        if graph.is_multigraph():
            return min(float(attributes.get("length_m", 0.0)) for attributes in edge_data.values())
        return float(edge_data.get("length_m", 0.0))

    def find_route(
        self,
        start_coordinate: Coordinate,
        end_coordinate: Coordinate,
    ) -> tuple[LineString, dict[str, Any]] | None:
        started_at = perf_counter()
        if self.graph.number_of_edges() == 0:
            raise RoadDataUnavailableError("Graf nie zawiera przejezdnych odcinków")
        walkable = self._walkable_graph()
        if walkable.number_of_edges() == 0:
            return None

        # Anchor endpoints before removing flooded edges. Otherwise an isolated
        # origin silently jumps across the flood to a different road.
        start_node, start_snap_distance = self._find_nearest_node(self.graph, start_coordinate)
        end_node, end_snap_distance = self._find_nearest_node(self.graph, end_coordinate)

        try:
            path_nodes = nx.shortest_path(
                walkable,
                source=start_node,
                target=end_node,
                weight="length_m",
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

        route_coordinates = [
            tuple(reversed(self._node_coordinate(walkable, node))) for node in path_nodes
        ]
        if len(route_coordinates) == 1:
            route_coordinates.append(route_coordinates[0])

        total_length = sum(
            self._edge_length(walkable, source, target)
            for source, target in zip(path_nodes, path_nodes[1:], strict=False)
        )
        blocked_edges_count = len(
            {
                data["geometry"].normalize().wkb
                for _, _, data in self.graph.edges(data=True)
                if data.get("blocked", False) and data.get("geometry") is not None
            }
        )

        return LineString(route_coordinates), {
            "length_m": total_length,
            "segments": len(path_nodes) - 1,
            "calc_time_ms": round((perf_counter() - started_at) * 1000, 3),
            "blocked_edges_count": blocked_edges_count,
            "start_snap_distance_m": round(start_snap_distance, 2),
            "end_snap_distance_m": round(end_snap_distance, 2),
        }
