// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use tantivy::tokenizer::BoxTokenStream;

use super::{default::DefaultTokenizer, ngram::NGramTokenStream};

#[derive(Clone)]
pub struct BigramTokenizer {
    inner_tokenizer: DefaultTokenizer,
}

impl Default for BigramTokenizer {
    fn default() -> Self {
        Self {
            inner_tokenizer: DefaultTokenizer::with_stopwords(vec![]),
        }
    }
}

impl BigramTokenizer {
    pub fn as_str() -> &'static str {
        "bigram_tokenizer"
    }
}
impl tantivy::tokenizer::Tokenizer for BigramTokenizer {
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&'a mut self, text: &'a str) -> Self::TokenStream<'a> {
        let inner_stream = self.inner_tokenizer.token_stream(text);
        let stream: NGramTokenStream<2> = NGramTokenStream::new(inner_stream);
        BoxTokenStream::new(stream)
    }
}

#[cfg(test)]
mod tests {
    use lending_iter::LendingIterator;
    use tantivy::tokenizer::Tokenizer;

    use super::*;
    fn tokenize_bigram(s: &str) -> Vec<String> {
        let mut res = Vec::new();
        let mut tokenizer = BigramTokenizer::default();
        let mut stream = tokenizer.token_stream(s);

        let mut it = tantivy::tokenizer::TokenStream::iter(&mut stream);
        while let Some(token) = it.next() {
            res.push(token.text.clone());
        }

        res
    }

    #[test]
    fn bigram_tokenizer() {
        assert!(tokenize_bigram("").is_empty());
        assert_eq!(tokenize_bigram("test"), vec!["test"]);

        assert_eq!(tokenize_bigram("this is"), vec!["thisis"]);
        assert_eq!(tokenize_bigram("this is a"), vec!["thisis", "isa",]);
        assert_eq!(
            tokenize_bigram("this is a test"),
            vec!["thisis", "isa", "atest",]
        );

        assert_eq!(tokenize_bigram("this.is"), vec!["this.", ".is"]);
    }
}
