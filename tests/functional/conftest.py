import pytest
import yaml
from pathlib import Path


@pytest.fixture(scope="module")
def metadata():
    """Provides charm metadata."""
    yield yaml.safe_load(Path("./metadata.yaml").read_text())

@pytest.fixture(scope="module")
def gunicorn_image(pytestconfig: pytest.Config):
    """Get the gunicorn image."""
    value: None | str = pytestconfig.getoption("--gunicorn-image")
    assert value is not None, "please specify the --gunicorn-image command line option"
    return value


@pytest.fixture(scope="module")
def statsd_exporter_image(metadata):
    """Provides the nginx prometheus exporter image from the metadata."""
    yield metadata["resources"]["statsd-prometheus-exporter-image"]["upstream-source"]


@pytest.fixture(scope="module")
def influx_model_name():
    """Get influx's model name for testing."""
    return "influxdbmodel"
