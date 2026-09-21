# DroneDB publishing

GeoPhotoConverter publishes completed processing results to an optional local DroneDB Registry.

## Backend endpoint

`POST /api/v1/jobs/{job_id}/publish/dronedb`

Optional body:

```json
{"name":"Survey result"}
```

Only completed jobs with existing artifacts can be published.

The backend:
1. authenticates to the configured Registry;
2. ensures the configured organization exists;
3. creates a deterministic dataset for the job;
4. uploads `geophoto-job.json`;
5. uploads processing artifacts under `results/`;
6. requests a DroneDB build;
7. persists publication metadata on the GeoPhoto job.

Repeated publication of an already-published job is idempotent and returns the stored publication.

## Configuration

Defaults target the bundled optional Compose service:

- `DRONEDB_BASE_URL=http://dronedb:5000`
- `DRONEDB_USERNAME=admin`
- `DRONEDB_PASSWORD=password123`
- `DRONEDB_ORG=geophoto`

The password above is DroneDB Registry's upstream development default. Change it before exposing the Registry on a LAN.

GeoPhotoConverter never sends DroneDB credentials to the frontend.
