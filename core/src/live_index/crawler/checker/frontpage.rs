// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use url::Url;

use crate::config::CheckIntervals;
use crate::webpage::Html;
use crate::Result;
use crate::{entrypoint::site_stats, webpage::url_ext::UrlExt};

use super::{Checker, CrawlableUrl};

pub struct Frontpage {
    url: Url,
    last_check: std::time::Instant,
    client: reqwest::Client,
}

impl Frontpage {
    pub fn new(site: &site_stats::Site, client: reqwest::Client) -> Result<Self> {
        let url = Url::robust_parse(&format!("https://{}/", site.as_str()))?;

        Ok(Self {
            url,
            last_check: std::time::Instant::now(),
            client,
        })
    }
}

impl Checker for Frontpage {
    async fn get_urls(&mut self) -> Result<Vec<CrawlableUrl>> {
        let res = self.client.get(self.url.clone()).send().await?;
        let body = res.text().await?;

        let page = Html::parse(&body, self.url.as_str())?;

        let urls = page
            .anchor_links()
            .into_iter()
            .map(|link| CrawlableUrl::from(link.destination))
            .collect::<Vec<_>>();

        self.last_check = std::time::Instant::now();

        Ok(urls)
    }

    fn should_check(&self, interval: &CheckIntervals) -> bool {
        self.last_check.elapsed() > interval.frontpage
    }
}
