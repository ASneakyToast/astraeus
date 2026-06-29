.PHONY: build-frontend build-frontend-dev test-js install-js

install-js:
	npm ci

build-frontend: install-js
	npm run build

build-frontend-dev: install-js
	npm run build:dev

test-js: install-js
	npm test
