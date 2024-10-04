// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

mod inbound_similarity;

use super::{RankableWebpage, Top};
pub use inbound_similarity::InboundSimilarity;

pub trait FullModifier: Send + Sync {
    type Webpage: RankableWebpage;
    fn update_boosts(&self, webpages: &mut [Self::Webpage]);

    fn rank(&self, webpages: &mut [Self::Webpage]) {
        webpages.sort_by(|a, b| b.score().partial_cmp(&a.score()).unwrap());
    }

    fn top_n(&self) -> Top {
        Top::Unlimited
    }
}

pub trait Modifier: Send + Sync {
    type Webpage: RankableWebpage;
    fn boost(&self, webpage: &Self::Webpage) -> f64;

    fn top(&self) -> Top {
        Top::Unlimited
    }
}

impl<T> FullModifier for T
where
    T: Modifier,
{
    type Webpage = <T as Modifier>::Webpage;

    fn update_boosts(&self, webpages: &mut [Self::Webpage]) {
        for webpage in webpages {
            let cur_boost = webpage.boost();
            webpage.set_boost(cur_boost * self.boost(webpage));
        }
    }

    fn top_n(&self) -> Top {
        Modifier::top(self)
    }
}
