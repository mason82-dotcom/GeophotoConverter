# Processing engines

## OpenDroneMap / ODM

Container base: `opendronemap/odm:3.6.2`.

Profiles:
- `preview`: fast orthophoto, lowest point-cloud quality
- `standard`: DSM/DTM, medium point-cloud quality
- `high`: DSM/DTM, high point-cloud quality

## MicMac

Pinned upstream release: `micmacIGN/micmac v1.2.0`.

The Linux release archive is verified during image build with SHA-256:

`84c1b48dd4f7b4e099a40d034d08afbebd4837ea61526ecae370304e8d5153c5`

Profiles:
- `preview`: Tapioca + Tapas RadialBasic + AperiCloud
- `standard`: Tapioca + Tapas RadialStd + AperiCloud + C3DC QuickMac
- `high`: Tapioca + Tapas RadialStd + AperiCloud + C3DC BigMac

The first MicMac worker produces local-coordinate sparse/dense point clouds. GPS/RTK-based georeferencing and orthomosaic/DEM export are a separate integration phase so that orientation correctness can be validated independently.

## gsplat

GPU worker pinned to upstream commit:

`nerfstudio-project/gsplat@512d366b67073d77ca099ede742683c165dfc23b`

Runtime foundation:
- NVIDIA CUDA 12.8.1 + cuDNN development image
- PyTorch 2.9.1 / torchvision 0.24.1 with CUDA 12.8 wheels
- COLMAP CLI for camera pose / sparse reconstruction
- gsplat CUDA extension JIT-compiled on first GPU use and stored in a persistent Docker volume

Profiles:
- `preview`: COLMAP sequential matching, max image size 1600, gsplat factor 4, 3000 training steps
- `standard`: exhaustive matching, max image size 2400, gsplat factor 2, 7000 steps
- `high`: exhaustive matching, max image size 3200, gsplat factor 2, 15000 steps

All profiles use packed rasterization to reduce GPU memory pressure. The worker requires NVIDIA Container Toolkit and a CUDA-capable NVIDIA GPU.

## Shared image normalization

ODM, MicMac and gsplat consume the same prepared job-local image set.

Rules:
- RGB and WIDE imagery is eligible for standard mapping/reconstruction jobs.
- ZOOM imagery is excluded by default to avoid mixing focal lengths.
- Thermal/R-JPEG imagery remains in the dataset but is excluded from standard photogrammetry.
- M3M multispectral bands remain classified for a dedicated multispectral workflow and are not mixed into RGB jobs.
- JPEG/TIFF/PNG inputs are linked or copied without re-encoding.
- DNG inputs are rendered to 16-bit TIFF with LibRaw `dcraw_emu` using camera white balance and AHD demosaicing.
- ExifTool copies source EXIF/XMP metadata to DNG-derived TIFF files so downstream engines retain GPS/DJI metadata.
- Each prepared image directory contains `geophoto-input-manifest.json` recording included, normalized and skipped files.

## TeleSculptor

Experimental/manual comparison engine only. It is not part of the default automated worker queue.
