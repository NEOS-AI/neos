// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use tantivy::tokenizer::{BoxTokenStream, LowerCaser, TextAnalyzer};
use whatlang::Lang;

use crate::tokenizer::stemmer::Stemmer;

use super::default::Normal;

#[derive(Clone, Default)]
pub struct Stemmed {
    force_language: Option<Lang>,
    analyzer: Option<TextAnalyzer>,
}

impl Stemmed {
    pub fn as_str() -> &'static str {
        "stemmed_tokenizer"
    }
    pub fn with_forced_language(lang: Lang) -> Self {
        Self {
            force_language: Some(lang),
            analyzer: None,
        }
    }
}
impl tantivy::tokenizer::Tokenizer for Stemmed {
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&'a mut self, text: &'a str) -> Self::TokenStream<'a> {
        let builder = TextAnalyzer::builder(Normal).filter(LowerCaser);

        let lang = match self.force_language {
            Some(lang) => Some(lang),
            None => whatlang::detect_lang(text),
        };

        self.analyzer = match lang {
            Some(lang) => Some(builder.filter(Stemmer::from(lang).into_tantivy()).build()),
            None => Some(builder.build()),
        };

        self.analyzer.as_mut().unwrap().token_stream(text)
    }
}
