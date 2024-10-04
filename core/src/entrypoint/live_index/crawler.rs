// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use crate::config;
use crate::live_index;
use crate::Result;

pub async fn run(config: config::LiveCrawlerConfig) -> Result<()> {
    let crawler = live_index::Crawler::new(config).await?;

    crawler.run().await?;

    Ok(())
}
