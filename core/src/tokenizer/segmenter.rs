// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use super::{script::Script, Token};

/// A segment is a part of a text where the entire segment has the same script and langage.
#[derive(Clone)]
pub struct Segment<'a> {
    full_text: &'a str,
    span: std::ops::Range<usize>,
    script: Script,
}

impl<'a> Segment<'a> {
    pub fn text(&self) -> &'a str {
        &self.full_text[self.span.clone()]
    }

    pub fn tokenize(&self) -> impl Iterator<Item = Token<'a>> + 'a {
        let offset = self.span.start;
        let script = self.script;

        script
            .tokenizer()
            .tokenize(self.text())
            .map(move |mut token| {
                token.offset(offset);
                token
            })
    }
}

pub trait Segmenter {
    fn segments(&self) -> SegmentIterator;
}

impl Segmenter for str {
    fn segments(&self) -> SegmentIterator<'_> {
        SegmentIterator::new(self)
    }
}

impl Segmenter for String {
    fn segments(&self) -> SegmentIterator<'_> {
        SegmentIterator::new(self)
    }
}

pub struct SegmentIterator<'a> {
    prev_end: usize,
    input: &'a str,
}

impl<'a> SegmentIterator<'a> {
    pub fn new(input: &'a str) -> Self {
        Self { input, prev_end: 0 }
    }
}

impl<'a> Iterator for SegmentIterator<'a> {
    type Item = Segment<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.prev_end >= self.input.len() {
            return None;
        }

        let start = self.prev_end;
        let mut end = start;
        let mut script = None;

        while end < self.input.len() {
            let c = self.input[end..].chars().next().unwrap();
            let next_script = Script::from(c);

            if let Some(script) = &script {
                if &next_script != script && next_script != Script::Other {
                    break;
                }
            } else {
                script = Some(next_script);
            }

            end += c.len_utf8();
        }

        self.prev_end = end;

        Some(Segment {
            script: script.unwrap_or_default(),
            full_text: self.input,
            span: start..end,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    #[test]
    fn test_segments() {
        let txt = "Hello, world! This is a test.";
        let segments: Vec<_> = txt.segments().collect();
        assert_eq!(segments.len(), 1);
        assert_eq!(segments[0].text(), txt);
        assert_eq!(segments[0].script, Script::Latin);

        let txt = "こんにちは、世界！";
        let segments: Vec<_> = txt.segments().collect();

        assert_eq!(segments.len(), 1);
        assert_eq!(segments[0].text(), txt);
        assert_eq!(segments[0].script, Script::Other);

        let txt = "Hello, こんにちは、世界！";
        let segments: Vec<_> = txt.segments().collect();

        // TODO: this should be split into multiple segments
        // when we have more script tokenizers than just latin
        assert_eq!(segments.len(), 1);
        assert_eq!(segments[0].text(), "Hello, こんにちは、世界！");
        assert_eq!(segments[0].script, Script::Latin);
    }

    proptest! {
        #[test]
        fn proptest_byte_offsets(txt in ".*") {
            for segment in txt.segments() {
                assert!(!segment.text().is_empty());
            }
        }
    }
}
