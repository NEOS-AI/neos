// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use super::script_tokenizer::ScriptTokenizer;

#[derive(Debug, PartialEq, Default, Clone, Copy)]
pub enum Script {
    Latin,

    #[default]
    Other,
}

impl From<char> for Script {
    fn from(c: char) -> Self {
        if c.is_ascii() {
            Script::Latin
        } else {
            Script::Other
        }
    }
}

impl Script {
    pub fn tokenizer(self) -> Box<dyn ScriptTokenizer> {
        match self {
            Script::Latin => Box::new(super::script_tokenizer::Latin),
            Script::Other => Box::new(super::script_tokenizer::Latin),
        }
    }
}
