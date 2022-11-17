from importlib import metadata

try:
    from ztf_viewer._version import github_sha
except ImportError:
    github_sha = None


try:
    metadata_version = metadata.version("ztf_viewer")
except metadata.PackageNotFoundError:
    metadata_version = None


version_string = metadata_version
if github_sha is not None:
    version_string = f"{metadata_version} ({github_sha[:7]})"


_base_url = "https://github.com/snad-space/ztf-viewer/tree/"
if github_sha is not None:
    version_url = f"{_base_url}{github_sha}"
elif metadata_version is not None:
    version_url = f"{_base_url}v{metadata_version}"
else:
    version_url = None
