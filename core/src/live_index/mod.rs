// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.
use std::time::Duration;

pub use self::index::LiveIndex;
pub use self::index_manager::IndexManager;

pub mod crawler;
pub mod index;
mod index_manager;

pub use self::crawler::Crawler;

const TTL: Duration = Duration::from_secs(60 * 60 * 24 * 60); // 60 days
const PRUNE_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60); // 6 hours
const COMPACT_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60); // 6 hours
const AUTO_COMMIT_INTERVAL: Duration = Duration::from_secs(10 * 60); // 10 minutes
const EVENT_LOOP_INTERVAL: Duration = Duration::from_secs(5);
const BATCH_SIZE: usize = 512;
