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

use super::Result;
use std::{path::Path, str::FromStr};

use fnv::FnvHashMap;
use whatlang::Lang;

use crate::{
    config::CorrectionConfig,
    web_spell::stupid_backoff::{IntoMiddle, LeftToRight, RightToLeft},
};

use super::{error_model, Correction, CorrectionTerm, Error, ErrorModel, StupidBackoff, TermDict};

struct LangSpellChecker {
    term_dict: TermDict,
    language_model: StupidBackoff,
    error_model: ErrorModel,
    config: CorrectionConfig,
}

impl LangSpellChecker {
    fn open<P: AsRef<Path>>(path: P, config: CorrectionConfig) -> Result<Self> {
        let term_dict = TermDict::open(path.as_ref().join("term_dict"))?;
        let language_model = StupidBackoff::open(path.as_ref().join("stupid_backoff"))?;
        let error_model = ErrorModel::open(path.as_ref().join("error_model.json"))?;

        Ok(Self {
            term_dict,
            language_model,
            error_model,
            config,
        })
    }

    fn candidates(&self, term: &str) -> Vec<String> {
        // one edit for words of
        // up to four characters, two edits for up to twelve
        // characters, and three for longer
        let max_edit_distance = if term.len() <= 4 {
            1
        } else if term.len() <= 12 {
            2
        } else {
            3
        };

        self.term_dict.search(term, max_edit_distance)
    }

    fn lm_logprob(&self, term_idx: usize, context: &[String]) -> f64 {
        if term_idx == 0 {
            let strat = RightToLeft;
            self.language_model.log_prob(context, strat)
        } else if term_idx == context.len() - 1 {
            let strat = LeftToRight;
            self.language_model.log_prob(context, strat)
        } else {
            let strat = IntoMiddle::default();
            self.language_model.log_prob(context, strat)
        }
    }

    fn score_candidates(
        &self,
        term: &str,
        candidates: &[String],
        context: Vec<String>,
        term_idx: usize,
    ) -> Option<(String, f64)> {
        let mut best_term: Option<(String, f64)> = None;
        let mut context = context;

        for candidate in candidates {
            if candidate.as_str() == term {
                continue;
            }

            context[term_idx].clone_from(candidate);

            let log_prob = self.lm_logprob(term_idx, &context);

            let scaled_lm_log_prob = self.config.lm_prob_weight * log_prob;

            let error_log_prob = if candidate.as_str() != term {
                match error_model::possible_errors(term, candidate) {
                    Some(error_seq) => {
                        (1.0 - self.config.misspelled_prob).log2()
                            + self.error_model.log_prob(&error_seq)
                    }
                    None => 0.0,
                }
            } else {
                self.config.misspelled_prob.log2()
            };
            tracing::trace!(?candidate, ?scaled_lm_log_prob, ?error_log_prob);

            let score = scaled_lm_log_prob + error_log_prob;

            if best_term.is_none() || score > best_term.as_ref().unwrap().1 {
                best_term = Some((candidate.clone(), score));
            }
        }

        best_term
    }

