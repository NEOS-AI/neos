// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use whatlang::Lang;

pub struct Stemmer(tantivy::tokenizer::Stemmer);

impl Stemmer {
    pub fn into_tantivy(self) -> tantivy::tokenizer::Stemmer {
        self.0
    }
}

impl From<Lang> for Stemmer {
    fn from(lang: Lang) -> Self {
        match lang {
            Lang::Dan => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Danish,
            )),
            Lang::Ara => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Arabic,
            )),
            Lang::Nld => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Dutch,
            )),
            Lang::Fin => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Finnish,
            )),
            Lang::Fra => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::French,
            )),
            Lang::Deu => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::German,
            )),
            Lang::Hun => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Hungarian,
            )),
            Lang::Ita => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Italian,
            )),
            Lang::Por => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Portuguese,
            )),
            Lang::Ron => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Romanian,
            )),
            Lang::Rus => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Russian,
            )),
            Lang::Spa => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Spanish,
            )),
            Lang::Swe => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Swedish,
            )),
            Lang::Tam => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Tamil,
            )),
            Lang::Tur => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::Turkish,
            )),
            _ => Stemmer(tantivy::tokenizer::Stemmer::new(
                tantivy::tokenizer::Language::English,
            )),
        }
    }
}
