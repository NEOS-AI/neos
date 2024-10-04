// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use crate::{prehashed::Prehashed, ranking::initial::InitialScoreTweaker, simhash};

pub mod approx_count;
mod top_docs;

pub use top_docs::{BucketCollector, TopDocs};
pub type MainCollector = top_docs::TweakedScoreTopCollector<InitialScoreTweaker>;

#[derive(Clone, Debug)]
pub struct MaxDocsConsidered {
    pub total_docs: usize,
    pub segments: usize,
}

#[derive(
    Clone,
    Copy,
    Debug,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    PartialEq,
)]
pub struct Hashes {
    pub site: Prehashed,
    pub title: Prehashed,
    pub url: Prehashed,
    pub url_without_tld: Prehashed,
    pub simhash: simhash::HashType,
}

pub trait Doc: Clone {
    fn score(&self) -> f64;
    fn hashes(&self) -> Hashes;
}
