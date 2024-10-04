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
use crate::{
    canon_index::CanonicalIndex,
    config::{self, WarcSource, WebgraphConstructConfig},
    entrypoint::download_all_warc_files,
    webgraph::{self, Node, NodeID, WebgraphWriter},
    webpage::{url_ext::UrlExt, Html},
    Result,
};
use anyhow::bail;
use itertools::Itertools;
use url::Url;

use std::{path::Path, sync::Arc};
use tokio::pin;
use tracing::{info, trace};

#[derive(Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Clone)]
pub enum JobConfig {
    Http(config::HttpConfig),
    Local(config::LocalConfig),
    S3(config::S3Config),
}

impl From<config::WarcSource> for JobConfig {
    fn from(value: config::WarcSource) -> Self {
        match value {
            config::WarcSource::HTTP(config) => JobConfig::Http(config),
            config::WarcSource::Local(config) => JobConfig::Local(config),
            config::WarcSource::S3(config) => JobConfig::S3(config),
        }
    }
}

impl From<JobConfig> for config::WarcSource {
    fn from(value: JobConfig) -> Self {
        match value {
            JobConfig::Http(config) => config::WarcSource::HTTP(config),
            JobConfig::Local(config) => config::WarcSource::Local(config),
            JobConfig::S3(config) => WarcSource::S3(config),
        }
    }
}

#[derive(Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Clone)]
pub struct Job {
    pub config: JobConfig,
    pub warc_paths: Vec<String>,
}

pub fn open_host_graph_writer<P: AsRef<Path>>(
    path: P,
    host_centrality_store: Option<Arc<speedy_kv::Db<NodeID, u64>>>,
) -> webgraph::WebgraphWriter {
    WebgraphWriter::new(
        path,
        crate::executor::Executor::single_thread(),
        webgraph::Compression::Lz4,
        host_centrality_store,
    )
}

pub fn open_page_graph_writer<P: AsRef<Path>>(
    path: P,
    host_centrality_store: Option<Arc<speedy_kv::Db<NodeID, u64>>>,
) -> webgraph::WebgraphWriter {
    WebgraphWriter::new(
        path,
        crate::executor::Executor::single_thread(),
        webgraph::Compression::Lz4,
        host_centrality_store,
    )
}

fn canonical_or_self(index: &CanonicalIndex, url: Url) -> Url {
    if let Some(url) = index.get(&url).unwrap() {
        url
    } else {
        url
    }
}

pub struct WebgraphWorker {
    pub host_graph: Option<webgraph::WebgraphWriter>,
    pub page_graph: Option<webgraph::WebgraphWriter>,
    pub canonical_index: Option<Arc<CanonicalIndex>>,
}

impl WebgraphWorker {
    pub fn process_job(&mut self, job: &Job) {
        let name = job.warc_paths.first().unwrap().split('/').last().unwrap();

        info!("processing {}", name);

        let source = WarcSource::from(job.config.clone());

        let warc_files = download_all_warc_files(&job.warc_paths, &source);
        pin!(warc_files);

        for file in warc_files.by_ref() {
            for record in file.records().flatten() {
                let webpage =
                    match Html::parse_without_text(&record.response.body, &record.request.url) {
                        Ok(webpage) => webpage,
                        Err(err) => {
                            tracing::error!("error parsing webpage: {}", err);
                            continue;
                        }
                    };

                for mut link in webpage
                    .anchor_links()
                    .into_iter()
                    .filter(|link| matches!(link.destination.scheme(), "http" | "https"))
                {
                    let mut source = link.source.clone();
                    let mut destination = link.destination.clone();

                    if let Some(index) = &self.canonical_index {
                        source = canonical_or_self(index, source);
                        destination = canonical_or_self(index, destination);
                    }

                    link.text = link.text.chars().take(128).collect();

                    let mut source = Node::from(source);

                    let mut destination = Node::from(destination);

                    trace!("inserting link {:?}", link);
                    if let Some(graph) = self.page_graph.as_mut() {
                        graph.insert(
                            source.clone(),
                            destination.clone(),
                            link.text.clone(),
                            link.rel,
                        )
                    }

                    let dest_domain = link.destination.root_domain();
                    let source_domain = link.source.root_domain();
                    if dest_domain.is_some()
                        && source_domain.is_some()
                        && dest_domain != source_domain
                    {
                        source = source.into_host();
                        destination = destination.into_host();

                        if let Some(graph) = self.host_graph.as_mut() {
                            graph.insert(source, destination, link.text, link.rel)
                        }
                    }
                }
            }

            if let Some(graph) = self.host_graph.as_mut() {
                graph.commit()
            }
            if let Some(graph) = self.page_graph.as_mut() {
                graph.commit()
            }
        }

        info!("{} done", name);
    }
}

