# Changelog

All notable changes to [ZTF SNAD Viewer](http://ztf.snad.space) will be documented in this file.

Version schema is `year.month.num_release`

## [Unreleased]

—

## [2022.11.0] 2022 November 2

### Added

- `stamp_classifier` for Alerce https://github.com/snad-space/ztf-viewer/pull/209
- https://github.com/snad-space/ztf-viewer/issues/210 "ML Classifications" section of the Summary with probability classifications from: Alerce (light-curve and stamp classifiers), Fink (binary KN, SN ang μLens classifiers), and Gaia DR3 (ternary galaxy — quasar — single star classifier). https://github.com/snad-space/ztf-viewer/issues/219

### Changed
- Search radius for broker links in the Summary section is now 3 arcsec https://github.com/snad-space/ztf-viewer/issues/217 https://github.com/snad-space/ztf-viewer/pull/218
- Set fixed time-outs for most catalog queries
- Implement 5-minute silence period for unavailable catalogs: if some catalog is found to not work properly, we are not calling it within 5 minutes

### Fixed

- https://github.com/snad-space/ztf-viewer/issues/208 Alerce table has shown no classifications. Fixed by https://github.com/snad-space/ztf-viewer/pull/209

## [2022.9.0] 2022 September 2

### Fixed

- 500 error when downloading some PDF figures with a large number of points

### Changed
- Aladin field of view is changed from 4.35' to 7.27' to make it close to ZTF FITS one https://github.com/snad-space/ztf-viewer/pull/199 

## [2022.7.3] 2022 July 25

### Fixed

- Better handling situations when cross-matched catalogs are not available
- Fix Pan-STARRS table to not load in some cases

## [2022.7.2] 2022 July 21

### Fixed

- Gaia light curve loading for some edge-cases
- Antares light curve loading

## [2022.7.1] 2022 July 17

### Fixed

- Pan-STARRS magnitude errors equation
- Description of Gaia light curves said that magnitudes are in Vega system, while we use AB.
- List new catalogs on the index page: SDSS DR16 QSO, PanSTARRS DR2, Gaia DR3. 

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
