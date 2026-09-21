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
}

export interface UploadedFileRecord {
  id: string
  dataset_id: string
  relative_path: string
  stored_path: string
  size_bytes: number
  media_type?: string | null
  metadata?: Record<string, unknown>
  scan_error?: string | null
  created_at: string
}

export interface UploadResponse {
  accepted: UploadedFileRecord[]
  rejected: Array<{
    name: string
    reason: string
  }>
}

export interface DatasetScanResponse {
  dataset: Dataset
  scanned: number
  failed: number
}

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
