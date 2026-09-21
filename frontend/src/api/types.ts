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

export interface UploadedFileRecord {
  id: string
  dataset_id: string
  relative_path: string
  stored_path: string
  size_bytes: number
  media_type?: string | null
  metadata?: FileMetadata
  scan_error?: string | null
  created_at: string
}

export interface DatasetDetail extends Dataset {
  files: UploadedFileRecord[]
}

export interface UploadResponse {
  accepted: UploadedFileRecord[]
  rejected: Array<{
    name: string
    reason: string
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

export type ProcessingEngine = 'odm' | 'micmac' | 'gsplat' | 'telesculptor'
export type ProcessingProfile = 'preview' | 'standard' | 'high'

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
  status: string
  progress: number
  phase?: string | null
  message?: string | null
  artifacts?: Artifact[]
  created_at: string
  updated_at: string
}

export interface ServiceState {
  status: string
  profile?: string
  gpu?: boolean
  note?: string
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
