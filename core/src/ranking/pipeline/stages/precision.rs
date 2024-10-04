// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use std::sync::Arc;

use crate::{
    collector,
    enum_map::EnumMap,
    inverted_index::RetrievedWebpage,
    ranking::{
        models::{self, cross_encoder::CrossEncoder},
        pipeline::{
            scorers::lambdamart::PrecisionLambda, RankableWebpage, RankingPipeline, ReRanker,
        },
        SignalCalculation, SignalEnum,
    },
    searcher::SearchQuery,
};

use super::RecallRankingWebpage;

#[derive(Clone, Debug, bincode::Encode, bincode::Decode)]
pub struct PrecisionRankingWebpage {
    retrieved_webpage: RetrievedWebpage,
    ranking: RecallRankingWebpage,
}

impl PrecisionRankingWebpage {
    pub fn retrieved_webpage(&self) -> &RetrievedWebpage {
        &self.retrieved_webpage
    }

    pub fn ranking(&self) -> &RecallRankingWebpage {
        &self.ranking
    }

    pub fn ranking_mut(&mut self) -> &mut RecallRankingWebpage {
        &mut self.ranking
    }
}

impl collector::Doc for PrecisionRankingWebpage {
    fn score(&self) -> f64 {
        RankableWebpage::score(self)
    }

    fn hashes(&self) -> collector::Hashes {
        self.ranking.pointer().hashes
    }
}

impl RankableWebpage for PrecisionRankingWebpage {
    fn set_raw_score(&mut self, score: f64) {
        self.ranking.set_raw_score(score);
    }

    fn unboosted_score(&self) -> f64 {
        self.ranking.unboosted_score()
    }

    fn boost(&self) -> f64 {
        self.ranking.boost()
    }

    fn set_boost(&mut self, boost: f64) {
        self.ranking.set_boost(boost)
    }

    fn signals(&self) -> &EnumMap<SignalEnum, SignalCalculation> {
        self.ranking.signals()
    }

    fn signals_mut(&mut self) -> &mut EnumMap<SignalEnum, SignalCalculation> {
        self.ranking.signals_mut()
    }

    fn as_local_recall(&self) -> &super::LocalRecallRankingWebpage {
        self.ranking.as_local_recall()
    }
}

impl PrecisionRankingWebpage {
    pub fn new(retrieved_webpage: RetrievedWebpage, ranking: RecallRankingWebpage) -> Self {
        Self {
            retrieved_webpage,
            ranking,
        }
    }

    pub fn into_retrieved_webpage(self) -> RetrievedWebpage {
        self.retrieved_webpage
    }
}

impl RankingPipeline<PrecisionRankingWebpage> {
    pub fn reranker<M: CrossEncoder + 'static>(
        query: &SearchQuery,
        crossencoder: Arc<M>,
        lambda: Option<Arc<models::LambdaMART>>,
    ) -> Self {
        let mut s = Self::new().add_stage(ReRanker::new(query.text().to_string(), crossencoder));

        if let Some(lambda) = lambda {
            let lambda = PrecisionLambda::from(lambda);
            s = s.add_stage(lambda);
        }

        s
    }
}
