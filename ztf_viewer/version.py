from importlib import metadata

try:
    metadata_version = metadata.version('ztf_viewer')
except metadata.PackageNotFoundError:
    metadata_version = None


version_string = metadata_version

_base_url = 'https://github.com/snad-space/ztf-viewer/tree/'
version_url = None if metadata_version is None else f'{_base_url}v{metadata_version}'
