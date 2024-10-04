// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use tantivy::tokenizer::{BoxTokenStream, TextAnalyzer};

use super::pred::PredTokenizer;

#[derive(Clone, Default)]
pub struct WordTokenizer {
    analyzer: Option<TextAnalyzer>,
}

impl WordTokenizer {
    pub fn as_str() -> &'static str {
        "word"
    }
}

impl tantivy::tokenizer::Tokenizer for WordTokenizer {
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&'a mut self, text: &'a str) -> Self::TokenStream<'a> {
        let builder = TextAnalyzer::builder(PredTokenizer(|c| c.is_whitespace()));

        self.analyzer = Some(builder.build());

        self.analyzer.as_mut().unwrap().token_stream(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lending_iter::LendingIterator;
    use tantivy::tokenizer::Tokenizer as _;

    fn tokenize(s: &str) -> Vec<String> {
        let mut res = Vec::new();
        let mut tokenizer = WordTokenizer::default();
        let mut stream = tokenizer.token_stream(s);
        let mut it = tantivy::tokenizer::TokenStream::iter(&mut stream);

        while let Some(token) = it.next() {
            res.push(token.text.clone());
        }

        res
    }

    #[test]
    fn test_words_tokenizer() {
        assert!(tokenize("").is_empty());
        assert_eq!(tokenize("a b"), vec!["a", "b"]);
        assert_eq!(tokenize("a b "), vec!["a", "b"]);
        assert_eq!(tokenize(" a b "), vec!["a", "b"]);
        assert_eq!(tokenize("a b c"), vec!["a", "b", "c"]);
    }
}
