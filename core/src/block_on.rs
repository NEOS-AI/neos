// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

static TOKIO_RUNTIME: std::sync::LazyLock<tokio::runtime::Runtime> =
    std::sync::LazyLock::new(|| {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
    });

// Make the async runtime to be available in the sync context
// by blocking on the async runtime.
pub fn block_on<F>(f: F) -> F::Output
where
    F: std::future::Future,
{
    TOKIO_RUNTIME.block_on(f)
}
