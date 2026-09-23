import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointCloudMetadata, PointCloudPreview } from '../api/types'

interface Props {
  metadata: PointCloudMetadata
  preview: PointCloudPreview
}

function perspective(fov: number, aspect: number, near: number, far: number) {
  const f = 1 / Math.tan(fov / 2)
  const out = new Float32Array(16)
  out[0] = f / aspect
  out[5] = f
  out[10] = (far + near) / (near - far)
  out[11] = -1
  out[14] = (2 * far * near) / (near - far)
  return out
}

function normalize(v: [number, number, number]): [number, number, number] {
  const length = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / length, v[1] / length, v[2] / length]
}

function cross(
  a: [number, number, number],
  b: [number, number, number],
): [number, number, number] {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ]
}

function dot(a: [number, number, number], b: [number, number, number]) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

function lookAt(eye: [number, number, number]) {
  const forward = normalize([-eye[0], -eye[1], -eye[2]])
  let right = normalize(cross(forward, [0, 0, 1]))
  if (Math.hypot(...right) < 0.001) right = [1, 0, 0]
  const up = cross(right, forward)
  const out = new Float32Array(16)
  out[0] = right[0]
  out[1] = up[0]
  out[2] = -forward[0]
  out[4] = right[1]
  out[5] = up[1]
  out[6] = -forward[1]
  out[8] = right[2]
  out[9] = up[2]
  out[10] = -forward[2]
  out[12] = -dot(right, eye)
  out[13] = -dot(up, eye)
  out[14] = dot(forward, eye)
  out[15] = 1
  return out
}

function multiply(a: Float32Array, b: Float32Array) {
  const out = new Float32Array(16)
  for (let column = 0; column < 4; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      let value = 0
      for (let index = 0; index < 4; index += 1) {
        value += a[index * 4 + row] * b[column * 4 + index]
      }
      out[column * 4 + row] = value
    }
  }
  return out
}

function shader(gl: WebGL2RenderingContext, type: number, source: string) {
  const value = gl.createShader(type)
  if (!value) throw new Error('WebGL-Shader konnte nicht erzeugt werden.')
  gl.shaderSource(value, source)
  gl.compileShader(value)
  if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(value) ?? 'Unbekannter Shader-Fehler'
    gl.deleteShader(value)
    throw new Error(message)
  }
  return value
}

