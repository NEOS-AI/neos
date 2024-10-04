// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

pub mod embedding;
pub mod inbound_similarity;
pub mod lambdamart;
pub mod reranker;
pub mod term_distance;

pub use reranker::ReRanker;

use crate::ranking::{SignalCalculation, SignalCoefficients, SignalEnum};

use super::{RankableWebpage, Top};

pub trait FullRankingStage: Send + Sync {
    type Webpage: RankableWebpage;

    fn compute(&self, webpages: &mut [Self::Webpage]);
    fn top_n(&self) -> Top {
        Top::Unlimited
    }

    fn update_scores(&self, webpages: &mut [Self::Webpage], coefficients: &SignalCoefficients) {
        for webpage in webpages.iter_mut() {
            webpage.set_raw_score(webpage.signals().iter().fold(0.0, |acc, (signal, calc)| {
                acc + calc.score * coefficients.get(&signal)
            }));
        }
    }

    fn rank(&self, webpages: &mut [Self::Webpage]) {
        webpages.sort_by(|a, b| b.score().partial_cmp(&a.score()).unwrap());
    }
}

pub trait RankingStage: Send + Sync {
    type Webpage: RankableWebpage;

    fn compute(&self, webpage: &Self::Webpage) -> (SignalEnum, SignalCalculation);
    fn top_n(&self) -> Top {
        Top::Unlimited
    }
}

impl<T> FullRankingStage for T
where
    T: RankingStage,
{
    type Webpage = <T as RankingStage>::Webpage;

    fn compute(&self, webpages: &mut [Self::Webpage]) {
        for webpage in webpages.iter_mut() {
            let (signal, signal_calculation) = self.compute(webpage);
            webpage.signals_mut().insert(signal, signal_calculation);
        }
    }

    fn top_n(&self) -> Top {
        self.top_n()
    }
}
