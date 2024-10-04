// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use super::Html;

impl Html {
    pub fn h1(&self) -> impl Iterator<Item = String> {
        self.root
            .select("h1")
            .expect("css selector should be valid")
            .map(|node| node.as_node().text_contents().trim().to_string())
    }

    pub fn h2(&self) -> impl Iterator<Item = String> {
        self.root
            .select("h2")
            .expect("css selector should be valid")
            .map(|node| node.as_node().text_contents().trim().to_string())
    }

    pub fn h3(&self) -> impl Iterator<Item = String> {
        self.root
            .select("h3")
            .expect("css selector should be valid")
            .map(|node| node.as_node().text_contents().trim().to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use itertools::Itertools;

    #[test]
    fn test_h1() {
        let html = Html::parse("<h1>Hello</h1><h2>World</h2>", "https://example.com").unwrap();
        assert_eq!(html.h1().collect_vec(), ["Hello"]);
    }

    #[test]
    fn test_h2() {
        let html = Html::parse("<h1>Hello</h1><h2>World</h2>", "https://example.com").unwrap();
        assert_eq!(html.h2().collect_vec(), ["World"]);
    }

    #[test]
    fn test_h3() {
        let html = Html::parse(
            "<h1>Hello</h1><h2>World</h2><h3>!</h3>",
            "https://example.com",
        )
        .unwrap();
        assert_eq!(html.h3().collect_vec(), ["!"]);
    }
}
