"""Verify the linked C library, which PyPI package versions cannot describe.

PYSEC-2026-217 maps the Connector/C advisory onto the Python package version.
Upstream fixes: https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm
"""


def patched_connector(version):
    version = tuple(version)
    return version >= (3, 4, 9) or (version[:2] == (3, 3) and version >= (3, 3, 19))


def verify_native_connector():
    import mariadb
    version = tuple(mariadb.client_version_info)
    if not patched_connector(version):
        raise RuntimeError('MariaDB Connector/C must be patched: 3.3.19+ or 3.4.9+; rebuild the image')
    return version
