// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use crate::{
    ranking::{self, pipeline::RankableWebpage},
    searcher::api,
};

use super::Modifier;

const INBOUND_SIMILARITY_SMOOTHING: f64 = 8.0;

pub struct InboundSimilarity;

impl Modifier for InboundSimilarity {
    type Webpage = api::ScoredWebpagePointer;

    fn boost(&self, webpage: &Self::Webpage) -> f64 {
        webpage
            .as_ranking()
            .signals()
            .get(ranking::signals::InboundSimilarity.into())
            .map(|calc| calc.value)
            .unwrap_or(0.0)
            + INBOUND_SIMILARITY_SMOOTHING
    }
}
