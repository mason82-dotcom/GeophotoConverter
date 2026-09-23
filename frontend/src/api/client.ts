import type {
  Dataset,
  DatasetDetail,
  DatasetQa,
  DatasetScanResponse,
  Job,
  JobLogs,
  MapCatalog,
  ProcessingCatalog,
  ProcessingEngine,
  ProcessingProfile,
  ProcessingWorkflow,
  PointCloudListResponse,
  PointCloudMetadata,
  PointCloudPreview,
  ServicesResponse,
  UploadResponse,
} from './types'
import { ApiError } from './types'

const API_BASE = '/api/v1'

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: unknown
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new ApiError(`Anfrage fehlgeschlagen (Status ${response.status})`, response.status, detail)
  }
  return response.json() as Promise<T>
}

export async function listDatasets(): Promise<Dataset[]> {
  return readJson<Dataset[]>(await fetch(`${API_BASE}/datasets`))
}

export async function getDataset(datasetId: string): Promise<DatasetDetail> {
  return readJson<DatasetDetail>(
    await fetch(`${API_BASE}/datasets/${encodeURIComponent(datasetId)}`),
  )
}

export async function getDatasetQa(datasetId: string): Promise<DatasetQa> {
  return readJson<DatasetQa>(
    await fetch(`${API_BASE}/datasets/${encodeURIComponent(datasetId)}/qa`),
  )
}

export async function createDataset(name: string, description?: string): Promise<Dataset> {
  const response = await fetch(`${API_BASE}/datasets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      description: description?.trim() || undefined,
    }),
  })
  return readJson<Dataset>(response)
}

export async function scanDataset(datasetId: string): Promise<DatasetScanResponse> {
  const response = await fetch(`${API_BASE}/datasets/${encodeURIComponent(datasetId)}/scan`, {
    method: 'POST',
  })
  return readJson<DatasetScanResponse>(response)
}

export async function listMapPacks(): Promise<MapCatalog> {
  return readJson<MapCatalog>(await fetch(`${API_BASE}/maps`))
}

export interface HealthResponse {
  status: string
  redis?: string
  version?: string
}

export async function getHealth(): Promise<HealthResponse> {
  return readJson<HealthResponse>(await fetch(`${API_BASE}/health`))
}

export async function getServices(): Promise<ServicesResponse> {
  return readJson<ServicesResponse>(await fetch(`${API_BASE}/services`))
}

export async function getProcessingCatalog(): Promise<ProcessingCatalog> {
  return readJson<ProcessingCatalog>(await fetch(`${API_BASE}/processing/profiles`))
}

export async function listJobs(): Promise<Job[]> {
  return readJson<Job[]>(await fetch(`${API_BASE}/jobs`))
}

export async function getJob(jobId: string): Promise<Job> {
  return readJson<Job>(
    await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`),
  )
}

export async function getJobLogs(jobId: string, tail = 200): Promise<JobLogs> {
  const safeTail = Math.max(1, Math.min(5000, Math.trunc(tail)))
  return readJson<JobLogs>(
    await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/logs?tail=${safeTail}`),
  )
}

export async function cancelJob(jobId: string): Promise<Job> {
  return readJson<Job>(
    await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    }),
  )
}

export async function createJob(
  datasetId: string,
  engine: ProcessingEngine,
  profile: ProcessingProfile,
  workflow: ProcessingWorkflow = 'mapping',
  options: Record<string, number> = {},
): Promise<Job> {
  const response = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dataset_id: datasetId,
      engine,
      profile,
      workflow,
      options,
    }),
  })
  return readJson<Job>(response)
}

export interface UploadCallbacks {
  onProgress: (progress: number) => void
  signal?: AbortSignal
}

export function uploadDatasetFile(
  datasetId: string,
  file: File,
  relativePath: string,
  callbacks: UploadCallbacks,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const form = new FormData()
    form.append('files', file, file.name)
    form.append('relative_paths', JSON.stringify([relativePath]))

    request.open('POST', `${API_BASE}/datasets/${encodeURIComponent(datasetId)}/files`)
    request.responseType = 'json'

    request.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return
      callbacks.onProgress(Math.round((event.loaded / event.total) * 100))
    })

    request.addEventListener('load', () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as UploadResponse)
        return
      }
      reject(new ApiError(`Upload fehlgeschlagen (Status ${request.status})`, request.status, request.response))
    })

    request.addEventListener('error', () => {
      reject(new ApiError('Upload fehlgeschlagen, weil die API nicht erreichbar ist.', 0))
    })

    request.addEventListener('abort', () => {
      reject(new DOMException('Upload abgebrochen', 'AbortError'))
    })

    const abort = () => request.abort()
    callbacks.signal?.addEventListener('abort', abort, { once: true })

    request.addEventListener('loadend', () => {
      callbacks.signal?.removeEventListener('abort', abort)
    })

    request.send(form)
  })
}


export async function listJobPointClouds(jobId: string): Promise<PointCloudListResponse> {
  return readJson<PointCloudListResponse>(
    await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/pointclouds`),
  )
}

export async function getPointCloudMetadata(
  jobId: string,
  artifactIndex: number,
): Promise<PointCloudMetadata> {
  return readJson<PointCloudMetadata>(
    await fetch(
      `${API_BASE}/jobs/${encodeURIComponent(jobId)}/pointclouds/${artifactIndex}`,
    ),
  )
}

export async function getPointCloudPreview(
  jobId: string,
  artifactIndex: number,
  maxPoints = 100_000,
): Promise<PointCloudPreview> {
  const response = await fetch(
    `${API_BASE}/jobs/${encodeURIComponent(jobId)}/pointclouds/${artifactIndex}/preview?max_points=${Math.max(1000, Math.min(500000, Math.trunc(maxPoints)))}`,
  )
  if (!response.ok) {
    let detail: unknown
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new ApiError(
      `Punktwolkenvorschau fehlgeschlagen (Status ${response.status})`,
      response.status,
      detail,
    )
  }

  const pointCount = Number(response.headers.get('X-Point-Count') ?? '0')
  const stride = Number(response.headers.get('X-Point-Stride') ?? '16')
  const origin = (response.headers.get('X-Point-Origin') ?? '0,0,0')
    .split(',')
    .map(Number) as [number, number, number]

  return {
    buffer: await response.arrayBuffer(),
    pointCount,
    stride,
    origin,
    hasRgb: response.headers.get('X-Point-Has-RGB') === '1',
  }
}
