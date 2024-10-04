use tantivy::tokenizer::BoxTokenStream;

// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.
#[derive(Clone, Default, Debug)]
pub struct Identity {}

impl Identity {
    pub fn as_str() -> &'static str {
        "identity_tokenizer"
    }
}
impl tantivy::tokenizer::Tokenizer for Identity {
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&mut self, text: &'a str) -> Self::TokenStream<'a> {
        BoxTokenStream::new(IdentityTokenStream::from(text.to_string()))
    }
}
pub struct IdentityTokenStream {
    num_advances: usize,
    token: Option<tantivy::tokenizer::Token>,
}

impl From<String> for IdentityTokenStream {
    fn from(text: String) -> Self {
        Self {
            num_advances: 0,
            token: Some(tantivy::tokenizer::Token {
                offset_from: 0,
                offset_to: text.len(),
                position: 0,
                text,
                ..Default::default()
            }),
        }
    }
}
impl tantivy::tokenizer::TokenStream for IdentityTokenStream {
    fn advance(&mut self) -> bool {
        self.num_advances += 1;

        if self.num_advances == 1 {
            true
        } else {
            self.token = None;
            false
        }
    }

    fn token(&self) -> &tantivy::tokenizer::Token {
        self.token.as_ref().unwrap()
    }

    fn token_mut(&mut self) -> &mut tantivy::tokenizer::Token {
        self.token.as_mut().unwrap()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lending_iter::LendingIterator;
    use tantivy::tokenizer::Tokenizer as _;

    fn tokenize_identity(s: &str) -> Vec<String> {
        let mut res = Vec::new();
        let mut tokenizer = Identity {};
        let mut stream = tokenizer.token_stream(s);
        let mut it = tantivy::tokenizer::TokenStream::iter(&mut stream);

        while let Some(token) = it.next() {
            res.push(token.text.clone());
        }

        res
    }

    #[test]
    fn identity() {
        assert_eq!(tokenize_identity("this is a test"), vec!["this is a test"]);
        assert_eq!(tokenize_identity("a-b"), vec!["a-b"]);
    }
}
