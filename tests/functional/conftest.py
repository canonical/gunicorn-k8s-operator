import pytest


@pytest.fixture(scope="module")
def gunicorn_image(pytestconfig: pytest.Config):
    """Get the gunicorn image."""
    value: None | str = pytestconfig.getoption("--gunicorn-image")
    assert value is not None, "please specify the --gunicorn-image command line option"
    return value


@pytest.fixture(scope="module")
def statsd_exporter_image(pytestconfig: pytest.Config):
    """Get the statsd exporter image."""
    value: None | str = pytestconfig.getoption("--statsd-prometheus-exporter-image")
    assert (
        value is not None
    ), "please specify the --statsd-prometheus-exporter-image command line option"
    return value


@pytest.fixture(scope="module")
def influx_model_name(pytestconfig: pytest.Config):
    """Get influx's model name for testing."""
    value: None | str = pytestconfig.getoption("--influx-model-name")
    assert value is not None, "please specify the --influx-model-name command line option"
    return value
