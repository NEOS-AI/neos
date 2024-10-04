// Neos is an open source web search engine.
// Copyright (C) 2024 Yeonwoo Sung
//
// This code is originated from Stract, which is licensed under the GNU Affero General Public License.

use futures::{pin_mut, Stream};

use crate::Result;
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};

pub trait StreamingResponse: Unpin + Sized {
    type Item: Unpin;

    fn next_batch(&mut self) -> impl Future<Output = Result<Vec<Self::Item>>>;

    fn stream(self) -> impl Stream<Item = Self::Item> {
        StreamingResponseStream::new(self)
    }
}

pub struct StreamingResponseStream<T>
where
    T: StreamingResponse,
{
    inner: T,
    batch: Option<Vec<T::Item>>,
}

impl<T> StreamingResponseStream<T>
where
    T: StreamingResponse,
{
    fn new(inner: T) -> Self {
        Self { inner, batch: None }
    }
}

impl<T> Stream for StreamingResponseStream<T>
where
    T: StreamingResponse,
{
    type Item = T::Item;

    fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        let this = self.get_mut();

        if this.batch.is_none() {
            let fut = this.inner.next_batch();
            pin_mut!(fut);

            match fut.poll(cx) {
                Poll::Pending => return Poll::Pending,
                Poll::Ready(batch) => match batch {
                    Ok(batch) => {
                        if batch.is_empty() {
                            return Poll::Ready(None);
                        }
                        this.batch = Some(batch);
                    }
                    Err(_) => return Poll::Ready(None),
                },
            }
        }

        match this.batch.as_mut() {
            Some(batch) => {
                if batch.is_empty() {
                    let fut = this.inner.next_batch();
                    pin_mut!(fut);

                    match fut.poll(cx) {
                        Poll::Pending => return Poll::Pending,
                        Poll::Ready(next_batch) => match next_batch {
                            Ok(next_batch) => {
                                if next_batch.is_empty() {
                                    return Poll::Ready(None);
                                }

                                batch.extend(next_batch);
                            }
                            Err(_) => return Poll::Ready(None),
                        },
                    }
                }

                Poll::Ready(batch.pop())
            }
            None => Poll::Ready(None),
        }
    }
}

#[cfg(test)]
mod tests {
    use futures::StreamExt;

    use super::*;

    struct TestStreamingResponse {
        items: Vec<String>,
        index: usize,
    }

    impl TestStreamingResponse {
        fn new(items: Vec<String>) -> Self {
            Self { items, index: 0 }
        }
    }

    impl StreamingResponse for TestStreamingResponse {
        type Item = String;

        async fn next_batch(&mut self) -> Result<Vec<Self::Item>> {
            if self.index >= self.items.len() {
                return Ok(Vec::new());
            }

            let mut res = Vec::new();

            res.push(self.items[self.index].clone());

            self.index += 1;

            Ok(res)
        }
    }

    #[tokio::test]
    async fn test_streaming_response_stream() {
        let mut stream =
            TestStreamingResponse::new(vec!["a".to_string(), "b".to_string(), "c".to_string()])
                .stream();

        assert_eq!(stream.next().await, Some("a".to_string()));
        assert_eq!(stream.next().await, Some("b".to_string()));
        assert_eq!(stream.next().await, Some("c".to_string()));
        assert_eq!(stream.next().await, None);
    }

    #[tokio::test]
    async fn test_empty_stream() {
        let mut stream = TestStreamingResponse::new(Vec::new()).stream();

        assert_eq!(stream.next().await, None);
    }
}
