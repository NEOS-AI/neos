// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use utoipa::ToSchema;

#[derive(
    Debug,
    Clone,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    PartialEq,
    ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub enum HighlightedKind {
    Normal,
    Highlighted,
}

#[derive(
    Debug,
    Clone,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    PartialEq,
    ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub struct HighlightedFragment {
    pub kind: HighlightedKind,
    pub text: String,
}

impl HighlightedFragment {
    pub fn new_unhighlighted(text: String) -> Self {
        Self::new_normal(text)
    }

    pub fn new_normal(text: String) -> Self {
        Self {
            kind: HighlightedKind::Normal,
            text,
        }
    }

    pub fn new_highlighted(text: String) -> Self {
        Self {
            kind: HighlightedKind::Highlighted,
            text,
        }
    }

    pub fn text(&self) -> &str {
        &self.text
    }
}
