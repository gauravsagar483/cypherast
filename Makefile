# cypherast — quick uv workflows
#
#   make help
#   make sync test
#   make optimize Q="MATCH (n:Person) RETURN n.name"
#   make validate Q="MATCH (n) RETURN n"
#   make translate Q="MATCH (n:Person) RETURN n" FROM=opencypher TO=puppygraph OPT=1

UV      ?= uv
PYTHON  ?= $(UV) run python
PKG     ?= cypherast
READ    ?= puppygraph
WRITE   ?= puppygraph
DIALECT ?= $(WRITE)
FROM    ?= puppygraph
TO      ?= puppygraph
ONLY    ?=
DISABLE ?=
CONSTRAINT_DISABLE ?=
CONSTRAINT_ONLY ?=

.PHONY: help sync install clean build dist \
	test test-cov test-tck test-puppy \
	lint fmt typecheck check \
	pre-commit-install pre-commit-run \
	parse optimize validate translate explain run \
	ci

help: ## Show targets
	@grep -E '^[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)?:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?##"}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Vars: Q READ WRITE DIALECT FROM TO ONLY DISABLE CONSTRAINT_ONLY CONSTRAINT_DISABLE"
	@echo "  Ex:   make optimize Q=\"MATCH (a:Person)-[:R]->(b:Person) RETURN a\""
	@echo "  Ex:   make optimize Q=\"...\" CONSTRAINT_DISABLE=ensure_row_limit"

# --- env / package -----------------------------------------------------------

install: ## Install project + dev deps (uv)
	$(UV) sync --group dev

sync: install ## Alias for install

clean: ## Remove caches, build artifacts, coverage
	rm -rf build dist *.egg-info .eggs
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml
	rm -rf **/__pycache__
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete

build: ## Build wheel + sdist
	$(UV) build

dist: clean build ## Clean then build

# --- quality -----------------------------------------------------------------

test: ## Run pytest
	$(UV) run pytest

test-cov: ## Pytest with coverage
	$(UV) run pytest --cov=$(PKG) --cov-report=term-missing --cov-report=xml

test-tck: ## TCK smoke (infrastructure only)
	$(UV) run pytest tests/tck/test_tck_smoke.py -q

test-tck-official: ## Official TCK from /tmp → tests/tck/results.md
	$(UV) run python -m tests.tck

test-tck-official-parse: ## Official TCK parse gate only
	$(UV) run python -m tests.tck --parse-only

test-tck-oc9: ## Official TCK with OC9 scenario filter
	CYPHERAST_TCK_OC9_FILTER=1 $(UV) run python -m tests.tck

test-tck-dialects: ## OC9-passing scenarios transposed to neo4j5/neo4j25/memgraph/puppygraph
	$(UV) run python -m tests.tck --dialect-matrix

grammar-smoke: ## Parse-smoke queries from tools/grammar_smoke_queries.txt
	$(PYTHON) tools/grammar_smoke.py

test-puppy: ## PuppyGraph dialect tests
	$(UV) run pytest tests/test_puppygraph_dialect.py -q

test-dialects: ## Multidialect + public API regression
	$(UV) run pytest tests/test_dialect_regression.py tests/test_parse.py tests/test_web_dialect_transpile.py -q

lint: ## Ruff check
	$(UV) run ruff check $(PKG) tests

fmt: ## Ruff format + fix
	$(UV) run ruff format $(PKG) tests
	$(UV) run ruff check $(PKG) tests --fix

typecheck: ## mypy strict
	$(UV) run mypy $(PKG)

check: lint typecheck test ## lint + mypy + test

pre-commit-install: ## Install git hooks (ruff + pytest on commit)
	$(UV) run pre-commit install

pre-commit-run: ## Run pre-commit hooks on all files
	$(UV) run pre-commit run --all-files

ci: sync check ## Full local CI: sync + check

# --- cypher tools (set Q=...) ------------------------------------------------

parse: ## Parse query → AST  (Q= READ=)
	@test -n "$(Q)" || (echo 'usage: make parse Q="MATCH (n:Person) RETURN n"'; exit 1)
	$(UV) run $(PKG) parse "$(Q)" -r $(READ)

optimize: ## Optimize for WRITE dialect  (Q= READ= WRITE= ONLY= DISABLE= CONSTRAINT_*)
	@test -n "$(Q)" || (echo 'usage: make optimize Q="..." WRITE=puppygraph'; exit 1)
	Q="$(Q)" READ="$(READ)" WRITE="$(WRITE)" ONLY="$(ONLY)" DISABLE="$(DISABLE)" \
	CONSTRAINT_ONLY="$(CONSTRAINT_ONLY)" CONSTRAINT_DISABLE="$(CONSTRAINT_DISABLE)" \
	$(PYTHON) -c "import cypherast,os; \
q=os.environ['Q']; r=os.environ['READ']; w=os.environ['WRITE']; \
def csv(k): v=os.environ.get(k,'').strip(); return [x.strip() for x in v.split(',') if x.strip()] or None; \
print(cypherast.optimize(q, read=r, write=w, only=csv('ONLY'), disable=csv('DISABLE'), constraint_only=csv('CONSTRAINT_ONLY'), constraint_disable=csv('CONSTRAINT_DISABLE')).cypher(pretty=True, dialect=w))"

validate: ## Validate against DIALECT caps  (Q= DIALECT=)
	@test -n "$(Q)" || (echo 'usage: make validate Q="..." DIALECT=puppygraph'; exit 1)
	Q="$(Q)" DIALECT="$(DIALECT)" READ="$(READ)" $(PYTHON) -c "import cypherast,os; q=os.environ['Q']; d=os.environ['DIALECT']; r=os.environ.get('READ') or None; issues=cypherast.validate(q, read=r, dialect=d); \
print('OK' if not issues else f'{len(issues)} issue(s)'); \
[print(f'  [{i.code}] {i.message}' + (f' — {i.hint}' if i.hint else '')) for i in issues]; \
raise SystemExit(1 if issues else 0)"

translate: ## Translate FROM → TO  (Q= FROM= TO=); add OPT=1 to optimize for TO
	@test -n "$(Q)" || (echo 'usage: make translate Q="..." FROM=opencypher TO=puppygraph'; exit 1)
	Q="$(Q)" FROM="$(FROM)" TO="$(TO)" OPT="$(OPT)" $(PYTHON) -c "import cypherast,os; q=os.environ['Q']; print(cypherast.translate(q, from_=os.environ['FROM'], to_=os.environ['TO'], pretty=True, optimize=os.environ.get('OPT')=='1'))"

explain: ## EXPLAIN plan  (Q=)
	@test -n "$(Q)" || (echo 'usage: make explain Q="..."'; exit 1)
	$(UV) run $(PKG) explain "$(Q)"

run: ## Execute on empty in-memory graph  (Q=)
	@test -n "$(Q)" || (echo 'usage: make run Q="CREATE (n:Person {name: '"'"'Ada'"'"'}) RETURN n"'; exit 1)
	$(UV) run $(PKG) run "$(Q)"
