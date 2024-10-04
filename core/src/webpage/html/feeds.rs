// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use std::str::FromStr;

use url::Url;

use crate::feed::{Feed, FeedKind};
use crate::Result;

use super::Html;

impl Html {
    pub fn feeds(&self) -> Result<impl Iterator<Item = Feed>> {
        Ok(self.root.select("link")?.filter_map(|node| {
            let attributes = node.attributes.borrow();
            if let (Some(feed_kind), Some(Ok(feed_url))) = (
                attributes.get("type"),
                attributes.get("href").map(Url::parse),
            ) {
                if let Ok(feed_kind) = FeedKind::from_str(feed_kind) {
                    return Some(Feed {
                        url: feed_url,
                        kind: feed_kind,
                    });
                }
            }

            None
        }))
    }
}
