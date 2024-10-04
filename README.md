# Neos

Highly efficient web search engine.

## Instructions

1. Set up the environment:
```bash
python3 -m venv .venv
source .venv/bin/activate

python3 scripts/setup.py
# to build ML mode:
python3 scripts/setup.py --ml
```

TODO: need to document the crawler setup

2. Run servers:
```bash
# API server
cargo run api configs/api.toml

# search server
cargo run search-server configs/search_server.toml

# entity server
cargo run entity-search-server configs/entity_search_server.toml

# webgraph
cargo run webgraph server configs/webgraph/host_server.toml" && cargo run webgraph server configs/webgraph/page_server.toml
```

## References

- [tantivy](https://crates.io/crates/tantivy)
