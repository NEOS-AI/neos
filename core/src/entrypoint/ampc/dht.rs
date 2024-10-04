// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use std::{collections::BTreeMap, net::SocketAddr, sync::Arc};

use anyhow::bail;
use openraft::error::InitializeError;
use tracing::info;

use crate::{
    ampc::dht::{self, BasicNode, ShardId},
    config::{DhtConfig, GossipConfig},
    distributed::{
        cluster::Cluster,
        member::{Member, Service},
    },
    Result,
};

pub struct Config {
    pub node_id: dht::NodeId,
    pub host: SocketAddr,
    pub shard: ShardId,
    pub seed_node: Option<SocketAddr>,
    pub gossip: Option<GossipConfig>,
}

impl From<DhtConfig> for Config {
    fn from(config: DhtConfig) -> Self {
        Self {
            node_id: config.node_id,
            host: config.host,
            shard: config.shard,
            seed_node: config.seed_node,
            gossip: Some(config.gossip),
        }
    }
}

pub async fn run<C: Into<Config>>(config: C) -> Result<()> {
    let config: Config = config.into();

    let raft_config = openraft::Config::default();
    let raft_config = Arc::new(raft_config.validate()?);

    let log_store = dht::log_store::LogStore::<dht::TypeConfig>::default();
    let state_machine_store = Arc::new(dht::store::StateMachineStore::default());

    let network = dht::network::Network;

    let raft = openraft::Raft::new(
        config.node_id,
        raft_config,
        network,
        log_store,
        state_machine_store.clone(),
    )
    .await?;

    let server = dht::Server::new(raft.clone(), state_machine_store)
        .bind(config.host)
        .await?;

    match config.seed_node {
        Some(seed) => {
            let client = dht::RaftClient::new(seed).await?;
            let metrics = client.metrics().await?;

            if metrics
                .membership_config
                .nodes()
                .any(|(id, node)| *id == config.node_id || node.addr == config.host.to_string())
            {
                bail!("Already member of cluster. It is currently not safe for a node to rejoin a cluster it was previously a member of.");
            }

            client.join(config.node_id, config.host).await?;

            info!("Joined cluster with node_id: {}", config.node_id);
        }
        None => {
            let members: BTreeMap<u64, _> =
                BTreeMap::from([(config.node_id, BasicNode::new(config.host))]);

            if let Err(e) = raft.initialize(members.clone()).await {
                match e {
                    openraft::error::RaftError::APIError(e) => match e {
                        InitializeError::NotAllowed(_) => {}
                        InitializeError::NotInMembers(_) => bail!(e),
                    },
                    openraft::error::RaftError::Fatal(_) => bail!(e),
                }
            }

            info!("Initialized cluster with node_id: {}", config.node_id);
        }
    }

    // dropping the handle leaves the cluster
    let _cluster_handle = match config.gossip {
        Some(gossip) => Some(
            Cluster::join(
                Member::new(Service::Dht {
                    host: config.host,
                    shard: config.shard,
                }),
                gossip.addr,
                gossip.seed_nodes.unwrap_or_default(),
            )
            .await?,
        ),
        None => None,
    };

    loop {
        server.accept().await?;
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;
    use crate::free_socket_addr;

    pub fn setup() -> (ShardId, SocketAddr) {
        let (tx, rx) = crossbeam_channel::unbounded();
        std::thread::spawn(move || {
            let rt = tokio::runtime::Runtime::new().unwrap();
            let shard = ShardId::new(1);

            rt.block_on(async {
                let addr = free_socket_addr();
                tx.send((shard, addr)).unwrap();

                run(Config {
                    node_id: 1,
                    host: addr,
                    seed_node: None,
                    shard,
                    gossip: None,
                })
                .await
                .unwrap();
            })
        });

        rx.recv().unwrap()
    }
}
