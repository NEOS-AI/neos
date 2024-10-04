// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use chrono::{DateTime, Utc};
use url::Url;

#[derive(
    Debug,
    Clone,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    PartialEq,
    Eq,
    Hash,
)]
pub struct DatedUrl {
    #[bincode(with_serde)]
    pub url: Url,
    #[bincode(with_serde)]
    pub last_modified: Option<DateTime<Utc>>,
}
