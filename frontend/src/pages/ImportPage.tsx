import {
  AlertCircle,
  CheckCircle2,
  FileImage,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  UploadCloud,
  XCircle,
} from 'lucide-react'
import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from 'react'
import { createDataset, scanDataset, uploadDatasetFile } from '../api/client'

type QueueStatus = 'queued' | 'uploading' | 'uploaded' | 'error' | 'cancelled'

type FileWithPath = File

interface QueueItem {
  id: string
  file: FileWithPath
  relativePath: string
  status: QueueStatus
  progress: number
  error?: string
}

const SUPPORTED_EXTENSIONS = ['jpg', 'jpeg', 'tif', 'tiff', 'dng', 'rjpeg']
const ACCEPT = SUPPORTED_EXTENSIONS.map((extension) => `.${extension}`).join(',')

function fileExtension(file: File) {
  return file.name.split('.').pop()?.toLowerCase() ?? ''
}

function isSupported(file: File) {
  return SUPPORTED_EXTENSIONS.includes(fileExtension(file))
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[index]}`
}

function statusLabel(status: QueueStatus) {
  return {
    queued: 'Queued',
    uploading: 'Uploading',
    uploaded: 'Uploaded',
    error: 'Error',
    cancelled: 'Cancelled',
  }[status]
}

export function ImportPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const abortersRef = useRef(new Map<string, AbortController>())
  const [datasetName, setDatasetName] = useState('')
  const [description, setDescription] = useState('')
  const [items, setItems] = useState<QueueItem[]>([])
  const [datasetId, setDatasetId] = useState<string>()
  const [isDragging, setIsDragging] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [scanState, setScanState] = useState<'idle' | 'scanning' | 'done' | 'error'>('idle')
  const [globalError, setGlobalError] = useState<string>()

  const totalBytes = useMemo(() => items.reduce((sum, item) => sum + item.file.size, 0), [items])
  const weightedProgress = useMemo(() => {
    if (!totalBytes) return 0
    const uploaded = items.reduce((sum, item) => sum + item.file.size * (item.progress / 100), 0)
    return Math.round((uploaded / totalBytes) * 100)
  }, [items, totalBytes])

  const successful = items.filter((item) => item.status === 'uploaded').length
  const uploadInProgress = items.some((item) => item.status === 'uploading')
  const hasUploadCandidate = items.some(
    (item) => isSupported(item.file) && ['queued', 'error', 'cancelled'].includes(item.status),
  )
  const canUpload =
    datasetName.trim().length > 0 && hasUploadCandidate && !uploadInProgress && !isStarting

  function addFiles(files: FileList | File[]) {
    const incoming = Array.from(files) as FileWithPath[]
    setItems((current) => {
      const keys = new Set(current.map((item) => `${item.relativePath}:${item.file.size}:${item.file.lastModified}`))
      const next = [...current]
      for (const file of incoming) {
        const relativePath = file.webkitRelativePath || file.name
        const key = `${relativePath}:${file.size}:${file.lastModified}`
        if (keys.has(key)) continue
        keys.add(key)
        next.push({
          id: crypto.randomUUID(),
          file,
          relativePath,
          status: isSupported(file) ? 'queued' : 'error',
          progress: 0,
          error: isSupported(file) ? undefined : `Unsupported .${fileExtension(file) || 'unknown'} file`,
        })
      }
      return next
    })
  }

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) addFiles(event.target.files)
    event.target.value = ''
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setIsDragging(false)
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files)
  }

  function updateItem(id: string, patch: Partial<QueueItem>) {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)))
  }

  function removeItem(id: string) {
    abortersRef.current.get(id)?.abort()
    abortersRef.current.delete(id)
    setItems((current) => current.filter((item) => item.id !== id))
  }

  function cancelItem(id: string) {
    abortersRef.current.get(id)?.abort()
  }

  async function ensureDataset() {
    if (datasetId) return datasetId
    const dataset = await createDataset(datasetName.trim(), description)
    setDatasetId(dataset.id)
    return dataset.id
  }

  async function uploadOne(item: QueueItem, targetDatasetId: string) {
    const controller = new AbortController()
    abortersRef.current.set(item.id, controller)
    updateItem(item.id, { status: 'uploading', progress: 0, error: undefined })

    try {
      const response = await uploadDatasetFile(targetDatasetId, item.file, item.relativePath, {
        signal: controller.signal,
        onProgress: (progress) => updateItem(item.id, { progress }),
      })
      const rejected = response.rejected.find((entry) => entry.name === item.file.name)
      if (rejected) {
        updateItem(item.id, { status: 'error', progress: 0, error: rejected.reason })
      } else {
        updateItem(item.id, { status: 'uploaded', progress: 100 })
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        updateItem(item.id, { status: 'cancelled', progress: 0, error: undefined })
      } else {
        updateItem(item.id, {
          status: 'error',
          progress: 0,
          error: error instanceof Error ? error.message : 'Upload failed',
        })
      }
    } finally {
      abortersRef.current.delete(item.id)
    }
  }

  async function startUpload() {
    setGlobalError(undefined)
    setIsStarting(true)
    try {
      const targetDatasetId = await ensureDataset()
      const candidates = items.filter((item) => item.status === 'queued' || item.status === 'error' || item.status === 'cancelled')
      for (const item of candidates) {
        if (!isSupported(item.file)) continue
        await uploadOne(item, targetDatasetId)
      }
    } catch (error) {
      setGlobalError(error instanceof Error ? error.message : 'Dataset could not be created.')
    } finally {
      setIsStarting(false)
    }
  }

  async function retry(item: QueueItem) {
    setGlobalError(undefined)
    try {
      const targetDatasetId = await ensureDataset()
      await uploadOne(item, targetDatasetId)
    } catch (error) {
      setGlobalError(error instanceof Error ? error.message : 'Retry failed.')
    }
  }

  async function runScan() {
    if (!datasetId || successful === 0) return
    setScanState('scanning')
    setGlobalError(undefined)
    try {
      await scanDataset(datasetId)
      setScanState('done')
    } catch (error) {
      setScanState('error')
      setGlobalError(error instanceof Error ? error.message : 'Dataset scan failed.')
    }
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Dataset import</p>
            <h2>Local aerial imagery</h2>
            <p>Preserve folder-relative paths where supported, then upload directly to the GeoPhoto API.</p>
          </div>
          {datasetId && <span className="mono-badge">Dataset {datasetId.slice(0, 8)}</span>}
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Dataset name</span>
            <input
              value={datasetName}
              maxLength={160}
              onChange={(event) => setDatasetName(event.target.value)}
              placeholder="Survey 2026-09-21"
              disabled={Boolean(datasetId)}
            />
          </label>
          <label className="field field--wide">
            <span>Description <em>optional</em></span>
            <input
              value={description}
              maxLength={2000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Site, mission, operator notes…"
              disabled={Boolean(datasetId)}
            />
          </label>
        </div>

        <div
          className={`drop-zone ${isDragging ? 'drop-zone--active' : ''}`}
          onDragEnter={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (event.currentTarget === event.target) setIsDragging(false)
          }}
          onDrop={handleDrop}
        >
          <UploadCloud size={34} strokeWidth={1.5} aria-hidden="true" />
          <div>
            <strong>Drop image files here</strong>
            <p>JPG, JPEG, TIFF, TIF, DNG and R-JPEG. Folder structure is retained when the browser exposes relative paths.</p>
          </div>
          <div className="button-row">
            <button className="button" type="button" onClick={() => fileInputRef.current?.click()}>
              <FileImage size={17} />
              Select files
            </button>
            <button className="button" type="button" onClick={() => folderInputRef.current?.click()}>
              <FolderOpen size={17} />
              Select folder
            </button>
          </div>
          <input
            ref={fileInputRef}
            className="visually-hidden"
            type="file"
            accept={ACCEPT}
            multiple
            onChange={handleInput}
          />
          <input
            ref={(element) => {
              folderInputRef.current = element
              element?.setAttribute('webkitdirectory', '')
              element?.setAttribute('directory', '')
            }}
            className="visually-hidden"
            type="file"
            accept={ACCEPT}
            multiple
            onChange={handleInput}
          />
        </div>
      </section>

      {globalError && (
        <div className="inline-message inline-message--error" role="alert">
          <AlertCircle size={18} />
          <span>{globalError}</span>
        </div>
      )}

      <section className="panel queue-panel">
        <div className="section-heading section-heading--compact">
          <div>
            <p className="eyebrow">Upload queue</p>
            <h3>{items.length ? `${items.length} files · ${formatBytes(totalBytes)}` : 'No files selected'}</h3>
          </div>
          {items.length > 0 && (
            <div className="queue-summary" aria-label="Overall upload progress">
              <span>{weightedProgress}%</span>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${weightedProgress}%` }} />
              </div>
            </div>
          )}
        </div>

        {items.length === 0 ? (
          <div className="compact-empty">
            <FileImage size={24} />
            <span>Select files or a folder to prepare the dataset.</span>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Relative path</th>
                  <th>Size</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <div className="file-cell">
                        <FileImage size={16} />
                        <span>{item.file.name}</span>
                      </div>
                    </td>
                    <td className="path-cell" title={item.relativePath}>{item.relativePath}</td>
                    <td>{formatBytes(item.file.size)}</td>
                    <td>
                      <span className={`status-chip status-chip--${item.status}`}>
                        {item.status === 'uploading' && <LoaderCircle className="spin" size={13} />}
                        {item.status === 'uploaded' && <CheckCircle2 size={13} />}
                        {item.status === 'error' && <AlertCircle size={13} />}
                        {item.status === 'cancelled' && <XCircle size={13} />}
                        {statusLabel(item.status)}
                      </span>
                      {item.error && <span className="row-error">{item.error}</span>}
                    </td>
                    <td>
                      <div className="file-progress">
                        <div className="progress-track">
                          <div className="progress-fill" style={{ width: `${item.progress}%` }} />
                        </div>
                        <span>{item.progress}%</span>
                      </div>
                    </td>
                    <td>
                      <div className="row-actions">
                        {(item.status === 'error' || item.status === 'cancelled') && isSupported(item.file) && (
                          <button className="mini-button" type="button" onClick={() => void retry(item)} title="Retry upload">
                            <RefreshCw size={15} />
                            <span className="visually-hidden">Retry {item.file.name}</span>
                          </button>
                        )}
                        {item.status === 'uploading' ? (
                          <button className="mini-button" type="button" onClick={() => cancelItem(item.id)} title="Cancel upload">
                            <XCircle size={15} />
                            <span className="visually-hidden">Cancel {item.file.name}</span>
                          </button>
                        ) : item.status !== 'uploaded' ? (
                          <button className="mini-button" type="button" onClick={() => removeItem(item.id)} title="Remove file">
                            <XCircle size={15} />
                            <span className="visually-hidden">Remove {item.file.name}</span>
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="queue-footer">
          <span className="helper-text">{successful} uploaded · {items.length - successful} remaining</span>
          <div className="button-row">
            {datasetId && successful > 0 && (
              <button
                className="button"
                type="button"
                disabled={scanState === 'scanning'}
                onClick={() => void runScan()}
              >
                {scanState === 'scanning' ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}
                {scanState === 'done' ? 'Scan complete' : scanState === 'scanning' ? 'Scanning…' : 'Scan metadata'}
              </button>
            )}
            <button className="button button--primary" type="button" disabled={!canUpload} onClick={() => void startUpload()}>
              {isStarting ? <LoaderCircle className="spin" size={17} /> : <UploadCloud size={17} />}
              Upload queue
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
