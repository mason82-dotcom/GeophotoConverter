import maplibregl, { type GeoJSONSource, type StyleSpecification } from 'maplibre-gl'
import { useEffect, useMemo, useRef } from 'react'
import type { UploadedFileRecord } from '../api/types'

interface CaptureMapProps {
  files: UploadedFileRecord[]
  mapPackId?: string
  selectedId?: string
  onSelect: (fileId: string) => void
}

const OSM_ATTRIBUTION = '© OpenStreetMap contributors'

function baseStyle(mapPackId?: string): StyleSpecification {
  const sources: StyleSpecification['sources'] = {
    flightline: {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    },
    captures: {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    },
  }

  const layers: StyleSpecification['layers'] = [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#08111f' },
    },
  ]

  if (mapPackId) {
    sources.offline = {
      type: 'vector',
      url: `/api/v1/maps/${encodeURIComponent(mapPackId)}/tilejson.json`,
      attribution: OSM_ATTRIBUTION,
    }

    layers.push(
      {
        id: 'land',
        type: 'fill',
        source: 'offline',
        'source-layer': 'land',
        paint: { 'fill-color': '#13271f', 'fill-opacity': 0.78 },
      },
      {
        id: 'sites',
        type: 'fill',
        source: 'offline',
        'source-layer': 'sites',
        paint: { 'fill-color': '#1c2a38', 'fill-opacity': 0.7 },
      },
      {
        id: 'ocean',
        type: 'fill',
        source: 'offline',
        'source-layer': 'ocean',
        paint: { 'fill-color': '#09263b' },
      },
      {
        id: 'water',
        type: 'fill',
        source: 'offline',
        'source-layer': 'water_polygons',
        paint: { 'fill-color': '#0d314b', 'fill-opacity': 0.95 },
      },
      {
        id: 'buildings',
        type: 'fill',
        source: 'offline',
        'source-layer': 'buildings',
        minzoom: 13,
        paint: { 'fill-color': '#2d3a48', 'fill-opacity': 0.82 },
      },
      {
        id: 'boundaries',
        type: 'line',
        source: 'offline',
        'source-layer': 'boundaries',
        paint: {
          'line-color': '#66788c',
          'line-width': 1,
          'line-dasharray': [3, 3],
          'line-opacity': 0.6,
        },
      },
      {
        id: 'streets',
        type: 'line',
        source: 'offline',
        'source-layer': 'streets',
        paint: {
          'line-color': '#5a6879',
          'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.5, 11, 1.2, 15, 2.6],
          'line-opacity': 0.86,
        },
      },
    )
  }

  layers.push(
    {
      id: 'flightline',
      type: 'line',
      source: 'flightline',
      paint: {
        'line-color': '#5cc8ff',
        'line-width': 1.5,
        'line-opacity': 0.48,
      },
    },
    {
      id: 'capture-points',
      type: 'circle',
      source: 'captures',
      paint: {
        'circle-radius': ['case', ['==', ['get', 'selected'], true], 7, 4.5],
        'circle-color': ['case', ['==', ['get', 'selected'], true], '#f2bd5b', '#5cc8ff'],
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#07111d',
      },
    },
  )

  return {
    version: 8,
    sources,
    layers,
  }
}

export function CaptureMap({ files, mapPackId, selectedId, onSelect }: CaptureMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map>()
  const lastFitKeyRef = useRef('')

  const positionedFiles = useMemo(
    () =>
      files.filter(
        (file) =>
          file.metadata?.gps?.longitude != null && file.metadata?.gps?.latitude != null,
      ),
    [files],
  )

  useEffect(() => {
    if (!containerRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: baseStyle(mapPackId),
      center: [9.1, 48.8],
      zoom: 7,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: OSM_ATTRIBUTION,
      }),
      'bottom-right',
    )

    map.on('click', 'capture-points', (event) => {
      const id = event.features?.[0]?.properties?.fileId
      if (typeof id === 'string') onSelect(id)
    })
    map.on('mouseenter', 'capture-points', () => {
      map.getCanvas().style.cursor = 'pointer'
    })
    map.on('mouseleave', 'capture-points', () => {
      map.getCanvas().style.cursor = ''
    })

    mapRef.current = map
    lastFitKeyRef.current = ''
    return () => {
      map.remove()
      mapRef.current = undefined
    }
  }, [mapPackId, onSelect])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const points = {
      type: 'FeatureCollection' as const,
      features: positionedFiles.map((file) => ({
        type: 'Feature' as const,
        properties: {
          fileId: file.id,
          selected: file.id === selectedId,
        },
        geometry: {
          type: 'Point' as const,
          coordinates: [
            file.metadata!.gps!.longitude as number,
            file.metadata!.gps!.latitude as number,
          ],
        },
      })),
    }

    const line = {
      type: 'FeatureCollection' as const,
      features:
        positionedFiles.length > 1
          ? [
              {
                type: 'Feature' as const,
                properties: {},
                geometry: {
                  type: 'LineString' as const,
                  coordinates: positionedFiles.map((file) => [
                    file.metadata!.gps!.longitude as number,
                    file.metadata!.gps!.latitude as number,
                  ]),
                },
              },
            ]
          : [],
    }

    const syncSources = () => {
      ;(map.getSource('captures') as GeoJSONSource | undefined)?.setData(points)
      ;(map.getSource('flightline') as GeoJSONSource | undefined)?.setData(line)

      const fitKey = positionedFiles.map((file) => file.id).join('|')
      if (positionedFiles.length && fitKey !== lastFitKeyRef.current) {
        const bounds = new maplibregl.LngLatBounds()
        positionedFiles.forEach((file) => {
          bounds.extend([
            file.metadata!.gps!.longitude as number,
            file.metadata!.gps!.latitude as number,
          ])
        })
        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, {
            padding: 56,
            maxZoom: 17,
            duration: 0,
          })
        }
        lastFitKeyRef.current = fitKey
      }
    }

    if (map.isStyleLoaded()) syncSources()
    else map.once('load', syncSources)
  }, [positionedFiles, selectedId])

  return (
    <div className="map-frame">
      <div ref={containerRef} className="capture-map" aria-label="Dataset capture map" />
      {!positionedFiles.length && (
        <div className="map-overlay-message">No geotagged capture points in this dataset.</div>
      )}
      {!mapPackId && (
        <div className="map-pack-warning">
          Offline basemap not installed. Capture geometry remains available.
        </div>
      )}
    </div>
  )
}
