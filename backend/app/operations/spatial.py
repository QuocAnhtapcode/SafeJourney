"""Bounded spatial calculations and explicit, server-configured OSRM requests."""
from collections import Counter
import asyncio
import json
import math
from urllib.parse import urlsplit

import httpx

from .models import Coordinate

MAX_DISTANCE_M = 20_000_000
MAX_DURATION_S = 604_800
MAX_RESPONSE_BYTES = 2_000_000


class RoutingError(ValueError):
    """A route could not be verified; callers must not silently bless an estimate."""


def great_circle_route(origin: Coordinate | dict, destination: Coordinate | dict, speed_kmh=30) -> dict:
    start, end = Coordinate.model_validate(origin), Coordinate.model_validate(destination)
    if isinstance(speed_kmh, bool) or not isinstance(speed_kmh, (int, float)) or not math.isfinite(speed_kmh) or not 1 <= speed_kmh <= 130:
        raise ValueError('Tốc độ giả định phải hữu hạn trong 1–130 km/h')
    lat1, lat2 = math.radians(start.lat), math.radians(end.lat)
    dlat, dlon = lat2-lat1, math.radians(end.lon-start.lon)
    arc = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    distance = 6_371_008.8*2*math.asin(math.sqrt(min(1, max(0, arc))))
    return {'distance_m': round(distance, 3), 'duration_s': round(distance/(speed_kmh/3.6), 3),
            'source': 'great_circle_estimate', 'verified': False,
            'geometry': {'type': 'LineString', 'coordinates': [[start.lon, start.lat], [end.lon, end.lat]]},
            'assumptions': ['Khoảng cách đường chim bay và tốc độ giả định; chưa kiểm tra đường bộ, hướng đi hoặc giao thông.']}


def h3_aggregate(points: list[Coordinate | dict], resolution: int = 8) -> dict:
    if isinstance(resolution, bool) or not isinstance(resolution, int) or not 0 <= resolution <= 15:
        raise ValueError('Độ phân giải H3 phải là số nguyên từ 0 đến 15')
    if len(points) > 20_000:
        raise ValueError('Tối đa 20.000 điểm cho một lần tổng hợp')
    import h3
    normalized = [Coordinate.model_validate(point) for point in points]
    counts = Counter(h3.latlng_to_cell(point.lat, point.lon, resolution) for point in normalized)
    cells = []
    for cell, count in sorted(counts.items()):
        lat, lon = h3.cell_to_latlng(cell)
        cells.append({'cell': cell, 'count': count, 'center': {'lat': lat, 'lon': lon}})
    return {'resolution': resolution, 'point_count': len(points), 'cells': cells, 'source': 'h3-v4',
            'assumptions': ['Đếm điểm trong ô H3; chưa phải nhu cầu dự báo hoặc ranh giới hành chính.']}


