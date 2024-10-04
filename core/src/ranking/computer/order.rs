// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is copied from Stract, which is licensed under the GNU Affero General Public License.

use tantivy::DocId;

use crate::{
    enum_map::EnumMap,
    ranking::{ComputedSignal, CoreSignal, CoreSignalEnum},
    schema::{text_field::TextField, TextFieldEnum},
};

use super::SignalComputer;

#[derive(Clone)]
pub struct SignalComputeOrder {
    text_signals: EnumMap<TextFieldEnum, NGramComputeOrder>,
    other_signals: Vec<CoreSignalEnum>,
}

impl SignalComputeOrder {
    pub fn new() -> Self {
        let mut text_signals = EnumMap::new();
        let mut other_signals = Vec::new();

        for signal in CoreSignalEnum::all() {
            if let Some(text_field) = signal.as_textfield() {
                if signal.has_sibling_ngrams() {
                    let mono = text_field.monogram_field();

                    if !text_signals.contains_key(mono) {
                        text_signals.insert(mono, NGramComputeOrder::default());
                    }

                    let ngram = text_field.ngram_size();
                    text_signals.get_mut(mono).unwrap().push(signal, ngram);
                } else {
                    other_signals.push(signal);
                }
            } else {
                other_signals.push(signal);
            }
        }

        Self {
            text_signals,
            other_signals,
        }
    }

    pub fn compute<'a>(
        &'a self,
        doc: DocId,
        signal_computer: &'a SignalComputer,
    ) -> impl Iterator<Item = ComputedSignal> + 'a {
        self.text_signals
            .values()
            .flat_map(move |ngram| ngram.compute(doc, signal_computer))
            .chain(self.other_signals.iter().map(move |&signal| {
                let calc = signal.compute(doc, signal_computer);

                ComputedSignal {
                    signal: signal.into(),
                    calc,
                }
            }))
    }
}

impl Default for SignalComputeOrder {
    fn default() -> Self {
        Self::new()
    }
}

/// If an ngram of size n matches the query for a given document in a given field,
/// the score of all ngrams where n' < n is dampened by NGRAM_DAMPENING.
///
/// A dampening factor of 0.0 means that we ignore all ngrams where n' < n. A dampening factor of 1.0
/// does not dampen any ngrams.
const NGRAM_DAMPENING: f64 = 0.4;

#[derive(Debug, Default, Clone)]
pub struct NGramComputeOrder {
    /// ordered by descending ngram size. e.g. [title_bm25_trigram, title_bm25_bigram, title_bm25]
    signals: Vec<(usize, CoreSignalEnum)>,
}

impl NGramComputeOrder {
    fn push(&mut self, signal: CoreSignalEnum, ngram: usize) {
        self.signals.push((ngram, signal));
        self.signals.sort_unstable_by(|(a, _), (b, _)| b.cmp(a));
    }

    fn compute<'a>(
        &'a self,
        doc: DocId,
        signal_computer: &'a SignalComputer,
    ) -> impl Iterator<Item = ComputedSignal> + 'a {
        let mut hits = 0;

        self.signals.iter().map(|(_, s)| s).map(move |&signal| {
            let calc = signal.compute(doc, signal_computer);

            let mut computed = ComputedSignal {
                signal: signal.into(),
                calc,
            };

            computed.calc.score *= NGRAM_DAMPENING.powi(hits);

            if computed.calc.score > 0.0 {
                hits += 1;
            }

            computed
        })
    }
}
