.PHONY: up down logs test lint fmt shell messages seed

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
		-e DATABASE_URL=postgres://grs_owner:owner-local@postgres:5432/grs \
		-e REDIS_CACHE_URL=redis://redis-cache:6379/1 \
		-e REDIS_BROKER_URL=redis://redis-broker:6379/1 \
		grs-app:test pytest $(ARGS)

lint:          ## Lint and check formatting
	ruff check . && ruff format --check .

fmt:           ## Apply formatting
	ruff check --fix . && ruff format .

messages:      ## Compile translations (.po -> .mo) into the working tree
	docker build -q --target i18n -t grs-i18n . >/dev/null
	docker run --rm -v "$(CURDIR)/src/locale:/locale" grs-i18n \
		find /locale -name '*.po' -execdir msgfmt --check -o django.mo django.po ';'

seed:          ## Load synthetic demo data (needs DEMO_MODE=true)
	docker compose run --rm --no-deps api python manage.py seed_demo

shell:         ## Django shell in the running API container
	docker compose exec api python manage.py shell
