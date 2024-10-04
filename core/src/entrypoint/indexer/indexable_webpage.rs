// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use crate::crawler::CrawlDatum;
use crate::warc::WarcRecord;

#[derive(Debug, Clone, bincode::Encode, bincode::Decode)]
pub struct IndexableWebpage {
    pub url: String,
    pub body: String,
    pub fetch_time_ms: u64,
}

impl From<CrawlDatum> for IndexableWebpage {
    fn from(datum: CrawlDatum) -> Self {
        Self {
            url: datum.url.to_string(),
            body: datum.body,
            fetch_time_ms: datum.fetch_time_ms,
        }
    }
}

impl From<WarcRecord> for IndexableWebpage {
    fn from(record: WarcRecord) -> Self {
        Self {
            url: record.request.url,
            body: record.response.body,
            fetch_time_ms: record.metadata.fetch_time_ms,
        }
    }
}
