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

use super::Error;
use super::Result as ModResult;
use lalrpop_util::lalrpop_mod;

use super::lexer;

lalrpop_mod!(pub parser, "/parser.rs");

pub static PARSER: std::sync::LazyLock<parser::BlocksParser> =
    std::sync::LazyLock::new(parser::BlocksParser::new);

#[derive(Debug, PartialEq)]
pub struct RawOptic {
    pub rules: Vec<RawRule>,
    pub host_preferences: Vec<RawHostPreference>,
    pub discard_non_matching: bool,
}

impl From<Vec<RawOpticBlock>> for RawOptic {
    fn from(blocks: Vec<RawOpticBlock>) -> Self {
        let mut rules = Vec::new();
        let mut host_preferences = Vec::new();
        let mut discard_non_matching = false;

        for block in blocks {
            match block {
                RawOpticBlock::Rule(rule) => rules.push(rule),
                RawOpticBlock::HostPreference(pref) => host_preferences.push(pref),
                RawOpticBlock::DiscardNonMatching => discard_non_matching = true,
            }
        }

        RawOptic {
            rules,
            host_preferences,
            discard_non_matching,
        }
    }
}

#[derive(Debug)]
pub enum RawOpticBlock {
    Rule(RawRule),
    HostPreference(RawHostPreference),
    DiscardNonMatching,
}

#[derive(Debug, PartialEq)]
pub struct RawRule {
    pub matches: Vec<RawMatchBlock>,
    pub action: Option<RawAction>,
}

#[derive(Debug, PartialEq)]
pub enum RawHostPreference {
    Like(String),
    Dislike(String),
}

#[derive(Debug, PartialEq, Clone)]
pub struct RawMatchBlock(pub Vec<RawMatchPart>);

#[derive(Debug, PartialEq, Clone)]
pub enum RawMatchPart {
    Site(String),
    Url(String),
    Domain(String),
    Title(String),
    Description(String),
    Content(String),
    MicroformatTag(String),
    Schema(String),
}

#[derive(Debug, PartialEq, Clone)]
pub enum RawAction {
    Boost(u64),
    Downrank(u64),
    Discard,
}

pub fn parse(optic: &str) -> ModResult<RawOptic> {
    match PARSER.parse(lexer::lex(optic)) {
        Ok(blocks) => Ok(RawOptic::from(blocks)),
        Err(error) => match error {
            lalrpop_util::ParseError::InvalidToken { location: _ } => unreachable!(
                "this is a lexing error, which should be caught earlier since we use logos"
            ),
            lalrpop_util::ParseError::UnrecognizedEof {
                location: _,
                expected,
            } => Err(Error::UnexpectedEof { expected }),
            lalrpop_util::ParseError::UnrecognizedToken {
                token: (start, tok, end),
                expected,
            } => Err(Error::UnexpectedToken {
                token: (start, tok.to_string(), end),
                expected,
            }),
            lalrpop_util::ParseError::ExtraToken {
                token: (start, tok, end),
            } => Err(Error::UnrecognizedToken {
                token: (start, tok.to_string(), end),
            }),
            lalrpop_util::ParseError::User { error } => Err(error),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simple() {
        let optic = parse(
            r#"
            // this is a normal comment
            /*
                this is a block comment
             */
            Rule {
                Matches {
                    Url("/this/is/a/*/pattern")
                }
            };
            Rule {
                Matches {
                    Url("/this/is/a/pattern"),
                    Site("example.com")
                }
            }
        "#,
        )
        .unwrap();

        assert_eq!(
            optic,
            RawOptic {
                rules: vec![
                    RawRule {
                        matches: vec![RawMatchBlock(vec![RawMatchPart::Url(
                            "/this/is/a/*/pattern".to_string()
                        )])],
                        action: None,
                    },
                    RawRule {
                        matches: vec![RawMatchBlock(vec![
                            RawMatchPart::Url("/this/is/a/pattern".to_string()),
                            RawMatchPart::Site("example.com".to_string()),
                        ])],
                        action: None,
                    },
                ],
                host_preferences: vec![],
                discard_non_matching: false,
            }
        );
    }

    #[test]
    fn actions() {
        let optic = parse(
            r#"
            Rule {
                Matches {
                    Url("/this/is/a/*/pattern")
                },
                Action(Boost(2))
            };
            Rule {
                Matches {
                    Site("example.com"),
                },
                Action(Downrank(4))
            };
        "#,
        )
        .unwrap();

        assert_eq!(
            optic,
            RawOptic {
                rules: vec![
                    RawRule {
                        matches: vec![RawMatchBlock(vec![RawMatchPart::Url(
                            "/this/is/a/*/pattern".to_string()
                        )])],
                        action: Some(RawAction::Boost(2)),
                    },
                    RawRule {
                        matches: vec![RawMatchBlock(vec![RawMatchPart::Site(
                            "example.com".to_string()
                        )])],
                        action: Some(RawAction::Downrank(4)),
                    },
                ],
                host_preferences: vec![],
                discard_non_matching: false,
            }
        );
    }

    #[test]
    fn discard_non_matching() {
        let optic = parse(
            r#"
            DiscardNonMatching;
            Rule {
                Matches {
                    Url("/this/is/a/*/pattern")
                },
                Action(Boost(2))
            };
            Rule {
                Matches {
                    Site("example.com"),
                },
                Action(Downrank(4))
            };
        "#,
        )
        .unwrap();

        assert_eq!(
            optic,
            RawOptic {
                rules: vec![
                    RawRule {
                        matches: vec![RawMatchBlock(vec![RawMatchPart::Url(
                            "/this/is/a/*/pattern".to_string()
                        )])],
                        action: Some(RawAction::Boost(2)),
                    },
                    RawRule {
                        matches: vec![RawMatchBlock(vec![RawMatchPart::Site(
                            "example.com".to_string()
                        )])],
                        action: Some(RawAction::Downrank(4)),
                    },
                ],
                host_preferences: vec![],
                discard_non_matching: true,
            }
        );
    }

    #[test]
    fn quickstart_parse() {
        assert!(parse(include_str!("../testcases/samples/quickstart.optic")).is_ok());
    }

    #[test]
    fn hacker_news_parse() {
        assert!(parse(include_str!("../testcases/samples/hacker_news.optic")).is_ok());
    }

    #[test]
    fn copycats_parse() {
        assert!(parse(include_str!("../testcases/samples/copycats_removal.optic")).is_ok());
    }

    #[test]
    fn optics_10kshort_parse() {
        assert!(parse(include_str!("../testcases/samples/10k_short.optic")).is_ok());
    }

    #[test]
    fn blogroll_parse() {
        assert!(parse(include_str!("../testcases/samples/indieweb_blogroll.optic")).is_ok());
    }

    #[test]
    fn devdocs_parse() {
        assert!(parse(include_str!("../testcases/samples/devdocs.optic")).is_ok());
    }

    #[test]
    fn academic_parse() {
        assert!(parse(include_str!("../testcases/samples/academic.optic")).is_ok());
    }

    #[test]
    fn tilde() {
        assert!(parse(include_str!("../testcases/samples/tilde.optic")).is_ok());
    }

    #[test]
    fn crlf_linebreaks() {
        assert!(parse(include_str!("../testcases/crlf.optic")).is_ok());
    }
}
