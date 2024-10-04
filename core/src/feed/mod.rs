// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use std::str::FromStr;

use url::Url;

mod parser;

pub use parser::parse;

use crate::dated_url::DatedUrl;

#[derive(
    Debug,
    Clone,
    Copy,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    PartialEq,
    Eq,
    Hash,
)]
pub enum FeedKind {
    Atom,
    Rss,
}

impl FromStr for FeedKind {
    type Err = anyhow::Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "application/atom" => Ok(Self::Atom),
            "application/atom+xml" => Ok(Self::Atom),
            "application/rss" => Ok(Self::Rss),
            "application/rss+xml" => Ok(Self::Rss),
            s => anyhow::bail!("Unknown feed kind: {s}"),
        }
    }
}

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
pub struct Feed {
    #[bincode(with_serde)]
    pub url: Url,
    pub kind: FeedKind,
}

pub struct ParsedFeed {
    pub links: Vec<DatedUrl>,
}
