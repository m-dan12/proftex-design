# Общий Makefile. Владелец — T01; цель check дополнена в T15 (e2e и скрипты проверки).
PY ?= python3
BACKEND := backend

.PHONY: dev check check-backend check-frontend check-e2e check-scripts install build

install:
	cd $(BACKEND) && $(PY) -m pip install -e '.[dev]'

# Только один процесс: очередь и лимиты живут в памяти процесса.
dev:
	cd $(BACKEND) && $(PY) -m uvicorn app.main:app --reload --workers 1 --port 8000

check: check-backend check-frontend check-e2e check-scripts

check-backend:
	$(PY) -m openapi_spec_validator contracts/openapi.yaml
	cd $(BACKEND) && $(PY) -m ruff check . && $(PY) -m ruff format --check .
	cd $(BACKEND) && $(PY) -m pytest -q

# Фронтенд появляется в T03; до этого цель ничего не делает.
check-frontend:
	@if [ -f frontend/package.json ]; then \
		cd frontend && npx vue-tsc --noEmit && npm run --if-present lint && npx vitest run; \
	else echo "frontend/ ещё нет (T03), пропускаю"; fi

build:
	cd frontend && npm run build

# Playwright на заглушке: бэкенд отдаёт frontend/dist (S-03…S-08, S-10, S-11, S-15).
# Chromium: `cd e2e && npx playwright install chromium` или PW_CHROMIUM_PATH=/путь/к/chromium.
check-e2e: build
	cd e2e && npm install --no-audit --no-fund && npx playwright test

# S-07 (параллельность) и S-14 (безопасность): сами поднимают временный сервис.
check-scripts:
	$(PY) scripts/load_check.py
	PY=$(PY) scripts/security_check.sh
