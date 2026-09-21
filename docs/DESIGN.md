# GeoPhoto Converter Frontend Design System

## Purpose

GeoPhoto Converter is an operator workstation for geotagged aerial-imagery ingestion, QA, mapping, processing and result handling. The interface is intentionally designed as a technical geospatial application rather than a marketing website.

Primary workflow:

`Import → Metadata/GPS QA → Dataset review → Processing → Job monitoring → Results → Publish/export`

The visual language should make state, quality and processing readiness legible at a glance while keeping detailed metadata one interaction away.

## Design principles

1. **Operational clarity over decoration**  
   Every panel should answer a concrete operator question: what is selected, what state is it in, what is wrong, and what action is available.

2. **Maps and state are primary surfaces**  
   Dataset geometry, capture quality, progress, warnings and artifacts receive stronger hierarchy than explanatory copy.

3. **Compact desktop-first density**  
   The main target is a survey workstation or engineering desktop. Responsive layouts remain usable on tablets and narrow screens without turning the application into a mobile-first card feed.

4. **Backend truth, frontend presentation**  
   Readiness, service state, warnings, jobs and artifacts come from the API. The frontend must not invent successful backend state or duplicate processing logic.

5. **Progressive disclosure**  
   Summaries remain compact. Detailed logs, metadata, individual capture points and result artifacts are exposed in secondary panels or inspectors.

6. **Accessible by default**  
   Keyboard focus, semantic controls, status text, reduced-motion support and sufficient contrast are part of the base component behavior.

## Color tokens

Tokens are defined in `frontend/src/styles.css`.

| Token | Value | Usage |
| --- | --- | --- |
| `--bg` | `#08111f` | Application background |
| `--surface-0` | `#0b1626` | Lowest raised surface |
| `--surface-1` | `#101d2e` | Primary panels |
| `--surface-2` | `#142338` | Buttons / elevated controls |
| `--surface-3` | `#1a2b42` | Stronger raised states |
| `--border` | `#273b55` | Default panel/control border |
| `--border-strong` | `#35506e` | Interactive or emphasized border |
| `--text` | `#e7eef9` | Primary text |
| `--text-muted` | `#9cb0c7` | Secondary text |
| `--text-faint` | `#6f849b` | Metadata, hints, inactive labels |
| `--accent` | `#5cc8ff` | Primary interaction / map capture color |
| `--accent-strong` | `#7dd6ff` | Hover / emphasized accent |
| `--accent-soft` | `rgba(92, 200, 255, .12)` | Selected backgrounds |
| `--ok` | `#55d6a1` | Ready / completed / valid |
| `--warning` | `#f2bd5b` | Degraded / experimental / caution |
| `--danger` | `#ff737d` | Error / failed |

### Color rules

- Never rely on color alone for status. Pair status color with text, iconography, or both.
- Accent blue means selection, navigation, map geometry or a primary technical interaction.
- Green is reserved for valid/completed states.
- Amber is reserved for warnings, experimental capability, cancellation and incomplete readiness.
- Red is reserved for actual failures or rejected data.
- Basemap colors stay deliberately subdued so flight geometry and QA overlays remain dominant.

## Typography

The application uses the system UI stack:

`Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

Monospace values use:

`"SFMono-Regular", Consolas, "Liberation Mono", monospace`

Use monospace for:
- job IDs
- relative paths
- log output
- map/dataset technical identifiers
- checksums if surfaced later

### Hierarchy

- Page titles: restrained; typically about `1.08rem`
- Main content headings: `1.65–2.6rem` only for Overview/major workflow entry surfaces
- Panel headings: approximately `1rem`
- Body copy: compact, usually `.75–.86rem`
- Eyebrows: uppercase, letter-spaced, approximately `.68rem`
- Technical metadata: `.64–.72rem`

Large display typography should remain rare.

## Spacing and sizing

The UI uses a compact 4/8-derived spacing rhythm.

Common values:
- 4 px: very small inline separation
- 7–8 px: compact control/card spacing
- 9–12 px: internal row spacing
- 14–16 px: panel subsection spacing
- 18–20 px: normal panel padding / section gap
- 24–34 px: page-level spacing
- 40+ px: only major hero/workflow separation

### Radius

- Standard panel: 10 px
- Controls: 6–8 px
- Pills/status chips: fully rounded
- Map viewport remains visually rectangular and technical rather than highly rounded

### Minimum interactive targets

Desktop controls are compact but should normally remain at least 36–40 px tall. Critical actions use approximately 40 px.

## Application shell

The desktop shell uses:
- fixed-width left navigation
- sticky top bar
- central content workspace
- one active page at a time

Primary navigation order:

1. Overview
2. Import
3. Datasets
4. Map
5. Processing
6. Results
7. DroneDB
8. Assistant
9. Settings

The order mirrors the workflow while keeping optional services near the end.

At narrow widths the sidebar becomes an off-canvas drawer with a scrim and explicit close control.

## Panels

Panels are the primary layout primitive.

Rules:
- One conceptual task per panel.
- Panel headings use an eyebrow plus heading where useful.
- Avoid nested cards unless the nested element represents a real record, metric or operational sub-state.
- Do not add ornamental gradients or effects that reduce data density.
- Loading, empty and error states belong inside the same spatial region as the data they replace.

## Buttons

### Primary button

Use for the one dominant forward action in a panel:
- Upload queue
- Create processing job
- Future Publish to DroneDB

### Secondary button

Use for:
- refresh
- retry
- file/folder selection
- cancel
- metadata scan

### Icon button

Use only where the icon action is conventional and has an accessible label or visible tooltip/title:
- remove
- retry
- navigation close
- refresh compact list
- artifact download

Disabled buttons must communicate why through adjacent copy or a title where appropriate.

## Status chips

Status chips are compact categorical indicators.

Recommended mappings:
- queued / unknown → neutral
- uploading / running → accent
- uploaded / completed / installed → green
- cancelled / cancel requested / experimental → amber
- failed / invalid → red

Status chips always contain a textual label.

## Forms

- Labels remain visible; placeholders do not replace labels.
- Optional fields are explicitly marked.
- Inputs use the dark base surface with a visible border.
- Browser-native controls are preferred where they are sufficient.
- Validation and backend errors are shown close to the affected workflow.
- Never clear a user's queued import solely because a network request failed.

## Import workflow

The drop zone provides:
- drag/drop
- file selection
- folder selection
- supported-format description

The upload queue is tabular because file name, relative path, size, status and progress are comparison-oriented data.

Per-file state:
- queued
- uploading
- uploaded
- error
- cancelled

Progress is shown numerically and visually.

Relative paths are technical identifiers and use monospace presentation where space permits.

## Dataset QA

Dataset detail is organized into:

1. dataset header
2. QA summary metrics
3. Flightline Quality Strip
4. capture map
5. image/metadata inspector

### Flightline Quality Strip

The strip is a horizontal sequence preserving image order.

Each segment indicates:
- sequence index
- GPS readiness
- warning/error state
- current selection

It must remain horizontally scrollable for large surveys rather than compressing segments until they become unreadable.

### QA metrics

Authoritative backend QA should be preferred over frontend inference.

Expected concepts:
- image count
- geotagged %
- platform
- media classification
- camera models
- altitude range
- warning count
- per-engine readiness

## MapLibre maps

MapLibre GL JS is the required renderer.

Default behavior:
- Prefer local TileJSON from `/api/v1/maps/{region}/tilejson.json`.
- Do not require an external basemap.
- Preserve OpenStreetMap attribution.
- Capture geometry must remain visible if no offline map pack is installed.
- Flightline geometry and capture points must visually dominate the basemap.

Selected capture points use amber while normal captures use accent blue.

The initial Shortbread styling is intentionally restrained. More detailed cartography can be added later without changing map/data component contracts.

## Processing engine cards

Engine cards must clearly distinguish capability and maturity.

### ODM
Primary photogrammetry pipeline.

### MicMac
Alternative SfM/photogrammetry pipeline.

### gsplat
Gaussian Splatting / 3DGS. GPU-oriented designation must remain visible.

### TeleSculptor
Experimental / legacy comparison. Do not present it as equivalent production automation while the backend rejects automated jobs.

Profiles:
- Preview
- Standard
- High

The frontend submits backend jobs only.

## Job monitoring

The job detail surface includes:
- status
- percent progress
- phase
- engine
- profile
- runtime
- log tail
- cancellation
- failure details
- artifacts

Active jobs may poll the backend. Terminal jobs should stop automatic polling.

Logs use a monospace scroll region and should not dominate the page until intentionally inspected.

## Results

Artifacts are grouped by completed job.

Recognized presentation categories include:
- Orthophoto
- DSM
- DTM
- point cloud
- LAS/LAZ
- PLY
- mesh / OBJ
- GeoTIFF
- gsplat PLY
- gsplat checkpoints
- logs

Download actions use backend-supplied `download_url` only.

## DroneDB

DroneDB is an optional publication target, not the main data browser.

Until the backend exposes a publication endpoint:
- display service status
- allow completed result selection
- keep Publish disabled
- do not call DroneDB directly from the browser
- do not hardcode its host or port

## Assistant

Open WebUI is an optional assistant surface.

Rules:
- never replace the GeoPhoto application shell with Open WebUI
- report backend service status
- do not hardcode launch URLs
- only enable a launch action once the API exposes a safe relative target or equivalent configuration

## Settings

Settings has two classes of state:

### Backend state
Read-only:
- API health
- Redis state
- services
- offline map installation state

### Frontend-local preference
May be stored in browser localStorage:
- UI density
- polling preference
- future display preferences that do not affect processing truth

Do not silently treat browser preferences as backend configuration.

## Responsive behavior

### > 1180 px
Full workstation layout, multi-column engine/results/detail views.

### 821–1180 px
Reduced columns, map/inspector may stack, dataset browser may move above detail.

### 561–820 px
Off-canvas navigation, one-column detail surfaces where necessary.

### <= 560 px
Single-column cards/tables with horizontal overflow where preserving data relationships is more important than reflow.

Tables should scroll horizontally rather than dropping critical columns.

## Accessibility / WCAG 2.2 AA

Required behaviors:
- visible `:focus-visible` treatment
- skip link to main content
- semantic buttons for actions
- no clickable `div` elements
- status conveyed with text, not color alone
- form labels remain associated and visible
- meaningful icon-only controls include accessible names
- progress bars expose ARIA progress values
- reduced-motion media query disables nonessential motion
- disabled actions explain missing backend capability nearby
- contrast should be checked whenever token values change

## Loading, empty and error states

Every API-backed module must support:
- loading
- empty
- error
- retry where useful

Workflow-specific states additionally include:
- uploading
- processing
- completed
- cancelled

Never replace an error with fabricated sample data in production UI.

## Mock adapters

If a future backend capability is unavailable:
- define TypeScript types separately
- isolate any development mock behind an adapter
- never mix mock literals into UI components
- never silently invent an endpoint

The current frontend prefers explicit disabled states over mocks for capability gaps such as DroneDB publishing and Assistant launch URLs.

## API boundary

All application API calls use relative paths below:

`/api/v1`

No backend hostname, LAN IP, Docker service hostname or fixed port belongs in frontend source.

## Future design extensions

Safe future extensions include:
- dedicated orthophoto raster preview
- point-cloud / PLY viewer
- image thumbnail API integration
- richer Shortbread map style
- backend-provided DroneDB publish feedback
- AI assistant launch URL returned by backend
- persisted user/workstation preferences if a backend settings contract is introduced

These should extend the existing workstation language rather than introduce a separate visual system.
