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

use itertools::Itertools;
use regex::Regex;

use std::{
    fs::File,
    io::{BufRead, BufReader},
    path::Path,
};
use utoipa::ToSchema;

use anyhow::{anyhow, Result};
use rio_api::parser::TriplesParser;
use rio_turtle::TurtleParser;
use std::collections::HashMap;

static VALUE_STR_REGEX: std::sync::LazyLock<Regex> =
    std::sync::LazyLock::new(|| regex::Regex::new(r#""(.*)"@"#).expect("Failed to compile regex"));

#[derive(
    Debug,
    Clone,
    PartialEq,
    Eq,
    Hash,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    ToSchema,
)]
#[serde(rename_all = "camelCase", transparent)]
pub struct Lemma(String);

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct NormalizedLemma(String);

impl Lemma {
    fn normalize(&self) -> NormalizedLemma {
        NormalizedLemma(self.0.to_lowercase())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct Id(String);

#[derive(
    Debug,
    Clone,
    PartialEq,
    Eq,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    ToSchema,
)]
#[serde(rename_all = "camelCase", transparent)]
pub struct Definition(String);

#[derive(
    Debug,
    Clone,
    PartialEq,
    Eq,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    ToSchema,
)]
#[serde(rename_all = "camelCase", transparent)]
pub struct Example(String);

#[derive(
    Debug,
    Clone,
    PartialOrd,
    Ord,
    PartialEq,
    Eq,
    Hash,
    serde::Serialize,
    serde::Deserialize,
    bincode::Encode,
    bincode::Decode,
    ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub enum PartOfSpeech {
    Noun,
    Verb,
    Adjective,
    AdjectiveSatellite,
    Adverb,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Info {
    id: Id,
    definition: Definition,
    examples: Vec<Example>,
    similar: Vec<Id>,
    hyponyms: Vec<Id>,
    hypernyms: Vec<Id>,
    pos: PartOfSpeech,
}

impl Info {
    fn build_definition(concept: &NodeQuery<'_>) -> Definition {
        let def = concept
            .single_edge(|e| e.label.contains("#definition"))
            .unwrap()
            .to
            .single_edge(|e| e.label.contains("#value"))
            .unwrap()
            .to
            .node
            .0
            .clone();

        let def = VALUE_STR_REGEX
            .captures(&def)
            .unwrap()
            .get(1)
            .unwrap()
            .as_str()
            .to_string();

        Definition(def)
    }

    fn build_examples(concept: &NodeQuery<'_>) -> Vec<Example> {
        concept
            .filtered_edges(|e| e.label.contains("#example"))
            .into_iter()
            .map(|e| {
                e.to.single_edge(|e| e.label.contains("#value"))
                    .unwrap()
                    .to
                    .node
                    .0
                    .clone()
            })
            .map(|e| {
                VALUE_STR_REGEX
                    .captures(&e)
                    .unwrap()
                    .get(1)
                    .unwrap()
                    .as_str()
                    .to_string()
            })
            .map(Example)
            .collect()
    }

    fn build_similar(concept: &NodeQuery<'_>) -> Vec<Id> {
        concept
            .filtered_edges(|e| e.label.contains("#similar"))
            .into_iter()
            .map(|e| Id(e.to.node.0.clone()))
            .collect()
    }

    fn build_hyponyms(concept: &NodeQuery<'_>) -> Vec<Id> {
        concept
            .filtered_edges(|e| e.label.contains("#hyponym"))
            .into_iter()
            .map(|e| Id(e.to.node.0.clone()))
            .collect()
    }

    fn build_hypernyms(concept: &NodeQuery<'_>) -> Vec<Id> {
        concept
            .filtered_edges(|e| e.label.contains("#hypernym"))
            .into_iter()
            .map(|e| Id(e.to.node.0.clone()))
            .collect()
    }

    fn build_pos(concept: &NodeQuery<'_>) -> Result<PartOfSpeech> {
        let pos = concept
            .single_edge(|e| e.label.contains("#partOfSpeech"))
            .unwrap()
            .to
            .node
            .0
            .split_once('#')
            .unwrap()
            .1
            .to_string()
            .replace('>', "");

        match pos.as_str() {
            "noun" => Ok(PartOfSpeech::Noun),
            "adjective_satellite" => Ok(PartOfSpeech::AdjectiveSatellite),
            "verb" => Ok(PartOfSpeech::Verb),
            "adverb" => Ok(PartOfSpeech::Adverb),
            "adjective" => Ok(PartOfSpeech::Adjective),
            _ => Err(anyhow!("Unknown part of speech: {}", pos)),
        }
    }
}

pub struct Dictionary {
    map: HashMap<Id, Info>,
    lemmas: HashMap<NormalizedLemma, Vec<Id>>,
    reverse_lemmas: HashMap<Id, Vec<NormalizedLemma>>,
    spellings: HashMap<NormalizedLemma, Lemma>,

    matchers: Vec<Regex>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct Node(String);

#[derive(Debug)]
struct Edge {
    source: Node,
    label: String,
    target: Node,
}

#[derive(Debug)]
struct Graph {
    map: HashMap<Node, Vec<Edge>>,
}

impl Graph {
    pub fn new() -> Self {
        Self {
            map: HashMap::new(),
        }
    }

    pub fn insert(&mut self, edge: Edge) {
        self.map.entry(edge.source.clone()).or_default().push(edge);
    }

    pub fn get(&self, node: &Node) -> Option<&Vec<Edge>> {
        self.map.get(node)
    }
}

#[derive(Debug)]
struct EdgeQuery<'a> {
    to: NodeQuery<'a>,
    label: &'a str,
}

struct NodeQuery<'a> {
    node: &'a Node,
    graph: &'a Graph,
}

