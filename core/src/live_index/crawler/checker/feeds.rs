// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use std::time::Duration;

use crate::feed::{parse, Feed};
use crate::Result;

use super::{CheckIntervals, Checker, CrawlableUrl};

const CRAWL_DELAY: Duration = Duration::from_secs(5);

pub struct Feeds {
    feeds: Vec<Feed>,
    last_check: std::time::Instant,
    client: reqwest::Client,
}

impl Feeds {
    pub fn new(feeds: Vec<Feed>, client: reqwest::Client) -> Self {
        Self {
            feeds,
            last_check: std::time::Instant::now(),
            client,
        }
    }
}

impl Checker for Feeds {
    async fn get_urls(&mut self) -> Result<Vec<CrawlableUrl>> {
        let mut urls = Vec::new();

        for feed in &self.feeds {
            let resp = self.client.get(feed.url.clone()).send().await?;
            let text = resp.text().await?;
            let parsed_feed = parse(&text, feed.kind)?;

            for link in parsed_feed.links {
                urls.push(CrawlableUrl::from(link));
            }

            tokio::time::sleep(CRAWL_DELAY).await;
        }

        self.last_check = std::time::Instant::now();

        Ok(urls)
    }

    fn should_check(&self, interval: &CheckIntervals) -> bool {
        self.last_check.elapsed() > interval.feeds
    }
}
