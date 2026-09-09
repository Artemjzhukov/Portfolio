import pytest

from english_tutor.db import connect


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "test.db"))
    yield c
    c.close()
