import math
from typing import List

import geopandas as gpd
import pyproj
from shapely.geometry import Point, LineString, Polygon
from shapely.geometry.multipolygon import MultiPolygon
from shapely.ops import nearest_points, unary_union

from app.data.dto.main.Coordinates import Coordinates
from app.services.db_service import DbService
from app.data.dto.searoute.SearoutePath import SearoutePath


class IslandProjection:
    def __init__(self, land_gdf: gpd.GeoDataFrame, sql_db: DbService, inland_km: float = 5.0):
        """
        land_gdf: GeoDataFrame with land polygons
        inland_km: distance to project inland along coast normal
        """
        self.land_gdf = land_gdf
        self.land_union = unary_union(land_gdf.geometry)  # merge all land polygons
        self.inland_km = inland_km
        self.geod = pyproj.Geod(ellps="WGS84")
        self.sql_db_service = sql_db

    # --- Coastline projection ---
    def _nearest_coast_point(self, sea_point: Point) -> Point:
        """
        Find the nearest point on the coastline (polygon boundary)
        """
        _, nearest_pt = nearest_points(sea_point, self.land_union)
        return nearest_pt

    def _move_inland_along_normal(self, coast_point: Point) -> Point:
        """
        Move inland along an approximate normal to the coast by inland_km
        Handles both Polygon and MultiPolygon
        """
        # find nearest polygon
        nearest_poly = min(self.land_gdf.geometry, key=lambda p: coast_point.distance(p))

        # pick the exterior of the nearest polygon
        if nearest_poly.geom_type == "Polygon":
            exterior = nearest_poly.exterior
        elif nearest_poly.geom_type == "MultiPolygon":
            # choose the sub-polygon whose exterior is nearest to coast_point
            nearest_subpoly = min(nearest_poly.geoms, key=lambda p: coast_point.distance(p))
            exterior = nearest_subpoly.exterior
        else:
            raise ValueError(f"Unsupported geometry type: {nearest_poly.geom_type}")

        # find nearest segment on exterior
        nearest_idx = min(
            range(len(exterior.coords) - 1),
            key=lambda i: Point(exterior.coords[i]).distance(coast_point)
        )
        x0, y0 = exterior.coords[nearest_idx]
        x1, y1 = exterior.coords[nearest_idx + 1]
        dx, dy = x1 - x0, y1 - y0

        # normal vector
        nx, ny = -dy, dx
        azimuth = math.degrees(math.atan2(ny, nx))

        # project inland along normal
        new_lon, new_lat, _ = self.geod.fwd(coast_point.x, coast_point.y, azimuth, self.inland_km * 1000)
        return Point(new_lon, new_lat)

    # --- Project route ---
    def project_route_to_coastline(self, sea_route_coords: List[Coordinates]) -> List[Point]:
        projected_points = []
        for c in sea_route_coords:
            sea_point = Point(c.longitude, c.latitude)
            coast_point = self._nearest_coast_point(sea_point)
            projected_points.append(coast_point)
        return projected_points

    def create_inland_buffers(self, projected_points: List[Point]) -> MultiPolygon:
        inland_polygons = []
        for pt in projected_points:
            inland_pt = self._move_inland_along_normal(pt)
            line = LineString([pt, inland_pt])
            buffer = line.buffer(1000)
            inland_polygons.append(buffer)
        merged = unary_union(inland_polygons)

        # ensure return type is MultiPolygon
        if isinstance(merged, Polygon):
            merged = MultiPolygon([merged])
        elif isinstance(merged, GeometryCollection):
            merged = MultiPolygon([g for g in merged.geoms if isinstance(g, Polygon)])

        return merged

    # --- Main job ---
    async def do_job(self, coordinates: List[Coordinates]):
        projected_points = self.project_route_to_coastline(coordinates)
        inland_strip = self.create_inland_buffers(projected_points)
        return await self.sql_db_service.search_ports_within_polygon(inland_strip.wkt, n=50)
