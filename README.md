# Neos

Highly efficient web search engine.

## Why new search engine?

Clearly, there are so many search engines available.
And they are doing a great job.
But, there are some issues with them.

Google is great, but it is not open source.
Also, some people are concerned about privacy, and some people are concerned about the monopoly of Google.
Furthermore, it is clear that many Search Engines gets profit from ads, which might affect the search results.

Metasearch engines like searxng are relying too much on other search engines.

RAG-based search engines could be a game-changer, but not all companies can afford to use the LLMs due to the high cost of GPUs.

This is why I am spending my time to build a new classic search engine.

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

## TODO

- [ ] Crawl the data from the web
    - [ ] run the crawler with the seed URLs
- [ ] Enhance the indexer for faster indexing
- [ ] Update the ranking algorithms, prove the efficiency
- [ ] Need web interface
    - [ ] Search page
    - [ ] Entity search page

## References

- [tantivy](https://crates.io/crates/tantivy)
- [stract](https://github.com/StractOrg/stract)