    fn correct_once(&self, text: &str) -> Option<Correction> {
        let orig_terms = super::tokenize(text);
        let mut terms = orig_terms.clone();

        let mut corrections = Vec::new();

        let num_terms = terms.len();
        for i in 0..num_terms {
            let term = &terms[i];
            let candidates = self.candidates(term);

            if candidates.is_empty() {
                tracing::debug!("no candidates for {}", term);
                continue;
            }

            // context around term
            // if term is first or last, use two next/previous terms if they exist
            // otherwise use one next/previous term (if they exist)
            let mut context = Vec::new();
            let mut j = i.saturating_sub(2);
            let mut this_term_context_idx = None;
            let limit = std::cmp::min(i + 3, terms.len());

            while j < limit {
                context.push(terms[j].clone());
                if i == j {
                    this_term_context_idx = Some(context.len() - 1);
                }
                j += 1;
            }

            let this_term_context_idx = this_term_context_idx.unwrap();
            let term_log_prob = self.lm_logprob(this_term_context_idx, &context);
            let scaled_term_log_prob = self.config.lm_prob_weight * term_log_prob
                + ((1.0 - self.config.misspelled_prob).log2());

            tracing::debug!(?term, ?term_log_prob, ?scaled_term_log_prob);

            if let Some((best_term, score)) =
                self.score_candidates(term, &candidates, context, this_term_context_idx)
            {
                let diff = score - scaled_term_log_prob;
                tracing::debug!(?best_term, ?score, ?diff);
                if diff.is_finite() && diff > self.config.correction_threshold {
                    corrections.push((i, best_term.clone()));
                    terms[i] = best_term; // make sure the next terms use the corrected context
                }
            }
        }

        if corrections.is_empty() {
            return None;
        }

        let mut res = Correction::empty(text.to_string());

        for (orig, possible_correction) in orig_terms.into_iter().zip(terms.into_iter()) {
            if orig == possible_correction {
                res.push(CorrectionTerm::NotCorrected(orig));
            } else {
                res.push(CorrectionTerm::Corrected {
                    orig,
                    correction: possible_correction,
                });
            }
        }

        Some(res)
    }

    fn correct(&self, text: &str) -> Option<Correction> {
        // TODO:
        // sometimes the text should be corrected more than once.
        // we should make sure to only correct each term once so we don't
        // get corrections to the corrections.
        self.correct_once(text.to_lowercase().as_str())
    }
}

pub struct SpellChecker {
    lang_spell_checkers: FnvHashMap<Lang, LangSpellChecker>,
}

impl SpellChecker {
    pub fn open<P: AsRef<Path>>(path: P, config: CorrectionConfig) -> Result<Self> {
        if !path.as_ref().exists() {
            return Err(Error::CheckerNotFound);
        }

        if !path.as_ref().is_dir() {
            return Err(Error::CheckerNotFound);
        }

        let mut lang_spell_checkers = FnvHashMap::default();

        for entry in std::fs::read_dir(path)? {
            let entry = entry?;
            let path = entry.path();

            if !path.is_dir() {
                continue;
            }

            let lang = match path.file_name().and_then(|s| s.to_str()) {
                Some(lang) => lang,
                None => continue,
            };

            let lang = match Lang::from_str(lang) {
                Ok(lang) => lang,
                Err(_) => {
                    tracing::warn!("Invalid language: {}", lang);
                    continue;
                }
            };

            let lang_spell_checker = LangSpellChecker::open(path, config)?;
            lang_spell_checkers.insert(lang, lang_spell_checker);
        }

        Ok(Self {
            lang_spell_checkers,
        })
    }
    pub fn correct(&self, text: &str, lang: &Lang) -> Option<Correction> {
        self.lang_spell_checkers
            .get(lang)
            .and_then(|s| s.correct(text))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn correction(orig: &str, corrected: &str) -> Correction {
        let mut res = Correction::empty(orig.to_string());

        for (orig, corrected) in super::super::tokenize(orig)
            .into_iter()
            .zip(super::super::tokenize(corrected))
        {
            if orig == corrected {
                res.push(CorrectionTerm::NotCorrected(orig));
            } else {
                res.push(CorrectionTerm::Corrected {
                    orig,
                    correction: corrected,
                });
            }
        }

        res
    }
    #[test]
    fn simple() {
        let path = Path::new("../data/web_spell/checker");

        if !path.exists() {
            return;
        }

        let conf = CorrectionConfig {
            correction_threshold: 16.0,
            ..Default::default()
        };

        let spell_checker = SpellChecker::open(path, conf).unwrap();

        assert_eq!(spell_checker.correct("hello", &Lang::Eng), None);
        assert_eq!(
            spell_checker.correct("dudw", &Lang::Eng),
            Some(correction("dudw", "dude"))
        );
    }
}
