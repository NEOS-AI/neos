// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use async_stream::stream;
use bloom::fast_stable_hash_64;
use futures::Stream;
use rand::seq::SliceRandom;
use std::{
    collections::BTreeMap,
    net::SocketAddr,
    ops::{Bound, Range},
};

use crate::{distributed::member::ShardId, Result};

use super::{
    key::{Key, KeyTrait},
    network::api,
    store::Table,
    upsert::UpsertEnum,
    value::Value,
    UpsertAction,
};

#[derive(Debug)]
pub struct Node {
    api: api::RemoteClient,
}

impl bincode::Encode for Node {
    fn encode<E: bincode::enc::Encoder>(
        &self,
        encoder: &mut E,
    ) -> std::prelude::v1::Result<(), bincode::error::EncodeError> {
        let addr = self.api.addr();
        addr.encode(encoder)
    }
}

impl bincode::Decode for Node {
    fn decode<D: bincode::de::Decoder>(
        decoder: &mut D,
    ) -> std::prelude::v1::Result<Self, bincode::error::DecodeError> {
        let addr = SocketAddr::decode(decoder)?;
        Ok(Self::new(addr))
    }
}

impl<'de> bincode::BorrowDecode<'de> for Node {
    fn borrow_decode<D: bincode::de::BorrowDecoder<'de>>(
        decoder: &mut D,
    ) -> std::prelude::v1::Result<Self, bincode::error::DecodeError> {
        let addr = SocketAddr::borrow_decode(decoder)?;
        Ok(Self::new(addr))
    }
}

impl serde::Serialize for Node {
    fn serialize<S>(&self, serializer: S) -> std::prelude::v1::Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        let addr = self.api.addr();
        addr.serialize(serializer)
    }
}

impl<'de> serde::Deserialize<'de> for Node {
    fn deserialize<D>(deserializer: D) -> std::prelude::v1::Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let addr = SocketAddr::deserialize(deserializer)?;
        Ok(Self::new(addr))
    }
}

impl Clone for Node {
    fn clone(&self) -> Self {
        Self {
            api: api::RemoteClient::new(self.api.addr()),
        }
    }
}

impl Node {
    pub fn new(addr: SocketAddr) -> Self {
        let api = api::RemoteClient::new(addr);

        Self { api }
    }

    pub async fn num_keys(&self, table: Table) -> Result<u64> {
        self.api.num_keys(table).await
    }

    pub async fn get(&self, table: Table, key: Key) -> Result<Option<Value>> {
        self.api.get(table, key).await
    }

    pub async fn batch_get(&self, table: Table, keys: Vec<Key>) -> Result<Vec<(Key, Value)>> {
        self.api.batch_get(table, keys).await
    }

    pub async fn set(&self, table: Table, key: Key, value: Value) -> Result<()> {
        self.api.set(table, key, value).await
    }

    pub async fn batch_set(&self, table: Table, values: Vec<(Key, Value)>) -> Result<()> {
        self.api.batch_set(table, values).await
    }

    pub async fn upsert<F: Into<UpsertEnum>>(
        &self,
        table: Table,
        upsert: F,
        key: Key,
        value: Value,
    ) -> Result<UpsertAction> {
        self.api.upsert(table, upsert, key, value).await
    }

    pub async fn batch_upsert<F: Into<UpsertEnum>>(
        &self,
        table: Table,
        upsert: F,
        values: Vec<(Key, Value)>,
    ) -> Result<Vec<(Key, UpsertAction)>> {
        let res = self.api.batch_upsert(table, upsert, values.clone()).await?;

        debug_assert_eq!(res.len(), values.len());
        debug_assert!(res
            .iter()
            .all(|(k, _)| values.iter().any(|(key, _)| key == k)));

        Ok(res)
    }

    pub async fn range_get(
        &self,
        table: Table,
        range: Range<Bound<Key>>,
        limit: Option<usize>,
    ) -> Result<Vec<(Key, Value)>> {
        self.api.range_get(table, range, limit).await
    }

