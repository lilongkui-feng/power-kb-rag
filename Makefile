.PHONY: up up-milvus down logs seed test config
up:        ; sh deploy/up.sh
up-milvus: ; sh deploy/up.sh milvus
down:      ; sh deploy/up.sh down
logs:      ; docker compose logs -f api web
seed:      ; sh deploy/seed_data.sh
config:    ; docker compose config -q && docker compose --profile milvus config -q && echo compose OK
test:      ; .venv/bin/python -m pytest tests -q
