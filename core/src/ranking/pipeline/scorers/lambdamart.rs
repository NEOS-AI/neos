// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use crate::{
    ranking::{
        self, models,
        pipeline::{PrecisionRankingWebpage, RankableWebpage, Top},
        SignalCalculation, SignalEnum,
    },
    searcher::api::ScoredWebpagePointer,
};
use std::sync::Arc;

use super::RankingStage;

impl RankingStage for Arc<models::LambdaMART> {
    type Webpage = ScoredWebpagePointer;

    fn compute(&self, webpage: &Self::Webpage) -> (SignalEnum, SignalCalculation) {
        (
            ranking::signals::LambdaMart.into(),
            SignalCalculation::new_symmetrical(self.predict(webpage.as_ranking().signals())),
        )
    }

    fn top_n(&self) -> Top {
        Top::Limit(20)
    }
}

pub struct PrecisionLambda(Arc<models::LambdaMART>);

impl From<Arc<models::LambdaMART>> for PrecisionLambda {
    fn from(model: Arc<models::LambdaMART>) -> Self {
        Self(model)
    }
}

impl RankingStage for PrecisionLambda {
    type Webpage = PrecisionRankingWebpage;

    fn compute(&self, webpage: &Self::Webpage) -> (SignalEnum, SignalCalculation) {
        (
            ranking::signals::LambdaMart.into(),
            SignalCalculation::new_symmetrical(self.0.predict(webpage.ranking().signals())),
        )
    }

    fn top_n(&self) -> Top {
        Top::Limit(20)
    }
}
