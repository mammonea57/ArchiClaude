"use client";

import { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

export interface MapViewProps {
  center?: [number, number]; // [lng, lat]
  zoom?: number;
  onMapClick?: (lngLat: { lng: number; lat: number }) => void;
  parcels?: Array<{ geometry: GeoJSON.Geometry; selected?: boolean }>;
}

const IGN_TILES =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg";

export default function MapView({
  center = [2.35, 48.85],
  zoom = 12,
  onMapClick,
  parcels,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onClickRef = useRef(onMapClick);

  // Keep the click handler ref fresh without triggering re-initialisation
  useEffect(() => {
    onClickRef.current = onMapClick;
  }, [onMapClick]);

  // Initialise the map once
  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          ign: {
            type: "raster",
            tiles: [IGN_TILES],
            tileSize: 256,
            attribution: "© IGN",
          },
        },
        layers: [
          {
            id: "ign-layer",
            type: "raster",
            source: "ign",
          },
        ],
      },
      center,
      zoom,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("click", (e) => {
      if (onClickRef.current) {
        onClickRef.current({ lng: e.lngLat.lng, lat: e.lngLat.lat });
      }
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally only on mount

  // Fly to new center/zoom when props change
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.flyTo({ center, zoom, duration: 900 });
  }, [center, zoom]);

  // Sync parcel overlays
  const updateParcels = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    // Remove existing parcel layers/sources
    if (map.getLayer("parcels-fill")) map.removeLayer("parcels-fill");
    if (map.getLayer("parcels-stroke")) map.removeLayer("parcels-stroke");
    if (map.getLayer("parcels-fill-selected")) map.removeLayer("parcels-fill-selected");
    if (map.getLayer("parcels-stroke-selected")) map.removeLayer("parcels-stroke-selected");
    if (map.getSource("parcels")) map.removeSource("parcels");
    if (map.getSource("parcels-selected")) map.removeSource("parcels-selected");

    if (!parcels || parcels.length === 0) return;

    const regular = parcels.filter((p) => !p.selected);
    const selected = parcels.filter((p) => p.selected);

    if (regular.length > 0) {
      map.addSource("parcels", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: regular.map((p) => ({
            type: "Feature",
            geometry: p.geometry,
            properties: {},
          })),
        },
      });
      map.addLayer({
        id: "parcels-fill",
        type: "fill",
        source: "parcels",
        paint: { "fill-color": "#0d9488", "fill-opacity": 0.25 },
      });
      map.addLayer({
        id: "parcels-stroke",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#0d9488", "line-width": 1.5 },
      });
    }

    if (selected.length > 0) {
      map.addSource("parcels-selected", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: selected.map((p) => ({
            type: "Feature",
            geometry: p.geometry,
            properties: {},
          })),
        },
      });
      map.addLayer({
        id: "parcels-fill-selected",
        type: "fill",
        source: "parcels-selected",
        paint: { "fill-color": "#0f766e", "fill-opacity": 0.45 },
      });
      map.addLayer({
        id: "parcels-stroke-selected",
        type: "line",
        source: "parcels-selected",
        paint: { "line-color": "#134e4a", "line-width": 2.5 },
      });
    }
  }, [parcels]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (map.isStyleLoaded()) {
      updateParcels();
    } else {
      map.once("load", updateParcels);
    }
  }, [updateParcels]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full rounded-xl overflow-hidden"
      style={{ minHeight: 360 }}
    />
  );
}
