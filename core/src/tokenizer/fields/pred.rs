// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use tantivy::tokenizer::BoxTokenStream;

use crate::tokenizer::{self, normalizer, split_with_range::SplitWithRange, Normalize};

#[derive(Clone)]
pub struct PredTokenizer<P>(pub P)
where
    P: Fn(char) -> bool + Send + Sync + Clone + 'static;

impl<P> tantivy::tokenizer::Tokenizer for PredTokenizer<P>
where
    P: Fn(char) -> bool + Send + Sync + Clone + 'static,
{
    type TokenStream<'a> = BoxTokenStream<'a>;

    fn token_stream<'a>(&'a mut self, text: &'a str) -> Self::TokenStream<'a> {
        let stream = Box::new(
            text.split_with_range(|c| self.0(c))
                .map(|(s, range)| tokenizer::Token::new(s, range))
                .normalize(&normalizer::Lowercase)
                .normalize(&normalizer::UnicodeNFKD)
                .normalize(&normalizer::UnicodeDiacritics),
        );

        BoxTokenStream::new(PredTokenStream::new_boxed(stream))
    }
}

pub struct PredTokenStream<'a> {
    stream: Box<dyn Iterator<Item = tokenizer::Token<'a>> + 'a>,
    token: Option<tantivy::tokenizer::Token>,
    next_position: usize,
}

impl<'a> tantivy::tokenizer::TokenStream for PredTokenStream<'a> {
    fn advance(&mut self) -> bool {
        self.token = self.stream.next().map(|token| {
            let span = token.span();
            let pos = self.next_position;
            self.next_position += 1;
            tantivy::tokenizer::Token {
                offset_from: span.start,
                offset_to: span.end,
                position: pos,
                text: token.text().to_string(),
                ..Default::default()
            }
        });

        self.token.is_some()
    }

    fn token(&self) -> &tantivy::tokenizer::Token {
        self.token.as_ref().unwrap()
    }

    fn token_mut(&mut self) -> &mut tantivy::tokenizer::Token {
        self.token.as_mut().unwrap()
    }
}

impl<'a> PredTokenStream<'a> {
    fn new_boxed(
        stream: Box<dyn Iterator<Item = tokenizer::Token<'a>> + 'a>,
    ) -> BoxTokenStream<'a> {
        BoxTokenStream::new(Self {
            stream,
            token: None,
            next_position: 0,
        })
    }
}