export function PointCloudViewer({ metadata, preview }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dragRef = useRef<{ x: number; y: number } | null>(null)
  const extent = metadata.bounds.extent
  const radius = useMemo(
    () => Math.max(Math.hypot(extent[0], extent[1], extent[2]) / 2, 1),
    [extent],
  )
  const [yaw, setYaw] = useState(-0.75)
  const [pitch, setPitch] = useState(0.55)
  const [distance, setDistance] = useState(radius * 2.4)
  const [pointSize, setPointSize] = useState(2)
  const [colorMode, setColorMode] = useState<'rgb' | 'height'>(
    preview.hasRgb ? 'rgb' : 'height',
  )
  const [renderError, setRenderError] = useState<string>()

  useEffect(() => {
    setDistance(radius * 2.4)
    setYaw(-0.75)
    setPitch(0.55)
    setColorMode(preview.hasRgb ? 'rgb' : 'height')
  }, [metadata.name, preview.hasRgb, radius])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const gl = canvas.getContext('webgl2', { antialias: true })
    if (!gl) {
      setRenderError('WebGL2 ist in diesem Browser nicht verfügbar.')
      return
    }

    let program: WebGLProgram | null = null
    let buffer: WebGLBuffer | null = null
    let vao: WebGLVertexArrayObject | null = null
    let frame = 0
    let resizeObserver: ResizeObserver | undefined

    try {
      const vertex = shader(gl, gl.VERTEX_SHADER, `#version 300 es
        precision highp float;
        in vec3 a_position;
        in vec4 a_color;
        uniform mat4 u_mvp;
        uniform float u_point_size;
        uniform float u_min_z;
        uniform float u_max_z;
        uniform int u_color_mode;
        out vec4 v_color;

        vec3 heightColor(float t) {
          t = clamp(t, 0.0, 1.0);
          vec3 low = vec3(0.10, 0.45, 0.95);
          vec3 mid = vec3(0.20, 0.85, 0.58);
          vec3 high = vec3(1.00, 0.68, 0.20);
          return t < 0.5
            ? mix(low, mid, t * 2.0)
            : mix(mid, high, (t - 0.5) * 2.0);
        }

        void main() {
          gl_Position = u_mvp * vec4(a_position, 1.0);
          gl_PointSize = u_point_size;
          float range = max(0.0001, u_max_z - u_min_z);
          float height_t = (a_position.z - u_min_z) / range;
          v_color = u_color_mode == 0
            ? a_color
            : vec4(heightColor(height_t), 1.0);
        }
      `)
      const fragment = shader(gl, gl.FRAGMENT_SHADER, `#version 300 es
        precision highp float;
        in vec4 v_color;
        out vec4 out_color;
        void main() {
          vec2 p = gl_PointCoord - vec2(0.5);
          if (dot(p, p) > 0.25) discard;
          out_color = v_color;
        }
      `)
      program = gl.createProgram()
      if (!program) throw new Error('WebGL-Programm konnte nicht erzeugt werden.')
      gl.attachShader(program, vertex)
      gl.attachShader(program, fragment)
      gl.linkProgram(program)
      gl.deleteShader(vertex)
      gl.deleteShader(fragment)
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) ?? 'WebGL-Linkfehler')
      }

      vao = gl.createVertexArray()
      buffer = gl.createBuffer()
      gl.bindVertexArray(vao)
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
      gl.bufferData(gl.ARRAY_BUFFER, preview.buffer, gl.STATIC_DRAW)

      const position = gl.getAttribLocation(program, 'a_position')
      const color = gl.getAttribLocation(program, 'a_color')
      gl.enableVertexAttribArray(position)
      gl.vertexAttribPointer(position, 3, gl.FLOAT, false, preview.stride, 0)
      gl.enableVertexAttribArray(color)
      gl.vertexAttribPointer(color, 4, gl.UNSIGNED_BYTE, true, preview.stride, 12)
      gl.bindVertexArray(null)

      const mvpLocation = gl.getUniformLocation(program, 'u_mvp')
      const pointSizeLocation = gl.getUniformLocation(program, 'u_point_size')
      const minZLocation = gl.getUniformLocation(program, 'u_min_z')
      const maxZLocation = gl.getUniformLocation(program, 'u_max_z')
      const colorModeLocation = gl.getUniformLocation(program, 'u_color_mode')
      const relativeMinZ = metadata.bounds.min[2] - metadata.bounds.center[2]
      const relativeMaxZ = metadata.bounds.max[2] - metadata.bounds.center[2]

      const draw = () => {
        const ratio = window.devicePixelRatio || 1
        const width = Math.max(1, Math.round(canvas.clientWidth * ratio))
        const height = Math.max(1, Math.round(canvas.clientHeight * ratio))
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width
          canvas.height = height
        }

        gl.viewport(0, 0, width, height)
        gl.clearColor(0.025, 0.055, 0.095, 1)
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
        gl.enable(gl.DEPTH_TEST)
        gl.enable(gl.BLEND)
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

        const clampedPitch = Math.max(-1.45, Math.min(1.45, pitch))
        const eye: [number, number, number] = [
          distance * Math.cos(clampedPitch) * Math.cos(yaw),
          distance * Math.cos(clampedPitch) * Math.sin(yaw),
          distance * Math.sin(clampedPitch),
        ]
        const projection = perspective(
          Math.PI / 4,
          width / height,
          Math.max(radius * 0.001, 0.01),
          Math.max(radius * 50, distance * 4),
        )
        const mvp = multiply(projection, lookAt(eye))

        gl.useProgram(program)
        gl.bindVertexArray(vao)
        gl.uniformMatrix4fv(mvpLocation, false, mvp)
        gl.uniform1f(pointSizeLocation, pointSize * ratio)
        gl.uniform1f(minZLocation, relativeMinZ)
        gl.uniform1f(maxZLocation, relativeMaxZ)
        gl.uniform1i(colorModeLocation, colorMode === 'rgb' && preview.hasRgb ? 0 : 1)
        gl.drawArrays(gl.POINTS, 0, preview.pointCount)
        gl.bindVertexArray(null)
      }

      const schedule = () => {
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(draw)
      }
      resizeObserver = new ResizeObserver(schedule)
      resizeObserver.observe(canvas)
      schedule()
      setRenderError(undefined)

      return () => {
        resizeObserver?.disconnect()
        cancelAnimationFrame(frame)
        if (buffer) gl.deleteBuffer(buffer)
        if (vao) gl.deleteVertexArray(vao)
        if (program) gl.deleteProgram(program)
      }
    } catch (error) {
      setRenderError(error instanceof Error ? error.message : 'Punktwolke konnte nicht gerendert werden.')
      if (buffer) gl.deleteBuffer(buffer)
      if (vao) gl.deleteVertexArray(vao)
      if (program) gl.deleteProgram(program)
    }
  }, [colorMode, distance, metadata, pitch, pointSize, preview, radius, yaw])

  function resetView() {
    setYaw(-0.75)
    setPitch(0.55)
    setDistance(radius * 2.4)
  }

  return (
    <div className="pointcloud-viewer">
      <div className="pointcloud-toolbar">
        <label>
          Färbung
          <select
            value={colorMode}
            onChange={(event) => setColorMode(event.target.value as 'rgb' | 'height')}
          >
            <option value="height">Höhe</option>
            <option value="rgb" disabled={!preview.hasRgb}>RGB</option>
          </select>
        </label>
        <label>
          Punktgröße
          <input
            type="range"
            min="1"
            max="8"
            step="0.5"
            value={pointSize}
            onChange={(event) => setPointSize(Number(event.target.value))}
          />
        </label>
        <button className="button" type="button" onClick={resetView}>Ansicht zurücksetzen</button>
        <span className="pointcloud-hint">Ziehen: drehen · Mausrad: zoomen</span>
      </div>

      <div className="pointcloud-canvas-wrap">
        <canvas
          ref={canvasRef}
          className="pointcloud-canvas"
          aria-label={`3D-Punktwolke ${metadata.name}`}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId)
            dragRef.current = { x: event.clientX, y: event.clientY }
          }}
          onPointerMove={(event) => {
            const last = dragRef.current
            if (!last) return
            const dx = event.clientX - last.x
            const dy = event.clientY - last.y
            dragRef.current = { x: event.clientX, y: event.clientY }
            setYaw((value) => value - dx * 0.006)
            setPitch((value) => Math.max(-1.45, Math.min(1.45, value + dy * 0.006)))
          }}
          onPointerUp={() => { dragRef.current = null }}
          onPointerCancel={() => { dragRef.current = null }}
          onWheel={(event) => {
            event.preventDefault()
            const factor = Math.exp(event.deltaY * 0.001)
            setDistance((value) => Math.max(radius * 0.08, Math.min(radius * 30, value * factor)))
          }}
        />
        {renderError && <div className="pointcloud-render-error">{renderError}</div>}
      </div>
    </div>
  )
}
