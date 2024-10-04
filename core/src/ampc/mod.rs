// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use self::{job::Job, worker::WorkerRef};
use crate::distributed::sonic;

mod coordinator;
pub mod dht;
pub mod dht_conn;
mod finisher;
mod job;
mod mapper;
pub mod prelude;
mod server;
mod setup;
mod worker;

use self::prelude::*;

pub use coordinator::Coordinator;
pub use dht_conn::{DefaultDhtTable, DhtConn, DhtTable, DhtTables, Table};
pub use server::Server;
pub use worker::{Message, RequestWrapper, Worker};

#[derive(serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Clone)]
pub enum CoordReq<J, M, T> {
    CurrentJob,
    ScheduleJob { job: J, mapper: M },
    Setup { dht: DhtConn<T> },
}

#[derive(serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode)]
pub enum CoordResp<J> {
    CurrentJob(Option<J>),
    ScheduleJob(()),
    Setup(()),
}

#[derive(serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Clone)]
pub enum Req<J, M, R, T> {
    Coordinator(CoordReq<J, M, T>),
    User(R),
}

type JobReq<J> =
    Req<J, <J as Job>::Mapper, <<J as Job>::Worker as Worker>::Request, <J as Job>::DhtTables>;

type JobResp<J> = Resp<J, <<J as Job>::Worker as Worker>::Response>;

#[derive(serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode)]
pub enum Resp<J, R> {
    Coordinator(CoordResp<J>),
    User(R),
}

type JobDht<J> = DhtConn<<J as Job>::DhtTables>;

pub type JobConn<J> = sonic::Connection<JobReq<J>, JobResp<J>>;

#[must_use = "this `JobScheduled` may not have scheduled the job on any worker"]
enum JobScheduled {
    Success(WorkerRef),
    NoAvailableWorkers,
}
