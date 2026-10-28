test:
	python -m unittest discover -v
check:
	python -m compileall -q netops tests
	python -m unittest discover -v
	python scripts/release_audit.py
