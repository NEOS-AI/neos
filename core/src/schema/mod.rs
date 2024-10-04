// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

pub mod numerical_field;
pub mod text_field;

use tantivy::schema::{BytesOptions, DateOptions, NumericOptions, TextOptions};

pub use numerical_field::{DataType, NumericalFieldEnum};
pub use text_field::TextFieldEnum;

use self::{numerical_field::NumericalField, text_field::TextField};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Field {
    Numerical(NumericalFieldEnum),
    Text(TextFieldEnum),
}

impl Field {
    #[inline]
    pub fn get(field_id: usize) -> Option<Field> {
        if field_id < TextFieldEnum::num_variants() {
            return Some(Field::Text(TextFieldEnum::get(field_id).unwrap()));
        }
        let field_id = field_id - TextFieldEnum::num_variants();

        if field_id < NumericalFieldEnum::num_variants() {
            return Some(Field::Numerical(NumericalFieldEnum::get(field_id).unwrap()));
        }
        let _field_id = field_id - NumericalFieldEnum::num_variants();

        None
    }

    #[inline]
    pub fn all() -> impl Iterator<Item = Field> {
        TextFieldEnum::all()
            .map(Field::Text)
            .chain(NumericalFieldEnum::all().map(Field::Numerical))
    }

    pub fn has_pos(&self) -> bool {
        match self {
            Field::Numerical(_) => false,
            Field::Text(text) => text.has_pos(),
        }
    }

    pub fn indexing_option(&self) -> IndexingOption {
        match self {
            Field::Text(f) => f.indexing_option(),
            Field::Numerical(f) => f.indexing_option(),
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Field::Text(f) => f.name(),
            Field::Numerical(f) => f.name(),
        }
    }

    pub fn is_searchable(&self) -> bool {
        match self {
            Field::Text(f) => f.is_searchable(),
            Field::Numerical(_) => false,
        }
    }

    pub fn as_text(&self) -> Option<TextFieldEnum> {
        match self {
            Field::Numerical(_) => None,
            Field::Text(field) => Some(*field),
        }
    }

    pub fn as_numerical(&self) -> Option<NumericalFieldEnum> {
        match self {
            Field::Numerical(field) => Some(*field),
            Field::Text(_) => None,
        }
    }
}

pub fn create_schema() -> tantivy::schema::Schema {
    let mut builder = tantivy::schema::Schema::builder();

    for field in Field::all() {
        match field.indexing_option() {
            IndexingOption::Text(options) => builder.add_text_field(field.name(), options),
            IndexingOption::Integer(options) => {
                let fast = field.as_numerical().expect("Expected fast field");
                match fast.data_type() {
                    DataType::U64 => builder.add_u64_field(field.name(), options),
                    DataType::F64 => builder.add_f64_field(field.name(), options),
                    DataType::Bool => builder.add_bool_field(field.name(), options),
                    DataType::Bytes => {
                        panic!("bytes field should have a `Bytes` variant as indexing option")
                    }
                }
            }
            IndexingOption::DateTime(options) => builder.add_date_field(field.name(), options),
            IndexingOption::Bytes(options) => builder.add_bytes_field(field.name(), options),
        };
    }

    builder.build()
}

pub enum IndexingOption {
    Text(TextOptions),
    Integer(NumericOptions),
    DateTime(DateOptions),
    Bytes(BytesOptions),
}
