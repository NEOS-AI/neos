// Stract is an open source web search engine.
// Copyright (C) 2023 Stract ApS
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as
// published by the Free Software Foundation, either version 3 of the
// License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

use kuchiki::NodeRef;

use super::RawItem;

pub fn convert_all_to_strings(json: &str) -> Result<String, serde_json::Error> {
    use serde_json::Value;

    fn convert_recursively(json: &mut Value) {
        match json {
            Value::Number(n) if n.is_u64() || n.is_i64() => {
                *json = Value::String(n.to_string());
            }
            Value::Bool(b) => {
                *json = Value::String(b.to_string());
            }
            Value::Array(a) => a.iter_mut().for_each(convert_recursively),
            Value::Object(o) => o.values_mut().for_each(convert_recursively),
            _ => (),
        }
    }

    serde_json::from_str(json).map(|mut v: Value| {
        convert_recursively(&mut v);
        v.to_string()
    })
}

pub(crate) fn parse(root: NodeRef) -> Vec<RawItem> {
    let mut res = Vec::new();

    for node in root.select("script").unwrap().filter(|node| {
        matches!(
            node.attributes.borrow().get("type"),
            Some("application/ld+json")
        )
    }) {
        let text_contens = node.text_contents();
        let content = text_contens.trim();

        match convert_all_to_strings(content) {
            Ok(schema) => match serde_json::from_str(&schema) {
                Ok(schema) => {
                    res.push(schema);
                }
                Err(e) => {
                    tracing::debug!("Failed to parse schema.org JSON-LD: {}", e)
                }
            },
            Err(e) => {
                tracing::debug!("Failed to convert schema.org JSON-LD: {}", e)
            }
        }
    }

    res
}

#[cfg(test)]
mod tests {
    use kuchiki::traits::TendrilSink;
    use maplit::hashmap;

    use crate::webpage::schema_org::{RawOneOrMany, RawProperty};

    use super::*;

    #[test]
    fn schema_dot_org_json_ld() {
        let root = kuchiki::parse_html().one(
            r#"
    <html>
        <head>
            <script type="application/ld+json">
                {
                "@context": "https://schema.org",
                "@type": "ImageObject",
                "author": "Jane Doe",
                "contentLocation": "Puerto Vallarta, Mexico",
                "contentUrl": "mexico-beach.jpg",
                "datePublished": "2008-01-25",
                "description": "I took this picture while on vacation last year.",
                "name": "Beach in Mexico"
                }
            </script>
        </head>
        <body>
        </body>
    </html>
        "#,
        );

        let res = parse(root);

        assert_eq!(res.len(), 1);

        assert_eq!(
            res,
            vec![RawItem {
                itemtype: Some(RawOneOrMany::One("ImageObject".to_string())),
                properties: hashmap! {
                    "@context".to_string() => RawOneOrMany::One(RawProperty::String("https://schema.org".to_string())),
                    "author".to_string() => RawOneOrMany::One(RawProperty::String("Jane Doe".to_string())),
                    "contentLocation".to_string() => RawOneOrMany::One(RawProperty::String("Puerto Vallarta, Mexico".to_string())),
                    "contentUrl".to_string() => RawOneOrMany::One(RawProperty::String("mexico-beach.jpg".to_string())),
                    "datePublished".to_string() => RawOneOrMany::One(RawProperty::String("2008-01-25".to_string())),
                    "description".to_string() => RawOneOrMany::One(RawProperty::String("I took this picture while on vacation last year.".to_string())),
                    "name".to_string() => RawOneOrMany::One(RawProperty::String("Beach in Mexico".to_string())),
                }
            }]
        );
    }

    #[test]
    fn no_schema_dot_org_json_ld() {
        let html = r#"
    <html>
        <head>
            <script>
                {
                "invalid": "schema"
                }
            </script>
        </head>
        <body>
        </body>
    </html>
        "#;

        let root = kuchiki::parse_html().one(html);
        let res = parse(root);
        assert!(res.is_empty());
    }

    #[test]
    fn numbers_as_strings() {
        let root = kuchiki::parse_html().one(
            r#"
    <html>
        <head>
            <script type="application/ld+json">
                {
                "@context": "https://schema.org",
                "@type": "test",
                "cost": 123
                }
            </script>
        </head>
        <body>
        </body>
    </html>
        "#,
        );

        let res = parse(root);

        assert_eq!(res.len(), 1);

        assert_eq!(
            res,
            vec![RawItem {
                itemtype: Some(RawOneOrMany::One("test".to_string())),
                properties: hashmap! {
                    "@context".to_string() => RawOneOrMany::One(RawProperty::String("https://schema.org".to_string())),
                    "cost".to_string() => RawOneOrMany::One(RawProperty::String("123".to_string())),
                }
            }]
        );
    }

    #[test]
    fn booleans() {
        let root = kuchiki::parse_html().one(
            r#"
            <html>
                <head>
                    <script type="application/ld+json">
                        {
                            "someBoolean": false
                        }
                </script>
            </head>
            <body>
            </body>
        </html>
        "#,
        );

        let res = parse(root);

        assert_eq!(res.len(), 1);
    }
}
