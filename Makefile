# Newsarr — development helpers
#
#   make setup     install backend + frontend dependencies
#   make backend   run the API on :7878 (with autoreload)
#   make frontend  run the Vite dev server on :5173
#   make build     build the frontend for production (served by the API)
#   make test      run the end-to-end smoke test
#   make docker-up       build and start the Docker container
#   make docker-build    build the Docker image
#   make docker-down     stop the Docker container

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: setup backend frontend build test docker-build docker-up docker-down

setup:
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

backend:
	cd backend && .venv/bin/python run.py

frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	cd backend && PYTHONPATH=. .venv/bin/python tests/e2e_smoke.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/qbit_error_paths.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/torrent_hash.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/background_loop.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/autosearch.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/import_dedupe.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/issues.py
	cd backend && PYTHONPATH=. .venv/bin/python tests/issue_auto_grab.py

docker-build:
	docker build -t newsarr:latest .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
