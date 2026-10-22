import pytest
from app.utils.connector_security import patched_connector


@pytest.mark.parametrize('version,patched', [
    ((3, 3, 18), False), ((3, 3, 19), True), ((3, 3, 20), True),
    ((3, 4, 8), False), ((3, 4, 9), True), ((3, 4, 10), True),
    ((3, 2, 99), False), ((3, 5, 0), True), ((4, 0, 0), True),
])
def test_native_connector_security_threshold(version, patched):
    assert patched_connector(version) is patched
