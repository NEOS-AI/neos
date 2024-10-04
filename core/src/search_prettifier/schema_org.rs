// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

//! This module is a hacky workaround for the fact that the `openapi` does not
//! like generics very much.

use std::collections::HashMap;

use utoipa::ToSchema;

#[derive(
    Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(untagged, rename_all = "camelCase")]
pub enum OneOrManyString {
    One(String),
    Many(Vec<String>),
}

impl From<crate::OneOrMany<String>> for OneOrManyString {
    fn from(one_or_many: crate::OneOrMany<String>) -> Self {
        match one_or_many {
            crate::OneOrMany::One(one) => OneOrManyString::One(one),
            crate::OneOrMany::Many(many) => OneOrManyString::Many(many),
        }
    }
}

#[derive(
    Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(untagged, rename_all = "camelCase")]
pub enum Property {
    String(String),
    Data(StructuredData),
}

impl From<crate::webpage::schema_org::Property> for Property {
    fn from(property: crate::webpage::schema_org::Property) -> Self {
        match property {
            crate::webpage::schema_org::Property::String(string) => Property::String(string),
            crate::webpage::schema_org::Property::Item(data) => Property::Data(data.into()),
        }
    }
}

#[derive(
    Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(untagged, rename_all = "camelCase")]
pub enum OneOrManyProperty {
    One(Property),
    Many(Vec<Property>),
}

impl From<crate::OneOrMany<crate::webpage::schema_org::Property>> for OneOrManyProperty {
    fn from(one_or_many: crate::OneOrMany<crate::webpage::schema_org::Property>) -> Self {
        match one_or_many {
            crate::OneOrMany::One(one) => OneOrManyProperty::One(one.into()),
            crate::OneOrMany::Many(many) => {
                OneOrManyProperty::Many(many.into_iter().map(Into::into).collect())
            }
        }
    }
}

#[derive(
    Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub struct StructuredData {
    #[serde(rename = "_type")]
    pub item_type: Option<OneOrManyString>,
    #[serde(flatten)]
    pub properties: HashMap<String, OneOrManyProperty>,
}

impl From<crate::webpage::schema_org::Item> for StructuredData {
    fn from(item: crate::webpage::schema_org::Item) -> Self {
        Self {
            item_type: item.itemtype.map(OneOrManyString::from),
            properties: item
                .properties
                .into_iter()
                .map(|(k, v)| (k, v.into()))
                .collect(),
        }
    }
}
