gunicorn-k8s.charm: src/*.py requirements.txt metadata.yaml config.yaml test
	charmcraft build

blacken:
	@echo "Normalising python layout with black."
	@tox -e black

lint: blacken
	@echo "Running flake8"
	@tox -e lint

# We actually use the build directory created by charmcraft,
# but the .charm file makes a much more convenient sentinel.
unittest:
	@tox -e unit

test: lint unittest

clean:
	@echo "Cleaning files"
	@git clean -fXd


.PHONY: lint test unittest blacken clean
