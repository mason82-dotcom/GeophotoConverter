export interface CameraMetadata {
  make?: string | null
  model?: string | null
  serial?: string | null
  lens?: string | null
}

export interface ImageMetadata {
  width?: number | null
  height?: number | null
  iso?: number | null
  f_number?: number | null
  focal_length?: number | null
  exposure_time?: number | null
}

export interface GpsMetadata {
  latitude?: number | null
  longitude?: number | null
  altitude?: number | null
}

export interface DjiMetadata {
  absolute_altitude?: number | null
  relative_altitude?: number | null
  flight_yaw?: number | null
  flight_pitch?: number | null
  flight_roll?: number | null
  gimbal_yaw?: number | null
  gimbal_pitch?: number | null
  gimbal_roll?: number | null
  rtk_flag?: string | number | boolean | null
  product_name?: string | null
  aircraft_type?: string | null
}

export interface FileMetadata {
  capture_time?: string | null
  camera?: CameraMetadata
  image?: ImageMetadata
  gps?: GpsMetadata
  dji?: DjiMetadata
}

export interface Dataset {
  id: string
  name: string
  description?: string | null
  created_at: string
  updated_at: string
  scan_status: string
  image_count?: number
  geotagged_count?: number
  geotagged_percent?: number
  processing_readiness?: string | boolean | null
  platform?: string | null
  duplicate_count?: number | null
}

export interface MediaClassification {
  platform: string
  media_kind: string
  capture_group?: string | null
  media_kind_source?: string
  capture_group_source?: string
  conflicts?: string[]
}

export interface UploadedFileRecord {
  id: string
  dataset_id: string
  relative_path: string
  stored_path: string
  size_bytes: number
  media_type?: string | null
  metadata?: FileMetadata
  scan_error?: string | null
  classification?: MediaClassification | null
  sha256?: string | null
  preview_url?: string | null
  created_at: string
}

export interface QaRange {
  count: number
  min: number | null
  max: number | null
}

export interface EngineReadiness {
  ready: boolean
  eligible_images: number
  complete_groups?: number
  platform?: string | null
  classification_conflict_files?: number
  classification_conflict_groups?: number
  blocking_conflicts?: number
  blocking_conflict_groups?: string[]
  reason: string | null
}

export interface DatasetQaWarning {
  code: string
  severity: string
  count: number
}

export interface MappingQaIssue {
  code: string
  severity: 'info' | 'warning' | 'error'
  count: number
  message: string
  [key: string]: unknown
}

export interface DatasetQa {
  image_count: number
  geotagged_count: number
  geotagged_percent: number
  platforms: Record<string, number>
  media_kinds: Record<string, number>
  camera_models: Record<string, number>
  altitude: {
    gps_m: QaRange
    relative_takeoff_m: QaRange
  }
  capture_period: {
    start: string | null
    end: string | null
    count: number
  }
  warnings: DatasetQaWarning[]
  engine_inputs: {
    rgb_wide: number
    thermal: number
    multispectral: number
    multispectral_groups: number
    complete_multispectral_groups: number
    multispectral_classification_conflicts: number
    thermal_groups: number
    complete_thermal_groups: number
  }
  mapping: {
    status: 'ready' | 'warning' | 'blocked'
    ready: boolean
    minimum_images: number
    eligible_images: number
    geotagged_images: number
    geotagged_percent: number
    missing_gps: number
    invalid_gps: number
    unique_positions: number
    duplicate_position_images: number
    position_extent_m: number | null
    rtk_metadata_images: number
    rtk_fixed_images: number
    orientation_metadata_images: number
    metadata_errors: number
    camera: {
      models: Record<string, number>
      model_count: number
      dimensions: Record<string, number>
      dimension_variants: number
      focal_length_mm: QaRange & { spread_percent: number | null }
    }
    altitude_consistency: {
      paired_absolute_relative: number
      takeoff_offset_m: QaRange
      takeoff_offset_spread_m: number | null
      nonpositive_relative_altitudes: number
    }
    orientation: {
      gimbal_pitch_images: number
      near_nadir_images: number
      oblique_images: number
      strongly_oblique_images: number
      max_nadir_deviation_deg: number | null
    }
    capture_time: {
      count: number
      missing: number
      duplicate_count: number
      span_seconds: number | null
    }
    issues: MappingQaIssue[]
    reason: string | null
  }
  thermal: {
    group_count: number
    complete_groups: number
    platform: string | null
  }
  multispectral: {
    required_media_kinds: string[]
    group_count: number
    complete_groups: number
    classification_conflicts: Record<string, number>
    conflict_file_count: number
    conflict_files: string[]
    conflict_group_count: number
    conflict_groups: string[]
    blocking_conflict_count: number
    blocking_conflict_groups: string[]
  }
  readiness: {
    odm: EngineReadiness
    micmac: EngineReadiness
    gsplat: EngineReadiness
    thermal: EngineReadiness
    odm_multispectral: EngineReadiness
  }
}

