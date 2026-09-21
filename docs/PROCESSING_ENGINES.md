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

MicMac input in this worker currently accepts JPEG/JPEG/TIFF imagery. DNG/R-JPEG conversion will be handled by a normalization stage rather than hidden inside the reconstruction commands.

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

All profiles use packed rasterization to reduce GPU memory pressure. The worker requires NVIDIA Container Toolkit and a CUDA-capable NVIDIA GPU. Image normalization currently accepts JPEG/PNG/TIFF; DNG and R-JPEG conversion will be added as a dedicated preprocessing stage.

## TeleSculptor

Experimental/manual comparison engine only. It is not part of the default automated worker queue.
