.PHONY: up down logs test lint fmt shell

up:            ## Build and start the local stack on http://localhost:8080
	test -f .env || cp .env.example .env
	docker compose up -d --build --wait

down:          ## Stop the stack (keeps data)
	docker compose down

logs:          ## Follow logs from every service
	docker compose logs -f

test:          ## Run the test suite inside the image, against the running stack
	docker build -q --target test -t grs-app:test . >/dev/null
	docker run --rm --network grs-project_default \
		-e DATABASE_URL=postgres://grs:grs@postgres:5432/grs \
		-e REDIS_CACHE_URL=redis://redis-cache:6379/1 \
		-e REDIS_BROKER_URL=redis://redis-broker:6379/1 \
		grs-app:test pytest $(ARGS)

lint:          ## Lint and check formatting
	ruff check . && ruff format --check .

fmt:           ## Apply formatting
	ruff check --fix . && ruff format .

shell:         ## Django shell in the running API container
	docker compose exec api python manage.py shell
