// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use crate::{webpage::schema_org, Result};
use lending_iter::LendingIterator;
use tantivy::tokenizer::PreTokenizedString;

use super::{find_recipe_first_ingredient_tag_id, Html};

macro_rules! cache {
    ($($fn:ident -> $res:ty),*$(,)?) => {
        /// Dynamically compute the different webpage functions
        /// and cache the results for subsequent calls.
        ///
        /// Used during indexing as some of the fields use
        /// the same data from the webpage and we don't want to
        /// recompute the same data multiple times.
        pub struct FnCache<'a> {
            html: &'a Html,
            first_ingredient_tag_id: Option<String>,
            schema_json: Option<String>,
            pretokenized_schema_json: Option<PreTokenizedString>,
            $($fn: Option<$res>,)*
        }

        impl<'a> FnCache<'a> {
            /// Create a new instance of the IndexingCacher
            pub fn new(html: &'a Html) -> Self {
                Self {
                    html,
                    first_ingredient_tag_id: None,
                    schema_json: None,
                    pretokenized_schema_json: None,
                    $($fn: None,)*
                }
            }

            $(
                /// Compute $fn from webpage and cache the result
                pub fn $fn(&mut self) -> &$res {
                    if self.$fn.is_none() {
                        self.$fn = Some(self.html.$fn());
                    }

                    self.$fn.as_ref().unwrap()
                }
            )*
        }
    };
}

cache! {
    pretokenize_title -> Result<PreTokenizedString>,
    pretokenize_all_text -> Result<PreTokenizedString>,
    pretokenize_clean_text -> PreTokenizedString,
    pretokenize_url -> PreTokenizedString,
    pretokenize_url_for_site_operator -> PreTokenizedString,
    pretokenize_domain -> PreTokenizedString,
    pretokenize_site -> PreTokenizedString,
    pretokenize_description -> PreTokenizedString,
    pretokenize_microformats -> PreTokenizedString,
    domain_name -> String,
    schema_org -> Vec<schema_org::Item>,
    site_hash -> [u64; 2],
    url_without_query_hash -> [u64; 2],
    url_hash -> [u64; 2],
    url_without_tld_hash -> [u64; 2],
    domain_hash -> [u64; 2],
    title_hash -> [u64; 2],
}

/// Some manual implementations so we can use previously cached data
/// to compute the next field.
impl<'a> FnCache<'a> {
    pub fn first_ingredient_tag_id(&mut self) -> Option<&String> {
        if self.first_ingredient_tag_id.is_none() {
            let root = self.html.root.clone(); // Node is just a NodeRef, so it's cheap to clone

            self.first_ingredient_tag_id =
                find_recipe_first_ingredient_tag_id(self.schema_org().as_slice(), &root);
        }

        self.first_ingredient_tag_id.as_ref()
    }

    pub fn schema_json(&mut self) -> &String {
        if self.schema_json.is_none() {
            self.schema_json = Some(serde_json::to_string(self.schema_org()).unwrap());
        }

        self.schema_json.as_ref().unwrap()
    }

    pub fn pretokenized_schema_json(&mut self) -> &PreTokenizedString {
        if self.pretokenized_schema_json.is_none() {
            self.pretokenized_schema_json =
                match schema_org::flattened_json(self.schema_org().clone()) {
                    Ok(mut f) => {
                        let mut tokens = Vec::new();

                        {
                            let mut stream = f.token_stream();
                            let mut it = tantivy::tokenizer::TokenStream::iter(&mut stream);

                            while let Some(token) = it.next() {
                                tokens.push(token.clone());
                            }
                        }

                        Some(PreTokenizedString {
                            text: f.text().to_string(),
                            tokens,
                        })
                    }
                    Err(_) => Some(PreTokenizedString {
                        text: String::new(),
                        tokens: Vec::new(),
                    }),
                };
        }

        self.pretokenized_schema_json.as_ref().unwrap()
    }
}
