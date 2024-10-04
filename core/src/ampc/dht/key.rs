// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use crate::distributed::member::ShardId;
use crate::webgraph::NodeID;

pub trait KeyTrait: TryFrom<Key> + Into<Key> {
    fn as_bytes(&self) -> Vec<u8>;
}

impl KeyTrait for String {
    fn as_bytes(&self) -> Vec<u8> {
        self.as_bytes().to_vec()
    }
}

impl KeyTrait for NodeID {
    fn as_bytes(&self) -> Vec<u8> {
        self.as_u64().to_le_bytes().to_vec()
    }
}

type Unit = ();
impl KeyTrait for Unit {
    fn as_bytes(&self) -> Vec<u8> {
        vec![]
    }
}

impl KeyTrait for ShardId {
    fn as_bytes(&self) -> Vec<u8> {
        self.as_u64().to_le_bytes().to_vec()
    }
}

type U64 = u64;
impl KeyTrait for U64 {
    fn as_bytes(&self) -> Vec<u8> {
        self.to_le_bytes().to_vec()
    }
}

#[derive(
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    Debug,
    Clone,
    PartialOrd,
    Ord,
    PartialEq,
    Eq,
)]
pub enum Key {
    String(String),
    NodeID(NodeID),
    Unit(Unit),
    ShardId(ShardId),
    U64(U64),
}

impl KeyTrait for Key {
    fn as_bytes(&self) -> Vec<u8> {
        match self {
            Key::String(key) => KeyTrait::as_bytes(key),
            Key::NodeID(key) => KeyTrait::as_bytes(key),
            Key::Unit(key) => KeyTrait::as_bytes(key),
            Key::ShardId(key) => KeyTrait::as_bytes(key),
            Key::U64(key) => KeyTrait::as_bytes(key),
        }
    }
}

macro_rules! impl_from_to_key {
    ($key:ty, $variant:ident) => {
        impl From<$key> for Key {
            fn from(key: $key) -> Self {
                Key::$variant(key)
            }
        }

        impl TryFrom<Key> for $key {
            type Error = anyhow::Error;

            fn try_from(key: Key) -> Result<Self, Self::Error> {
                match key {
                    Key::$variant(key) => Ok(key),
                    _ => anyhow::bail!("Key is not of type {}", stringify!($key)),
                }
            }
        }
    };
}

impl_from_to_key!(String, String);
impl_from_to_key!(NodeID, NodeID);
impl_from_to_key!(Unit, Unit);
impl_from_to_key!(ShardId, ShardId);
impl_from_to_key!(U64, U64);
