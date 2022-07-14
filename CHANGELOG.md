# Changelog

All notable changes to [ZTF SNAD Viewer](http://ztf.snad.space) will be documented in this file.

Version schema is `year.month.num_release`

## [Unreleased]

### Fixed

- Pan-STARRS magnitude errors equation
- Description of Gaia light curves said that magnitudes are in Vega system, while we use AB.

## [2022.7.0] 2022 July 10

### Added

- Gaia DR3 light curves
- Gaia DR3 table which includes astrometry and spectral derivatives

## [2022.5.2] 2022 May 20

### Added

- New catalog: Pan-STARRS DR2 stacked PSF mags
- Pan-STARRS DR2 PSF light curves for the graph
- "Open in JS9" link to a full-functional installation of the JS9 FITS viewer

### Known issues

- Pan-STARRS MJD is different from ZTF's one https://github.com/snad-space/ztf-viewer/issues/144
- "Open in JS9" link doesn't draw a point in the object location, it looks like it is not supported by JS9 query parameters interface

## [2022.5.1] 2022 May 12

### Changed

- Highlight that Antares is diff-photometry https://github.com/snad-space/ztf-viewer/pull/140

### Fixed

- Support the latest `light-curve-feature` API v2022.5.1

## [2022.5.0] 2022 May 5

### Added

- This `CHANGELOG.md` file
- Reference catalog magnitude, error and flags are added to the **Metadata**
- Magnitude / flux / differential magnitude / diff flux switching
- Show the closest Antares object
- Show the viewer version in the footer

### Fixed

- Fink link is not working https://github.com/snad-space/ztf-viewer/issues/129
- Sort vizier matches by separation https://github.com/snad-space/ztf-viewer/issues/92

### Changed

- All plot tools moved bellow the graph

### Known issues

- Downloadable plots don't support new flux / diff mag / diff flux variants yet https://github.com/snad-space/ztf-viewer/issues/121
- Downloadable plots don't include the closest Antares object https://github.com/snad-space/ztf-viewer/issues/137
- Closest Antares object can be missed due to a (reported) bug in Antares
