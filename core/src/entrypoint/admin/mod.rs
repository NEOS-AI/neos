// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use std::{
    net::SocketAddr,
    path::{Path, PathBuf},
};

use crate::{distributed::sonic, entrypoint::api, Result};

const CONFIG_FOLDER: &str = "~/.config/stract";
const CONFIG_NAME: &str = "admin.toml";

trait ExpandUser {
    fn expand_user(&self) -> PathBuf;
}

impl ExpandUser for Path {
    fn expand_user(&self) -> PathBuf {
        let mut path = self.to_path_buf();
        if path.starts_with("~") {
            if let Some(home) = dirs::home_dir() {
                path = home.join(path.strip_prefix("~").unwrap());
            }
        }

        path
    }
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct Config {
    pub host: SocketAddr,
}

impl Config {
    pub fn save(&self) -> Result<()> {
        let path = Path::new(CONFIG_FOLDER).expand_user();

        if !path.exists() {
            std::fs::create_dir_all(&path)?;
        }

        let path = path.join(CONFIG_NAME);

        let config = toml::to_string(&self).unwrap();
        std::fs::write(path, config)?;

        Ok(())
    }

    pub fn load() -> Result<Self> {
        let path = Path::new(CONFIG_FOLDER).expand_user().join(CONFIG_NAME);

        let config = std::fs::read_to_string(path)?;
        let config: Config = toml::from_str(&config)?;

        Ok(config)
    }
}

impl Drop for Config {
    fn drop(&mut self) {
        self.save().ok();
    }
}

pub fn init(host: SocketAddr) -> Result<()> {
    let config = Config { host };
    config.save()?;

    Ok(())
}

pub async fn status() -> Result<()> {
    let config = Config::load()?;
    let mut conn = sonic::service::Connection::create(config.host).await?;

    let status = conn.send_without_timeout(api::ClusterStatus).await?;

    println!("Members:");
    for member in status.members {
        println!("  - {}: {}", member.id, member.service);
    }

    Ok(())
}

pub async fn top_keyphrases(top: usize) -> Result<()> {
    let config = Config::load()?;
    let mut conn = sonic::service::Connection::create(config.host).await?;

    let keyphrases = conn
        .send_without_timeout(api::TopKeyphrases { top })
        .await?;

    println!("id,text,score");
    for (i, keyphrase) in keyphrases.iter().enumerate() {
        println!("{},{},{}", i + 1, keyphrase.text(), keyphrase.score());
    }

    Ok(())
}

pub async fn index_size() -> Result<()> {
    let config = Config::load()?;
    let mut conn: sonic::service::Connection<api::ManagementService> =
        sonic::service::Connection::create(config.host).await?;

    let size: api::SizeResponse = conn.send_without_timeout(api::Size).await?;

    println!("Number of pages in index: {}", size.pages);

    Ok(())
}