export interface DatasetDetail extends Dataset {
  files: UploadedFileRecord[]
  qa?: DatasetQa
}

export interface UploadResponse {
  accepted: UploadedFileRecord[]
  rejected: Array<{
    name: string
    reason: string
    duplicate_of?: string
    sha256?: string
  }>
}

export interface DatasetScanResponse {
  dataset: DatasetDetail
  scanned: number
  failed: number
}

export interface MapPack {
  id: string
  name: string
  group?: string
  default?: boolean
  filename: string
  installed: boolean
  size_bytes?: number | null
  minzoom?: number | null
  maxzoom?: number | null
  bounds?: [number, number, number, number] | null
  status?: string
}

export interface MapCatalog {
  format?: string
  attribution?: string
  license?: string
  packs: MapPack[]
}

export type ProcessingEngine = 'odm' | 'micmac' | 'gsplat' | 'thermal' | 'telesculptor'
export type ProcessingProfile = 'preview' | 'standard' | 'high'
export type ProcessingWorkflow = 'mapping' | 'reconstruction' | 'rgb' | 'multispectral' | 'thermal'

export interface ProcessingProfileDefinition {
  purpose?: string
  orthophoto_resolution_cm?: number
  max_steps?: number
}

export interface ProcessingOptionDefinition {
  type: 'number' | 'integer'
  minimum?: number
  minimum_exclusive?: number
  maximum?: number
  default?: number | null
  note?: string
}

export interface ProcessingWorkflowDefinition {
  key: ProcessingWorkflow
  title: string
  description?: string
  eligible_media_kinds?: string[]
  minimum_images?: number
  minimum_complete_groups?: number
  platforms?: string[]
  outputs?: string[]
  required_pair?: string[]
  temperature_space?: string
  wide_thermal_coregistered?: boolean
  georeferenced_temperature_raster?: boolean
  radiometric_calibration?: string
  camera_plus_sun?: {
    enabled: boolean
    reason?: string
  }
  options?: Record<string, ProcessingOptionDefinition>
  profiles: Partial<Record<ProcessingProfile, ProcessingProfileDefinition>>
}

export interface ProcessingEngineDefinition {
  key: ProcessingEngine
  title: string
  automated: boolean
  experimental?: boolean
  description?: string
  requires_gpu?: boolean
  requires_dji_tsdk?: boolean
  platforms?: string[]
  workflows: ProcessingWorkflowDefinition[]
}

export interface ProcessingCatalog {
  profiles: ProcessingProfile[]
  engines: ProcessingEngineDefinition[]
}

export interface Artifact {
  type: string
  name: string
  relative_path?: string
  size_bytes?: number
  download_url?: string
}

export interface Job {
  id: string
  dataset_id: string
  engine: ProcessingEngine
  profile: ProcessingProfile
  workflow?: ProcessingWorkflow
  options?: Record<string, number>
  status: string
  progress: number
  phase?: string | null
  message?: string | null
  artifacts?: Artifact[]
  created_at: string
  updated_at: string
}

export interface JobLogs {
  job_id: string
  lines: string[]
  available: boolean
}

export interface ServiceState {
  status: string
  profile?: string
  gpu?: boolean
  note?: string
  queue_depth?: number | null
  requires_dji_tsdk?: boolean
  platforms?: string[]
  wide_thermal_coregistered?: boolean
  georeferenced_temperature_raster?: boolean
}

export type ServicesResponse = Record<string, ServiceState>

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface PointCloudSource {
  job_id?: string
  artifact_index: number
  name: string
  type: string
  size_bytes?: number
  metadata_url: string
  preview_url: string
  download_url: string
}

export interface PointCloudListResponse {
  job_id: string
  pointclouds: PointCloudSource[]
}

export interface PointCloudBounds {
  min: [number, number, number]
  max: [number, number, number]
  center: [number, number, number]
  extent: [number, number, number]
}

export interface PointCloudMetadata {
  job_id: string
  artifact_index: number
  name: string
  type: string
  format: 'las' | 'laz' | 'ply'
  ply_encoding?: string
  point_count: number
  has_rgb: boolean
  dimensions: string[]
  bounds: PointCloudBounds
  source_size_bytes: number
  preview_url: string
  download_url: string
}

export interface PointCloudPreview {
  buffer: ArrayBuffer
  pointCount: number
  stride: number
  origin: [number, number, number]
  hasRgb: boolean
}
