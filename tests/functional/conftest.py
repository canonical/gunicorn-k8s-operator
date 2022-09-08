import pytest


@pytest.fixture(scope="module")
def gunicorn_image(pytestconfig: pytest.Config):
    """Get the gunicorn image."""
    value: None | str = pytestconfig.getoption("--gunicorn-image")
    assert value is not None, "please specify the --gunicorn-image command line option"
    return value
