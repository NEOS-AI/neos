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

use std::fs::File;
use std::io::BufReader;
use std::{collections::HashMap, path::Path};

use crate::enum_map::EnumMap;
use crate::ranking::SignalEnum;
use crate::Result;

#[derive(serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Debug)]
struct SerialziedLinearRegression {
    weights: HashMap<SignalEnum, f64>,
}

impl From<SerialziedLinearRegression> for LinearRegression {
    fn from(model: SerialziedLinearRegression) -> Self {
        let mut weights = EnumMap::new();

        for (signal, weight) in model.weights {
            weights.insert(signal, weight);
        }

        Self { weights }
    }
}

#[derive(serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, Debug)]
pub struct LinearRegression {
    pub weights: EnumMap<SignalEnum, f64>,
}

impl LinearRegression {
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self> {
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        let model: SerialziedLinearRegression = serde_json::from_reader(reader)?;
        Ok(model.into())
    }
}
