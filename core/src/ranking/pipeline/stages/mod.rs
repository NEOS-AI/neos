// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

mod precision;
mod recall;

pub use precision::PrecisionRankingWebpage;
pub use recall::{LocalRecallRankingWebpage, RecallRankingWebpage, StoredEmbeddings};
