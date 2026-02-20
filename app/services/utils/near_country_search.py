from typing import List

import geopandas as gpd
from shapely.geometry import LineString
from app.services.db_service import DbService
from app.data.dto.main.Coordinates import Coordinates

class RouteCountryFinder:
    def __init__(self, country_shapefile: str,  sql_db: DbService, buffer_km: float = 2500.0):
        """
        :param country_shapefile: Path to country polygons (e.g., Natural Earth shapefile)
        :param buffer_km: Distance in kilometers to consider "near" the route
        """
        self.buffer_km = buffer_km
        self.sql_db = sql_db

        # Load and project countries to metric CRS once (performance optimization)
        self.countries = gpd.read_file(country_shapefile).to_crs(epsg=3857)

        # Build spatial index once
        self.sindex = self.countries.sindex

    def find_country_codes(self, coordinates: List[Coordinates]):
        """
        :param polyline: list of (lon, lat) tuples
        :return: list of country names near the route
        """
        polyline = [(c.longitude, c.latitude) for c in coordinates]

        if not polyline or len(polyline) < 2:
            return []

        # Convert route to metric CRS
        line = LineString(polyline)
        line_metric = (
            gpd.GeoSeries([line], crs="EPSG:4326")
            .to_crs(epsg=3857)
            .iloc[0]
        )

        # Create buffer in meters
        buffer_geom = line_metric.buffer(self.buffer_km * 1000)

        # Spatial index pre-filter
        candidate_idx = list(self.sindex.intersection(buffer_geom.bounds))
        candidates = self.countries.iloc[candidate_idx]

        # Precise intersection
        intersected = candidates[candidates.intersects(buffer_geom)]

        # Return unique country names
        return intersected["ISO_A2"].unique().tolist()


    async def do_job(self,  coordinates: List[Coordinates]):
        country_codes = self.find_country_codes(coordinates)
        return await self.sql_db.get_ports_by_list_of_country_codes(country_codes)


# Example usage:
# finder = RouteCountryFinder("ne_10m_admin_0_countries.shp", buffer_km=100)
# polyline = [(-0.1276, 51.5074), (2.3522, 48.8566), (13.4050, 52.5200)]
# countries = finder.find_countries(polyline)
# print(countries)
