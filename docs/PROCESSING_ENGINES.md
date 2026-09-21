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

Planned GPU worker. Input pipeline will normalize imagery and build a COLMAP sparse reconstruction before gsplat training.

## TeleSculptor

Experimental/manual comparison engine only. It is not part of the default automated worker queue.
