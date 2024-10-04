// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use std::path::Path;

use itertools::Itertools;

use tokio::pin;
use tracing::{info, trace, warn};

use crate::config;
use crate::entrypoint::download_all_warc_files;
use crate::index::Index;
use crate::warc::PayloadType;

use super::{IndexableWebpage, IndexingWorker};

#[derive(Debug, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode)]
pub struct Job {
    pub source_config: config::WarcSource,
    pub warc_path: String,
    pub base_path: String,
    pub settings: JobSettings,
}

#[derive(
    Debug, Clone, Copy, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode,
)]
pub struct JobSettings {
    pub host_centrality_threshold: Option<f64>,
    pub minimum_clean_words: Option<usize>,
    pub batch_size: usize,
    pub autocommit_after_num_inserts: usize,
}

impl Job {
    pub fn process(&self, worker: &IndexingWorker) -> Index {
        let name = self.warc_path.split('/').last().unwrap();

        let mut has_host_centrality = false;
        let mut has_page_centrality = false;
        let mut has_backlinks = false;

        info!("processing {}", name);

        let mut index = Index::open(Path::new(&self.base_path).join(name)).unwrap();
        index.prepare_writer().unwrap();

        let paths = vec![self.warc_path.clone()];
        let warc_files = download_all_warc_files(&paths, &self.source_config);
        pin!(warc_files);

        let mut num_inserts_since_commit = 0;

        for file in warc_files.by_ref() {
            let mut batch = Vec::with_capacity(self.settings.batch_size);

            for chunk in file
                .records()
                .flatten()
                .filter(|record| match &record.response.payload_type {
                    Some(payload_type) => matches!(payload_type, PayloadType::Html),
                    None => true,
                })
                .filter(|record| !worker.see(&record.request.url))
                .chunks(self.settings.batch_size)
                .into_iter()
            {
                batch.clear();

                for record in chunk {
                    batch.push(IndexableWebpage::from(record));
                }

                let prepared = crate::block_on(worker.prepare_webpages(&batch));

                for webpage in &prepared {
                    if webpage.host_centrality > 0.0 {
                        has_host_centrality = true;
                    }

                    if webpage.page_centrality > 0.0 {
                        has_page_centrality = true;
                    }

                    if !webpage.backlinks().is_empty() {
                        has_backlinks = true;
                    }
                    trace!("inserting webpage: {:?}", webpage.html.url());
                    trace!("title = {:?}", webpage.html.title());
                    trace!("text = {:?}", webpage.html.clean_text());

                    if let Err(err) = index.insert(webpage) {
                        warn!("{:?}", err);
                        panic!();
                    }

                    num_inserts_since_commit += 1;
                }

                if num_inserts_since_commit >= self.settings.autocommit_after_num_inserts {
                    index.commit().unwrap();
                    num_inserts_since_commit = 0;
                }
            }
        }
        index.commit().unwrap();

        if !has_host_centrality {
            warn!("no host centrality values found in {}", name);
        }

        if !has_page_centrality && worker.page_centrality_store().is_some() {
            warn!("no page centrality values found in {}", name);
        }

        if !has_backlinks && worker.page_webgraph().is_some() {
            warn!("no backlinks found in {}", name);
        }

        index.inverted_index.merge_into_max_segments(1).unwrap();

        info!("{} done", name);

        index
    }
}
