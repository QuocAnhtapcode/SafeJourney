import React, { memo, useEffect, useMemo, useRef, useState } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import { positionsGeoJSON, routeGeoJSON } from './journeyData.js';

const positionColor = () => ['case', ['<', ['get', 'observedAt'], Date.now() - 30000], '#e5a223', '#2563eb'];

function LiveMap({ trips, selectedTrip }) {
  const container = useRef(null), map = useRef(null), latest = useRef(null);
  const focused = useRef(null), selectedId = useRef(null);
  const [mapError, setMapError] = useState('');
  const token = import.meta.env.VITE_MAPBOX_TOKEN;
  const positions = useMemo(() => positionsGeoJSON(trips), [trips]);
  const route = useMemo(() => routeGeoJSON(selectedTrip), [selectedTrip]);
  latest.current = { positions, route };
  selectedId.current = selectedTrip?.id;
  useEffect(() => {
    if (!token || !container.current) return;
    let instance, freshnessTimer;
    try {
      instance = new mapboxgl.Map({ container: container.current, accessToken: token,
        style: 'mapbox://styles/mapbox/streets-v12', center: [106.7, 10.78], zoom: 12 });
      map.current = instance;
      instance.addControl(new mapboxgl.NavigationControl());
      instance.on('error', () => setMapError('Không tải được bản đồ. Kiểm tra token, quyền URL và mạng.'));
      instance.on('load', () => {
        // Route selection must not re-upload all vehicle positions to the worker.
        instance.addSource('journey-positions', { type: 'geojson', data: latest.current.positions });
        instance.addSource('journey-route', { type: 'geojson', data: latest.current.route });
        instance.addLayer({ id: 'routes', type: 'line', source: 'journey-route',
          paint: { 'line-color': '#64748b', 'line-width': 3 } });
        instance.addLayer({ id: 'positions', type: 'circle', source: 'journey-positions',
          paint: { 'circle-radius': 7, 'circle-color': positionColor(),
            'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
        instance.addLayer({ id: 'labels', type: 'symbol', source: 'journey-positions', minzoom: 13,
          layout: { 'text-field': ['get', 'label'], 'text-offset': [0, 1.5], 'text-size': 12 },
          paint: { 'text-halo-color': '#fff', 'text-halo-width': 2 } });
        // Age the last known location even while REST/WebSocket are unavailable.
        // Updating the paint expression avoids rebuilding GeoJSON each tick.
        freshnessTimer = setInterval(() => {
          if (instance.getLayer('positions')) instance.setPaintProperty('positions', 'circle-color', positionColor());
        }, 1000);
        const point = latest.current.positions.features.find(f => f.id === selectedId.current)
          || latest.current.positions.features[0];
        if (point) instance.jumpTo({ center: point.geometry.coordinates });
      });
    } catch { setMapError('Trình duyệt chưa hỗ trợ bản đồ WebGL hoặc token không hợp lệ.'); }
    return () => { clearInterval(freshnessTimer); instance?.remove(); map.current = null; };
  }, [token]);
  useEffect(() => { map.current?.getSource('journey-positions')?.setData(positions); }, [positions]);
  useEffect(() => { map.current?.getSource('journey-route')?.setData(route); }, [route]);
  useEffect(() => {
    if (!selectedTrip) { focused.current = null; return; }
    if (focused.current !== selectedTrip.id) {
      const current = positions.features.find(point => point.id === selectedTrip.id);
      if (current) {
        map.current?.jumpTo({ center: current.geometry.coordinates, zoom: 14 });
        focused.current = selectedTrip.id;
      }
    }
  }, [positions, selectedTrip]);
  return <>
    <div className="map" ref={container}/>
    {mapError && <p role="alert" className="error">{mapError}</p>}
    <p><small>Bản đồ hiển thị mọi xe trong phạm vi danh sách đã chọn, độc lập với trang bảng bên dưới. Chỉ vẽ tuyến của chuyến đang chọn để giữ bản đồ dễ đọc.</small></p>
  </>;
}

export default memo(LiveMap);
