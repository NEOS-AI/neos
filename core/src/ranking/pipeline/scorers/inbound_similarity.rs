// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use std::sync::Mutex;

use crate::{
    ranking::{self, inbound_similarity, pipeline::RankableWebpage},
    searcher::api::ScoredWebpagePointer,
};

use super::FullRankingStage;

pub struct InboundScorer {
    scorer: Mutex<inbound_similarity::Scorer>,
}

impl InboundScorer {
    pub fn new(scorer: inbound_similarity::Scorer) -> Self {
        Self {
            scorer: Mutex::new(scorer),
        }
    }
}

impl FullRankingStage for InboundScorer {
    type Webpage = ScoredWebpagePointer;

    fn compute(&self, webpages: &mut [Self::Webpage]) {
        let mut scorer = self.scorer.lock().unwrap();

        for webpage in webpages {
            let score = scorer.score(
                webpage.as_ranking().host_id(),
                webpage.as_ranking().inbound_edges(),
            );
            webpage.as_ranking_mut().signals_mut().insert(
                ranking::signals::InboundSimilarity.into(),
                ranking::signals::SignalCalculation::new_symmetrical(score),
            );
        }
    }
}