def _number(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise RoutingError('OSRM trả số đo không hợp lệ')
    return float(value)


def _coordinate(value):
    if not isinstance(value, list) or len(value) != 2:
        raise RoutingError('OSRM trả tọa độ không hợp lệ')
    lon, lat = value
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise RoutingError('OSRM trả tọa độ không hợp lệ')
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise RoutingError('OSRM trả tọa độ ngoài phạm vi')
    return [float(lon), float(lat)]


class OSRMClient:
    """Only construct with trusted deployment configuration, never a request URL.

    No public host default, environment proxy, redirects, retry, or estimated
    fallback. `verified` means a validated routing-engine response, not that a
    road or a journey is currently safe.
    """

    def __init__(self, base_url: str, timeout_seconds=3, *, transport=None, max_snap_distance_m=500):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError('OSRM cần URL HTTP(S) cấu hình ở server, không có thông tin đăng nhập/query/fragment')
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not .1 <= timeout_seconds <= 10:
            raise ValueError('OSRM timeout phải từ 0,1 đến 10 giây')
        if isinstance(max_snap_distance_m, bool) or not isinstance(max_snap_distance_m, (int, float)) or not math.isfinite(max_snap_distance_m) or not 0 < max_snap_distance_m <= 5000:
            raise ValueError('Giới hạn khoảng cách ghép vào đường phải trong (0, 5000] m')
        self.base_url = base_url.rstrip('/')
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.max_snap_distance_m = max_snap_distance_m

    def _request(self, service, points, params):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._request_async(service, points, params))
        raise RoutingError('Tool OSRM đồng bộ cần chạy ngoài event loop, trong worker thread')

    async def _request_async(self, service, points, params):
        encoded = ';'.join(f'{point.lon:.7f},{point.lat:.7f}' for point in points)
        url = f'{self.base_url}/{service}/v1/driving/{encoded}'
        try:
            # A per-read timeout alone allows an endless trickle response. This
            # cancellation deadline covers connecting, headers and the full body.
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False, follow_redirects=False,
                                             transport=self.transport) as client:
                    async with client.stream('GET', url, params=params) as response:
                        if response.status_code != 200:
                            raise RoutingError('OSRM không trả phản hồi thành công')
                        data = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65_536):
                            data.extend(chunk)
                            if len(data) > MAX_RESPONSE_BYTES:
                                raise RoutingError('Phản hồi OSRM vượt giới hạn kích thước')
            payload = json.loads(data)
        except (TimeoutError, httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RoutingError('Không thể đọc kết quả OSRM; tuyến chưa được xác minh') from exc
        if not isinstance(payload, dict) or payload.get('code') != 'Ok':
            raise RoutingError('OSRM không tìm được kết quả hợp lệ')
        return payload

    def _waypoints(self, payload, key, expected):
        waypoints = payload.get(key)
        if not isinstance(waypoints, list) or len(waypoints) != len(expected):
            raise RoutingError('OSRM trả sai số điểm ghép vào đường')
        locations = []
        for item, original in zip(waypoints, expected):
            if not isinstance(item, dict):
                raise RoutingError('Điểm ghép vào đường không hợp lệ')
            location = _coordinate(item.get('location'))
            _number(item.get('distance'), self.max_snap_distance_m)
            snapped = {'lat': location[1], 'lon': location[0]}
            if great_circle_route(original, snapped)['distance_m'] > self.max_snap_distance_m+1:
                raise RoutingError('Điểm ghép OSRM cách quá xa tọa độ yêu cầu')
            locations.append(snapped)
        return locations

    def route(self, origin: Coordinate | dict, destination: Coordinate | dict) -> dict:
        points = [Coordinate.model_validate(origin), Coordinate.model_validate(destination)]
        payload = self._request('route', points, {'overview': 'full', 'geometries': 'geojson', 'steps': 'false', 'alternatives': 'false'})
        snapped = self._waypoints(payload, 'waypoints', points)
        routes = payload.get('routes')
        if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
            raise RoutingError('OSRM thiếu tuyến')
        route = routes[0]
        distance = _number(route.get('distance'), MAX_DISTANCE_M)
        duration = _number(route.get('duration'), MAX_DURATION_S)
        geometry = route.get('geometry')
        if not isinstance(geometry, dict) or geometry.get('type') != 'LineString':
            raise RoutingError('OSRM thiếu hình học tuyến GeoJSON')
        coordinates = geometry.get('coordinates')
        if not isinstance(coordinates, list) or not 2 <= len(coordinates) <= 50_000:
            raise RoutingError('OSRM trả hình học tuyến ngoài giới hạn')
        normalized = [_coordinate(value) for value in coordinates]
        for actual, expected in zip((normalized[0], normalized[-1]), snapped):
            if great_circle_route({'lat': actual[1], 'lon': actual[0]}, expected)['distance_m'] > 10:
                raise RoutingError('Đầu/cuối hình học OSRM không khớp điểm ghép')
        if distance+10 < great_circle_route(snapped[0], snapped[-1])['distance_m']:
            raise RoutingError('Khoảng cách tuyến OSRM ngắn hơn khoảng cách trực tiếp')
        if distance > 10 and duration == 0:
            raise RoutingError('OSRM trả thời gian bằng không cho tuyến có quãng đường')
        return {'distance_m': distance, 'duration_s': duration, 'source': 'osrm', 'verified': True,
                'geometry': {'type': 'LineString', 'coordinates': normalized},
                'assumptions': ['Đã kiểm tra cấu trúc/số đo của bộ định tuyến cấu hình; phụ thuộc bản đồ và profile của OSRM.',
                                'Không chứng minh an toàn đường, thời tiết hoặc thời gian giao thông thực tế.']}

    def table(self, origins: list[Coordinate | dict], destinations: list[Coordinate | dict]) -> dict:
        if not 1 <= len(origins) <= 100 or not 1 <= len(destinations) <= 100:
            raise ValueError('Ma trận OSRM cần 1–100 điểm mỗi phía')
        points = [Coordinate.model_validate(point) for point in [*origins, *destinations]]
        nv, nr = len(origins), len(destinations)
        payload = self._request('table', points, {'annotations': 'distance,duration',
            'sources': ';'.join(map(str, range(nv))), 'destinations': ';'.join(map(str, range(nv, nv+nr)))})
        sources = self._waypoints(payload, 'sources', points[:nv])
        destinations = self._waypoints(payload, 'destinations', points[nv:])
        if payload.get('fallback_speed_cells'):
            raise RoutingError('Ma trận có cạnh ước lượng thay thế; không thể đánh dấu đã xác minh')
        matrices = []
        for key, maximum in (('distances', MAX_DISTANCE_M), ('durations', MAX_DURATION_S)):
            matrix = payload.get(key)
            if not isinstance(matrix, list) or len(matrix) != nv or any(not isinstance(row, list) or len(row) != nr for row in matrix):
                raise RoutingError('OSRM trả ma trận sai kích thước')
            matrices.append([[None if v is None else _number(v, maximum) for v in row] for row in matrix])
        distances, durations = matrices
        if any((d is None) != (t is None) for ds, ts in zip(distances, durations) for d, t in zip(ds, ts)):
            raise RoutingError('OSRM trả cạnh không đi được không nhất quán')
        for i, (row_d, row_t) in enumerate(zip(distances, durations)):
            for j, (distance, duration) in enumerate(zip(row_d, row_t)):
                if distance is None:
                    continue
                if distance+10 < great_circle_route(sources[i], destinations[j])['distance_m']:
                    raise RoutingError('Khoảng cách ma trận OSRM ngắn hơn khoảng cách trực tiếp')
                if distance > 10 and duration == 0:
                    raise RoutingError('OSRM trả thời gian bằng không cho cạnh có quãng đường')
        return {'distance_matrix_m': distances, 'duration_matrix_s': durations, 'source': 'osrm', 'verified': True,
                'assumptions': ['null là cạnh không đi được; không thay bằng đường chim bay.',
                                'Thời gian theo profile/bản đồ OSRM, không mặc định có giao thông trực tiếp.']}
