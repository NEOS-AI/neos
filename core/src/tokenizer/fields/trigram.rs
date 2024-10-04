use tantivy::tokenizer::BoxTokenStream;

use super::{default::DefaultTokenizer, ngram::NGramTokenStream};

// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.
#[derive(Clone)]
pub struct TrigramTokenizer {
    inner_tokenizer: DefaultTokenizer,
}

impl Default for TrigramTokenizer {
    fn default() -> Self {
        Self {
            inner_tokenizer: DefaultTokenizer::with_stopwords(vec![]),
        }
    }
}

impl TrigramTokenizer {
    pub fn as_str() -> &'static str {
        "trigram_tokenizer"
    }
}
impl tantivy::tokenizer::Tokenizer for TrigramTokenizer {
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&'a mut self, text: &'a str) -> Self::TokenStream<'a> {
        let inner = self.inner_tokenizer.token_stream(text);
        let stream: NGramTokenStream<3> = NGramTokenStream::new(inner);
        BoxTokenStream::new(stream)
    }
}

#[cfg(test)]
mod tests {
    use lending_iter::LendingIterator;
    use tantivy::tokenizer::Tokenizer;

    use super::*;

    fn tokenize_trigram(s: &str) -> Vec<String> {
        let mut res = Vec::new();

        let mut tokenizer = TrigramTokenizer::default();
        let mut stream = tokenizer.token_stream(s);
        let mut it = tantivy::tokenizer::TokenStream::iter(&mut stream);

        while let Some(token) = it.next() {
            res.push(token.text.clone());
        }

        res
    }

    #[test]
    fn trigram_tokenizer() {
        assert!(tokenize_trigram("").is_empty());
        assert_eq!(tokenize_trigram("test"), vec!["test"]);
        assert_eq!(tokenize_trigram("this is"), vec!["thisis"]);

        assert_eq!(tokenize_trigram("this is a"), vec!["thisisa",]);
        assert_eq!(
            tokenize_trigram("this is a test"),
            vec!["thisisa", "isatest"]
        );
    }
}
