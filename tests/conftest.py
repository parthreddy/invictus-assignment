import pytest

from app.core.catalog import load_catalog


@pytest.fixture
def catalog():
    return load_catalog()
