import type {
  Dataset,
  DatasetDetail,
  DatasetScanResponse,
  MapCatalog,
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
    throw new ApiError(`Request failed with status ${response.status}`, response.status, detail)
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
      reject(new ApiError(`Upload failed with status ${request.status}`, request.status, request.response))
    })

    request.addEventListener('error', () => {
      reject(new ApiError('Upload failed because the API could not be reached.', 0))
    })

    request.addEventListener('abort', () => {
      reject(new DOMException('Upload cancelled', 'AbortError'))
    })

    const abort = () => request.abort()
    callbacks.signal?.addEventListener('abort', abort, { once: true })

    request.addEventListener('loadend', () => {
      callbacks.signal?.removeEventListener('abort', abort)
    })

    request.send(form)
  })
}
