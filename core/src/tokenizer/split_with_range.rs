// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

pub trait SplitWithRange {
    fn split_with_range<P>(&self, pred: P) -> impl Iterator<Item = (&str, std::ops::Range<usize>)>
    where
        P: Fn(char) -> bool;
}

pub trait SplitWhitespaceWithRange {
    fn split_whitespace_with_range(&self) -> impl Iterator<Item = (&str, std::ops::Range<usize>)>;
}

pub struct SplitWithRangeIter<'a, P> {
    s: &'a str,
    pred: P,
    start: usize,
}

impl<'a, P> SplitWithRangeIter<'a, P> {
    fn new(s: &'a str, pred: P) -> Self {
        Self { s, pred, start: 0 }
    }
}

impl<'a, P> Iterator for SplitWithRangeIter<'a, P>
where
    P: Fn(char) -> bool,
{
    type Item = (&'a str, std::ops::Range<usize>);

    fn next(&mut self) -> Option<Self::Item> {
        for c in self.s[self.start..].chars() {
            if !(self.pred)(c) {
                break;
            }
            self.start += c.len_utf8();
        }

        if self.start >= self.s.len() {
            return None;
        }

        let start = self.s[self.start..].find(|c: char| !(self.pred)(c))?;
        let start = self.start + start;
        let end = self.s[start..]
            .find(|c| (self.pred)(c))
            .map(|end| start + end)
            .unwrap_or(self.s.len());
        let range = start..end;
        self.start = end;
        Some((&self.s[range.clone()], range))
    }
}

impl SplitWhitespaceWithRange for str {
    fn split_whitespace_with_range(&self) -> impl Iterator<Item = (&str, std::ops::Range<usize>)> {
        self.split_with_range(char::is_whitespace)
    }
}

impl SplitWhitespaceWithRange for String {
    fn split_whitespace_with_range(&self) -> impl Iterator<Item = (&str, std::ops::Range<usize>)> {
        self.split_with_range(char::is_whitespace)
    }
}

impl SplitWithRange for str {
    fn split_with_range<P>(&self, pred: P) -> impl Iterator<Item = (&str, std::ops::Range<usize>)>
    where
        P: Fn(char) -> bool,
    {
        SplitWithRangeIter::new(self, pred)
    }
}

impl SplitWithRange for String {
    fn split_with_range<P>(&self, pred: P) -> impl Iterator<Item = (&str, std::ops::Range<usize>)>
    where
        P: Fn(char) -> bool,
    {
        SplitWithRangeIter::new(self, pred)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    #[test]
    fn test_split_whitespace_with_range() {
        let txt = "Hello, world! 123";
        let tokens: Vec<_> = txt.split_whitespace_with_range().collect();
        assert_eq!(tokens.len(), 3);
        assert_eq!(tokens[0], ("Hello,", 0..6));
        assert_eq!(tokens[1], ("world!", 7..13));
        assert_eq!(tokens[2], ("123", 14..17));
    }

    #[test]
    fn test_split_whitespace_with_range_empty() {
        let txt = "";
        let tokens: Vec<_> = txt.split_whitespace_with_range().collect();
        assert_eq!(tokens.len(), 0);
    }

    #[test]
    fn test_multi_whitespace() {
        let txt = "Hello,   world! 123";
        let tokens: Vec<_> = txt.split_whitespace_with_range().collect();
        assert_eq!(tokens.len(), 3);
        assert_eq!(tokens[0], ("Hello,", 0..6));
        assert_eq!(tokens[1], ("world!", 9..15));
        assert_eq!(tokens[2], ("123", 16..19));
    }

    #[test]
    fn unicode() {
        let txt = "best café";
        let tokens: Vec<_> = txt.split_whitespace_with_range().collect();
        assert_eq!(tokens.len(), 2);
        assert_eq!(tokens[0], ("best", 0..4));
        assert_eq!(tokens[1], ("café", 5..10));

        let txt = "Hello, 世界! 123";
        let tokens: Vec<_> = txt.split_whitespace_with_range().collect();
        assert_eq!(tokens.len(), 3);
        assert_eq!(tokens[0], ("Hello,", 0..6));
        assert_eq!(tokens[1], ("世界!", 7..14));
        assert_eq!(tokens[2], ("123", 15..18));
    }

    proptest! {
        #[test]
        fn prop_split_whitespace_with_range(s: String) {
            let tokens: Vec<_> = s.split_whitespace_with_range().collect();
            for (txt, range) in tokens {
                assert_eq!(&s[range.clone()], txt);
            }
        }

        #[test]
        fn consistent_with_std(s: String) {
            let tokens: Vec<_> = s.split_whitespace().collect();
            let tokens_with_range: Vec<_> = s.split_whitespace_with_range().collect();
            let tokens_with_range: Vec<_> = tokens_with_range.into_iter().map(|(txt, _)| txt).collect();
            assert_eq!(tokens, tokens_with_range);
        }
    }
}
