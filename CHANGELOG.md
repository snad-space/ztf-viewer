# Changelog

All notable changes to [ZTF SNAD Viewer](http://ztf.snad.space) will be documented in this file.

Version schema is `year.month.num_release`

## [Unreleased]

### Added

- New catalog: Pan-STARRS DR2 stacked PSF mags
- Pan-STARRS DR2 PSF light curves for the graph

### Known issues

- Pan-STARRS MJD definition is different from ZTF's https://github.com/snad-space/ztf-viewer/issues/144

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
