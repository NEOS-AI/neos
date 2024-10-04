// Stract is an open source web search engine.
// Copyright (C) 2024 Stract ApS
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

use std::ops::Deref;

use crate::LendingIterator;

pub struct Cloned<I> {
    iter: I,
}

impl<I> Cloned<I> {
    pub fn new(iter: I) -> Self {
        Self { iter }
    }
}

impl<I> From<I> for Cloned<I> {
    fn from(iter: I) -> Self {
        Self::new(iter)
    }
}

impl<I, T> Iterator for Cloned<I>
where
    I: LendingIterator,
    for<'a> I::Item<'a>: Deref<Target = T>,
    T: Clone,
{
    type Item = T;

    fn next(&mut self) -> Option<Self::Item> {
        self.iter.next().map(|item| item.deref().clone())
    }
}