    pub fn stream(&self, table: Table) -> impl Stream<Item = Result<(Key, Value)>> + '_ {
        const STREAM_BATCH_SIZE: usize = 1024;
        stream! {
            let mut prev_key = None;

            loop {
                let batch = self.range_get(
                    table.clone(),
                    prev_key
                        .as_ref()
                        .cloned()
                        .map_or(Bound::Unbounded, Bound::Excluded)
                        ..Bound::Unbounded,
                    Some(STREAM_BATCH_SIZE),
                ).await?;

                if batch.is_empty() {
                    break;
                }

                for (key, value) in batch {
                    yield Ok((key.clone(), value));
                    prev_key = Some(key);
                }
            }
        }
    }
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode)]
pub struct Shard {
    nodes: Vec<Node>,
}

impl Default for Shard {
    fn default() -> Self {
        Self::new()
    }
}

impl Shard {
    pub fn new() -> Self {
        Self { nodes: Vec::new() }
    }

    pub fn add_node(&mut self, addr: SocketAddr) {
        self.nodes.push(Node::new(addr));
    }

    pub fn node(&self) -> &Node {
        self.nodes.choose(&mut rand::thread_rng()).unwrap()
    }

    pub async fn get(&self, table: Table, key: Key) -> Result<Option<Value>> {
        self.node().get(table, key).await
    }

    pub async fn batch_get(&self, table: Table, keys: Vec<Key>) -> Result<Vec<(Key, Value)>> {
        self.node().batch_get(table, keys).await
    }

    pub async fn num_keys(&self, table: Table) -> Result<u64> {
        self.node().num_keys(table).await
    }

    pub async fn set(&self, table: Table, key: Key, value: Value) -> Result<()> {
        self.node().set(table, key, value).await
    }

    pub async fn batch_set(&self, table: Table, values: Vec<(Key, Value)>) -> Result<()> {
        self.node().batch_set(table, values).await
    }

    pub async fn upsert<F: Into<UpsertEnum>>(
        &self,
        table: Table,
        upsert: F,
        key: Key,
        value: Value,
    ) -> Result<UpsertAction> {
        self.node().upsert(table, upsert, key, value).await
    }

    pub async fn batch_upsert<F: Into<UpsertEnum>>(
        &self,
        table: Table,
        upsert: F,
        values: Vec<(Key, Value)>,
    ) -> Result<Vec<(Key, UpsertAction)>> {
        self.node().batch_upsert(table, upsert, values).await
    }

    pub fn stream(&self, table: Table) -> impl Stream<Item = Result<(Key, Value)>> + '_ {
        self.node().stream(table)
    }
}

#[derive(Clone, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Debug)]
pub struct Client {
    ids: Vec<ShardId>,
    shards: BTreeMap<ShardId, Shard>,
}

impl Client {
    pub fn new(members: &[(ShardId, SocketAddr)]) -> Self {
        let mut shards = BTreeMap::new();

        for (shard, host) in members {
            shards
                .entry(*shard)
                .or_insert_with(Shard::new)
                .add_node(*host);
        }

        let ids = shards.keys().cloned().collect();

        Self { shards, ids }
    }

    pub fn shards(&self) -> &BTreeMap<ShardId, Shard> {
        &self.shards
    }

    pub fn add_node(&mut self, shard_id: ShardId, addr: SocketAddr) {
        self.shards.entry(shard_id).or_default().add_node(addr);

        self.ids = self.shards.keys().cloned().collect();
    }

    fn shard_id_for_key(&self, key: &[u8]) -> Result<&ShardId> {
        if self.ids.is_empty() {
            return Err(anyhow::anyhow!("No shards"));
        }

        let hash = fast_stable_hash_64(key);

        Ok(&self.ids[hash as usize % self.ids.len()])
    }

    fn shard_for_key(&self, key: &[u8]) -> Result<&Shard> {
        let shard_id = self.shard_id_for_key(key)?;
        Ok(self.shards.get(shard_id).unwrap())
    }

    pub async fn get(&self, table: Table, key: Key) -> Result<Option<Value>> {
        self.shard_for_key(&key.as_bytes())?.get(table, key).await
    }

