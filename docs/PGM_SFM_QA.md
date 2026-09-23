# PGM-SFM-QA — Sparse-Reconstruction Qualitätsmetriken

Issue: #56

## Ziel

PGM-SFM-QA normalisiert Qualitätsmetriken einer COLMAP/pycolmap Sparse
Reconstruction, bevor Dense Reconstruction, gsplat oder weitere 3D-Schritte
darauf aufbauen.

Referenzvertrag: pycolmap/COLMAP **4.2.0**.

## Architektur

Der QA-Kern importiert pycolmap nicht selbst. Er akzeptiert ein
`pycolmap.Reconstruction`-kompatibles Objekt.

Vorteile:

- API-Container bleibt frei von zusätzlicher nativer COLMAP-Laufzeit
- Unit-Tests benötigen kein COLMAP
- späterer SFM-QA-Worker kann pycolmap 4.2.0 fest pinnen
- derselbe Normalisierungsvertrag bleibt engine-neutral nutzbar

## Metriken

### Registrierung

- erwartete Bilder
- registrierte Bilder
- Registrierungsquote

Wenn die Liste erwarteter Bildnamen bekannt ist, wird genau gegen diese
Eingabemenge bewertet.

### Sparse Points

- Anzahl 3D-Punkte
- Anzahl Beobachtungen
- mittlere Beobachtungen je registriertem Bild

### Reprojection Error

COLMAPs Point3D-`error` ist ein Pixel-Reprojection-Error.

Ausgegeben werden:

- Mittelwert
- Median
- p95
- Maximum
- Stichprobengröße

### Track Length

- Mittelwert
- Median
- p10
- Minimum
- Maximum

### Kamera-Netz

Aus den Point3D-Tracks wird ein Bild-Konnektivitätsgraph aufgebaut.

Ausgegeben werden:

- Anzahl zusammenhängender Komponenten
- Größe/Anteil der größten Komponente
- Komponenten
- schwach eingebundene Kamera-Kandidaten

Eine Kamera gilt in Phase 1 als schwach eingebunden, wenn sie höchstens einen
Nachbarn im Sparse-Track-Netz besitzt oder keine triangulierte Beobachtung hat.

Das ist **kein geometrischer Pose-Outlier-Beweis**. Ohne GCP, Referenztrajektorie
oder belastbare externe Pose-Referenz wird keine Scheingenauigkeit erzeugt.

## Standard-Warnschwellen

- Registrierungsquote < 90 %
- mittlerer Reprojection Error > 2 px
- p95 Reprojection Error > 4 px
- mittlere Track Length < 3
- Anteil größte Kamera-Komponente < 95 %

Die Schwellen sind explizit überschreibbar und führen in Phase 1 zu Warnings.

Blocked:

- keine registrierten Bilder
- keine Sparse Points

## Phase 2

- eigener CPU-SFM-QA-Worker mit `pycolmap==4.2.0`
- echtes COLMAP Sparse-Model als Job-Artefakt konsumieren
- QA-JSON als standardisiertes Job-Artefakt
- Frontend-Karten/Charts für Registration, Reprojection Error und Connectivity
- GCP-/Checkpoint-Referenz für echte Pose-/Georeferenzierungs-Ausreißer
- Integration vor gsplat/OpenMVS als Quality Gate
