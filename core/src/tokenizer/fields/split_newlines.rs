// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use tantivy::tokenizer::{BoxTokenStream, TextAnalyzer};

use super::pred::PredTokenizer;

#[derive(Clone, Default)]
pub struct NewlineTokenizer {
    analyzer: Option<TextAnalyzer>,
}

impl NewlineTokenizer {
    pub fn as_str() -> &'static str {
        "newline"
    }
}

impl tantivy::tokenizer::Tokenizer for NewlineTokenizer {
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&'a mut self, text: &'a str) -> Self::TokenStream<'a> {
        let builder = TextAnalyzer::builder(PredTokenizer(|c| c == '\n' || c == '\r'));

        self.analyzer = Some(builder.build());

        self.analyzer.as_mut().unwrap().token_stream(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lending_iter::LendingIterator;
    use tantivy::tokenizer::Tokenizer as _;

    fn tokenize_newline(s: &str) -> Vec<String> {
        let mut res = Vec::new();
        let mut tokenizer = NewlineTokenizer::default();
        let mut stream = tokenizer.token_stream(s);
        let mut it = tantivy::tokenizer::TokenStream::iter(&mut stream);

        while let Some(token) = it.next() {
            res.push(token.text.clone());
        }

        res
    }

    #[test]
    fn newline_tokenizer() {
        assert!(tokenize_newline("").is_empty());
        assert_eq!(tokenize_newline("a\nb"), vec!["a", "b"]);
        assert_eq!(tokenize_newline("a\nb\n"), vec!["a", "b"]);
        assert_eq!(tokenize_newline("\na\nb\n"), vec!["a", "b"]);
        assert_eq!(tokenize_newline("\na\nb\nc"), vec!["a", "b", "c"]);
    }

    #[test]
    fn newline_tokenizer_without_newlines() {
        assert!(tokenize_newline("").is_empty());
        assert_eq!(tokenize_newline("test"), vec!["test"]);

        assert_eq!(tokenize_newline("this is"), vec!["this is"]);
        assert_eq!(tokenize_newline("this is a"), vec!["this is a",]);
        assert_eq!(tokenize_newline("this is a test"), vec!["this is a test",]);

        assert_eq!(tokenize_newline("this.is"), vec!["this.is"]);
    }
}
