// Stract is an open source web search engine.
// Copyright (C) 2023 Stract ApS
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as
// published by the Free Software Foundation, either version 3 of the
// License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

use std::{collections::HashMap, sync::Arc};

use axum::{extract, response::IntoResponse, Json};
use serde::Serialize;
use utoipa::{IntoParams, ToSchema};

use crate::highlighted::HighlightedFragment;

use super::State;

fn highlight(query: &str, suggestion: &str) -> Vec<HighlightedFragment> {
    let idx = suggestion
        .chars()
        .zip(query.chars())
        .position(|(suggestion_char, query_char)| suggestion_char != query_char)
        .unwrap_or(query.chars().count());

    let mut new_suggestion = vec![HighlightedFragment::new_unhighlighted(
        suggestion.chars().take(idx).collect(),
    )];

    new_suggestion.push(HighlightedFragment::new_highlighted(
        suggestion.chars().skip(idx).collect::<String>(),
    ));

    new_suggestion
}

#[derive(Serialize, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct Suggestion {
    highlighted: Vec<HighlightedFragment>,
    raw: String,
}

#[derive(
    Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, IntoParams,
)]
#[serde(rename_all = "camelCase")]
pub struct AutosuggestQuery {
    q: String,
}

#[utoipa::path(
    post,
    path = "/beta/api/autosuggest",
    params(AutosuggestQuery),
    responses(
        (status = 200, description = "Autosuggest", body = Vec<Suggestion>),
    )
)]

pub async fn route(
    extract::State(state): extract::State<Arc<State>>,
    extract::Query(params): extract::Query<HashMap<String, String>>,
) -> impl IntoResponse {
    if let Some(query) = params.get("q") {
        let mut suggestions = Vec::new();

        for suggestion in state.autosuggest.suggestions(query).unwrap() {
            let highlighted = highlight(query, &suggestion);
            suggestions.push(Suggestion {
                highlighted,
                raw: suggestion,
            });
        }

        Json(suggestions)
    } else {
        Json(Vec::new())
    }
}

pub async fn browser(
    extract::State(state): extract::State<Arc<State>>,
    extract::Query(params): extract::Query<HashMap<String, String>>,
) -> impl IntoResponse {
    if let Some(query) = params.get("q") {
        Json((query.clone(), state.autosuggest.suggestions(query).unwrap()))
    } else {
        Json((String::new(), Vec::new()))
    }
}

#[cfg(test)]
mod tests {
    use crate::highlighted::HighlightedKind;

    use super::*;

    const HIGHLIGHTED_PREFIX: &str = "<b>";
    const HIGHLIGHTED_POSTFIX: &str = "</b>";

    fn highlight_fragments(frags: &[HighlightedFragment]) -> String {
        frags
            .iter()
            .map(|frag| match frag.kind {
                HighlightedKind::Normal => frag.text.clone(),
                HighlightedKind::Highlighted => {
                    format!(
                        "{}{}{}",
                        HIGHLIGHTED_PREFIX,
                        frag.text(),
                        HIGHLIGHTED_POSTFIX
                    )
                }
            })
            .collect()
    }

    #[test]
    fn suffix_highlight() {
        assert_eq!(
            highlight_fragments(&highlight("", "test")),
            format!("{HIGHLIGHTED_PREFIX}test{HIGHLIGHTED_POSTFIX}")
        );
        assert_eq!(
            highlight_fragments(&highlight("t", "test")),
            format!("t{HIGHLIGHTED_PREFIX}est{HIGHLIGHTED_POSTFIX}")
        );
        assert_eq!(
            highlight_fragments(&highlight("te", "test")),
            format!("te{HIGHLIGHTED_PREFIX}st{HIGHLIGHTED_POSTFIX}")
        );
        assert_eq!(
            highlight_fragments(&highlight("tes", "test")),
            format!("tes{HIGHLIGHTED_PREFIX}t{HIGHLIGHTED_POSTFIX}")
        );
        assert_eq!(
            highlight_fragments(&highlight("test", "test")),
            format!("test{HIGHLIGHTED_PREFIX}{HIGHLIGHTED_POSTFIX}")
        );
    }
}