    pub async fn batch_get(&self, table: Table, keys: Vec<Key>) -> Result<Vec<(Key, Value)>> {
        let mut shard_keys: BTreeMap<ShardId, Vec<Key>> = BTreeMap::new();

        for key in keys {
            let shard = self.shard_id_for_key(&key.as_bytes())?;
            shard_keys.entry(*shard).or_default().push(key);
        }

        let mut futures = Vec::with_capacity(shard_keys.len());

        for (shard_id, keys) in shard_keys {
            futures.push(self.shards[&shard_id].batch_get(table.clone(), keys));
        }

        Ok(futures::future::try_join_all(futures)
            .await?
            .into_iter()
            .flatten()
            .collect())
    }

    pub async fn set(&self, table: Table, key: Key, value: Value) -> Result<()> {
        self.shard_for_key(&key.as_bytes())?
            .set(table, key, value)
            .await
    }

    pub async fn batch_set(&self, table: Table, values: Vec<(Key, Value)>) -> Result<()> {
        let mut shard_values: BTreeMap<ShardId, Vec<(Key, Value)>> = BTreeMap::new();

        for (key, value) in values {
            let shard = self.shard_id_for_key(&key.as_bytes())?;
            shard_values.entry(*shard).or_default().push((key, value));
        }

        let mut futures = Vec::with_capacity(shard_values.len());

        for (shard_id, values) in shard_values {
            futures.push(self.shards[&shard_id].batch_set(table.clone(), values));
        }

        futures::future::try_join_all(futures).await?;

        Ok(())
    }

    pub async fn num_keys(&self, table: Table) -> Result<u64> {
        let mut total = 0;

        for shard in self.shards.values() {
            total += shard.num_keys(table.clone()).await?;
        }

        Ok(total)
    }

    pub async fn upsert<F: Into<UpsertEnum>>(
        &self,
        table: Table,
        upsert: F,
        key: Key,
        value: Value,
    ) -> Result<UpsertAction> {
        self.shard_for_key(&key.as_bytes())?
            .upsert(table, upsert, key, value)
            .await
    }

    pub async fn batch_upsert<F: Into<UpsertEnum> + Clone>(
        &self,
        table: Table,
        upsert: F,
        values: Vec<(Key, Value)>,
    ) -> Result<Vec<(Key, UpsertAction)>> {
        let mut shard_values: BTreeMap<ShardId, Vec<(Key, Value)>> = BTreeMap::new();

        for (key, value) in values {
            let shard = self.shard_id_for_key(&key.as_bytes())?;
            shard_values.entry(*shard).or_default().push((key, value));
        }

        let mut futures = Vec::with_capacity(shard_values.len());

        for (shard_id, values) in shard_values {
            futures.push(self.shards[&shard_id].batch_upsert(
                table.clone(),
                upsert.clone(),
                values,
            ));
        }

        Ok(futures::future::try_join_all(futures)
            .await?
            .into_iter()
            .flatten()
            .collect())
    }

    pub async fn drop_table(&self, table: Table) -> Result<()> {
        for shard in self.shards.values() {
            for node in &shard.nodes {
                node.api.drop_table(table.clone()).await?;
            }
        }

        Ok(())
    }

    pub async fn create_table(&self, table: Table) -> Result<()> {
        for shard in self.shards.values() {
            for node in &shard.nodes {
                node.api.create_table(table.clone()).await?;
            }
        }

        Ok(())
    }

    pub async fn all_tables(&self) -> Result<Vec<Table>> {
        let mut tables = Vec::new();

        for shard in self.shards.values() {
            for node in &shard.nodes {
                tables.extend(node.api.all_tables().await?);
            }
        }

        tables.sort();
        tables.dedup();

        Ok(tables)
    }

    pub async fn clone_table(&self, from: Table, to: Table) -> Result<()> {
        for shard in self.shards.values() {
            for node in &shard.nodes {
                node.api.clone_table(from.clone(), to.clone()).await?;
            }
        }

        Ok(())
    }

    pub fn stream(&self, table: Table) -> impl Stream<Item = Result<(Key, Value)>> + '_ {
        let mut streams = Vec::new();
        for shard in self.shards.values() {
            streams.push(Box::pin(shard.stream(table.clone())));
        }

        futures::stream::select_all(streams)
    }
}