pub struct Webgraph {}

impl Webgraph {
    pub fn run(config: &WebgraphConstructConfig) -> Result<()> {
        if config.page_graph_base_path.is_none() && config.host_graph_base_path.is_none() {
            bail!("either page_graph_base_path or host_graph_base_path must be set");
        }

        let warc_paths = config.warc_source.paths()?;

        let job_config = JobConfig::from(config.warc_source.clone());

        let jobs: Vec<_> = warc_paths
            .into_iter()
            .skip(config.skip_warc_files.unwrap_or(0))
            .take(config.limit_warc_files.unwrap_or(usize::MAX))
            .chunks(config.batch_size.unwrap_or(1))
            .into_iter()
            .map(|warc_paths| Job {
                config: job_config.clone(),
                warc_paths: warc_paths.collect_vec(),
            })
            .collect_vec();

        let canonical_index = if let Some(index_path) = &config.canonical_index_path {
            Some(Arc::new(CanonicalIndex::open(index_path)?))
        } else {
            None
        };

        let host_centrality_rank_store = if let Some(path) = &config.host_centrality_rank_store_path
        {
            Some(Arc::new(speedy_kv::Db::open_or_create(path)?))
        } else {
            None
        };

        let num_workers = usize::from(std::thread::available_parallelism()?);

        let mut handlers = Vec::new();
        let host_path = &config.host_graph_base_path;
        let page_path = &config.page_graph_base_path;

        const MAX_FINALIZE_CONCURRENT: usize = 8;
        let (s, r) = crossbeam_channel::bounded(MAX_FINALIZE_CONCURRENT);

        for _ in 0..MAX_FINALIZE_CONCURRENT {
            s.send(())?;
        }

        for i in 0..num_workers {
            let host_path = host_path.clone();
            let host_path = host_path
                .as_ref()
                .map(|p| Path::new(p).join(format!("worker_{i}")));

            let page_path = page_path.clone();
            let page_path = page_path
                .as_ref()
                .map(|p| Path::new(p).join(format!("worker_{i}")));

            let mut worker = WebgraphWorker {
                host_graph: host_path
                    .as_ref()
                    .map(|p| open_host_graph_writer(p, host_centrality_rank_store.clone())),
                page_graph: page_path
                    .as_ref()
                    .map(|p| open_page_graph_writer(p, host_centrality_rank_store.clone())),
                canonical_index: canonical_index.clone(),
            };

            let jobs = jobs.clone();
            let (s, r) = (s.clone(), r.clone());
            handlers.push(std::thread::spawn(move || {
                for job in jobs.iter().skip(i).step_by(num_workers) {
                    worker.process_job(job);
                }

                r.recv().unwrap();

                let host = worker.host_graph.map(|graph| graph.finalize());
                let page = worker.page_graph.map(|graph| graph.finalize());

                s.send(()).unwrap();
                (host, page)
            }));
        }

        let mut graphs = Vec::new();
        for handler in handlers {
            graphs.push(handler.join().unwrap());
        }

        let (mut host_graph, mut page_graph) = graphs.pop().unwrap();

        for (other_host, other_page) in graphs {
            if let (Some(graph), Some(other)) = (host_graph.as_mut(), other_host) {
                graph.merge(other)?;
            }

            if let (Some(graph), Some(other)) = (page_graph.as_mut(), other_page) {
                graph.merge(other)?;
            }
        }

        if config.merge_all_segments {
            if let Some(host) = host_graph.as_mut() {
                host.optimize_read(); // save space in id2node db
                host.merge_all_segments(Default::default())?;
            }

            if let Some(page) = page_graph.as_mut() {
                page.optimize_read(); // save space in id2node db
                page.merge_all_segments(Default::default())?;
            }
        }

        if let Some(host) = host_graph.as_mut() {
            host.optimize_read();
            crate::mv(host.path(), config.host_graph_base_path.as_ref().unwrap())?;
        }

        if let Some(page) = page_graph.as_mut() {
            page.optimize_read();
            crate::mv(page.path(), config.page_graph_base_path.as_ref().unwrap())?;
        }

        Ok(())
    }
}