impl std::fmt::Debug for NodeQuery<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NodeQuery")
            .field("node", &self.node)
            .finish()
    }
}

impl<'a> NodeQuery<'a> {
    pub fn new(node: &'a Node, graph: &'a Graph) -> Self {
        Self { node, graph }
    }

    pub fn edges(&self) -> Vec<EdgeQuery<'a>> {
        self.graph
            .get(self.node)
            .map(|edges| {
                edges
                    .iter()
                    .map(|e| EdgeQuery {
                        to: NodeQuery::new(&e.target, self.graph),
                        label: &e.label,
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    pub fn filtered_edges<F>(&self, f: F) -> Vec<EdgeQuery<'a>>
    where
        F: Fn(&EdgeQuery<'a>) -> bool,
    {
        self.edges().into_iter().filter(f).collect()
    }

    pub fn single_edge<F>(&self, f: F) -> Option<EdgeQuery<'a>>
    where
        F: Fn(&EdgeQuery<'a>) -> bool,
    {
        self.filtered_edges(f).into_iter().next()
    }
}

impl<'a> Clone for NodeQuery<'a> {
    fn clone(&self) -> Self {
        Self {
            node: self.node,
            graph: self.graph,
        }
    }
}

impl Dictionary {
    fn empty() -> Result<Self> {
        Ok(Self {
            map: HashMap::new(),
            lemmas: HashMap::new(),
            reverse_lemmas: HashMap::new(),
            spellings: HashMap::new(),
            matchers: vec![
                Regex::new(r"^definition of ([\w| ]+)$")?,
                Regex::new(r"^meaning of ([\w| ]+)$")?,
                Regex::new(r"^synonym of ([\w| ]+)$")?,
                Regex::new(r"^synonyms of ([\w| ]+)$")?,
                //
                Regex::new(r"^definition ([\w| ]+)$")?,
                Regex::new(r"^meaning ([\w| ]+)$")?,
                Regex::new(r"^synonym ([\w| ]+)$")?,
                Regex::new(r"^synonyms ([\w| ]+)$")?,
                //
                Regex::new(r"^([\w| ]+) definition$")?,
                Regex::new(r"^([\w| ]+) meaning$")?,
                Regex::new(r"^([\w| ]+) synonym$")?,
                Regex::new(r"^([\w| ]+) synonyms$")?,
                //
                Regex::new(r"^define ([\w| ]+)$")?,
            ],
        })
    }

    fn get_by_id(&self, id: Id) -> Option<&Info> {
        self.map.get(&id)
    }

    fn get(&self, lemma: Lemma) -> Vec<Info> {
        match self.lemmas.get(&lemma.normalize()) {
            Some(ids) => ids
                .iter()
                .filter_map(|id| self.get_by_id(id.clone()))
                .cloned()
                .collect(),
            None => Vec::new(),
        }
    }

    fn query_lemma(&self, query: &str) -> Option<String> {
        for matcher in &self.matchers {
            if let Some(captures) = matcher.captures(query) {
                return captures.get(1).map(|m| m.as_str().to_string());
            }
        }

        None
    }

    fn ids2lemmas(&self, ids: &[Id]) -> Vec<Lemma> {
        ids.iter()
            .filter_map(|id| self.get_by_id(id.clone()))
            .filter_map(|i| self.reverse_lemmas.get(&i.id))
            .flatten()
            .filter_map(|l| self.spellings.get(l))
            .cloned()
            .collect()
    }

    pub fn lookup(&self, query: &str) -> Option<ThesaurusWidget> {
        let query = self.query_lemma(query)?;
        let lemma = Lemma(query);

        let infos = self.get(lemma.clone());

        if infos.is_empty() {
            return None;
        }

        let mut meanings: HashMap<PartOfSpeech, Vec<WordMeaning>> = HashMap::new();

        for info in infos {
            meanings
                .entry(info.pos.clone())
                .or_default()
                .push(WordMeaning {
                    definition: info.definition.clone(),
                    examples: info.examples.clone(),
                    similar: self
                        .ids2lemmas(&info.similar)
                        .into_iter()
                        .filter(|l| l != &lemma)
                        .dedup_by(|a, b| a == b)
                        .take(5)
                        .collect(),
                });
        }

        Some(ThesaurusWidget {
            term: lemma,
            meanings: meanings
                .into_iter()
                .map(|(pos, meanings)| PartOfSpeechMeaning { pos, meanings })
                .sorted()
                .collect(),
        })
    }

    pub fn insert(&mut self, lemma: Lemma, info: Info) {
        let normalized = lemma.clone().normalize();

        self.map.insert(info.id.clone(), info.clone());

        self.lemmas
            .entry(normalized.clone())
            .or_default()
            .push(info.id.clone());

        self.reverse_lemmas
            .entry(info.id.clone())
            .or_default()
            .push(normalized.clone());

        self.spellings.insert(normalized, lemma);
    }

    fn entry_info(entry: NodeQuery<'_>) -> Result<Vec<Info>> {
        let mut res = Vec::new();
        for sense in entry.filtered_edges(|e| e.label.contains("#sense")) {
            let concept = sense
                .to
                .single_edge(|e| e.label.contains("#isLexicalizedSenseOf"))
                .unwrap()
                .to;
            let id = Id(concept.node.0.clone());

            let definition = Info::build_definition(&concept);
            let examples = Info::build_examples(&concept);
            let similar = Info::build_similar(&concept);
            let hyponyms = Info::build_hyponyms(&concept);
            let hypernyms = Info::build_hypernyms(&concept);
            let pos = Info::build_pos(&concept)?;

            res.push(Info {
                id,
                definition,
                examples,
                similar,
                hyponyms,
                hypernyms,
                pos,
            });
        }

        res.sort_by_key(|i| i.similar.len() + i.hyponyms.len() + i.hypernyms.len());
        res.reverse();

        Ok(res)
    }

    fn build_graph<R: BufRead>(reader: R) -> Result<Graph> {
        let mut parser = TurtleParser::new(reader, None);
        let mut graph = Graph::new();

        parser.parse_all(&mut |t| {
            let edge = Edge {
                source: Node(t.subject.to_string()),
                label: t.predicate.to_string(),
                target: Node(t.object.to_string()),
            };

            graph.insert(edge);

            Ok::<_, anyhow::Error>(())
        })?;

        Ok(graph)
    }

    fn build_lexical_entries(graph: &Graph) -> Vec<&'_ Node> {
        let mut lexical_entries = Vec::new();

        for (node, edges) in &graph.map {
            if let Some(e) = edges.iter().find(|e| e.label.contains("#type")) {
                if e.target.0.contains("#LexicalEntry") {
                    lexical_entries.push(node);
                }
            }
        }

        lexical_entries
    }

    pub fn build<P: AsRef<Path>>(path: P) -> Result<Self> {
        let reader = BufReader::new(File::open(path)?);
        let graph = Self::build_graph(reader)?;
        let lexical_entries = Self::build_lexical_entries(&graph);

        let mut dict = Self::empty()?;

        for entry in lexical_entries {
            let entry = NodeQuery::new(entry, &graph);

            let written_rep = entry
                .single_edge(|e| e.label.contains("#canonicalForm"))
                .unwrap()
                .to
                .single_edge(|e| e.label.contains("#writtenRep"))
                .unwrap()
                .to
                .node
                .0
                .clone();

            let written_rep = VALUE_STR_REGEX
                .captures(&written_rep)
                .unwrap()
                .get(1)
                .unwrap()
                .as_str()
                .to_string();

            let lemma = Lemma(written_rep);

            for info in Self::entry_info(entry)? {
                dict.insert(lemma.clone(), info);
            }
        }

        Ok(dict)
    }
}

#[derive(
    Debug, Clone, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub struct WordMeaning {
    pub definition: Definition,
    pub examples: Vec<Example>,
    pub similar: Vec<Lemma>,
}

#[derive(
    Debug, Clone, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub struct PartOfSpeechMeaning {
    pub pos: PartOfSpeech,
    pub meanings: Vec<WordMeaning>,
}

impl PartialEq for PartOfSpeechMeaning {
    fn eq(&self, other: &Self) -> bool {
        self.pos == other.pos
    }
}

impl Eq for PartOfSpeechMeaning {}

impl Ord for PartOfSpeechMeaning {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.pos.cmp(&other.pos)
    }
}

impl PartialOrd for PartOfSpeechMeaning {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(
    Debug, Clone, serde::Serialize, serde::Deserialize, bincode::Encode, bincode::Decode, ToSchema,
)]
#[serde(rename_all = "camelCase")]
pub struct ThesaurusWidget {
    pub term: Lemma,
    pub meanings: Vec<PartOfSpeechMeaning>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_dict() {
        let data_path = Path::new("../../data/english-wordnet-2022-subset.ttl");
        if !data_path.exists() {
            // Skip the test if the test data is not available
            return;
        }
        let dict = Dictionary::build(data_path).unwrap();

        let infos = dict.get(Lemma("barely".to_string()));

        let definitions = infos
            .iter()
            .map(|i| i.definition.0.clone())
            .collect::<Vec<_>>();

        assert!(definitions.contains(&String::from("only a very short time before")));
        assert!(definitions.contains(&String::from("by a little")));
        assert!(definitions.contains(&String::from("almost not")));
    }
}
