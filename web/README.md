# NEOS Web UI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Originated from Open Source, give back to Open Source.

This is the web UI for [`NEOS`](https://github.com/NEOS-AI/neos).

## Quick Start

### Prerequisites

- [`NEOS`](https://github.com/NEOS-AI/neos)
- Node.js (v22.14.0+)
- pnpm (v10.6.2+) as package manager

### Configuration

Create a `.env` file in the project root and configure the following environment variables:

- `NEXT_PUBLIC_API_URL`: The URL of the deer-flow API.

It's always a good idea to start with the given example file, and edit the `.env` file with your own values:

```bash
cp .env.example .env
```

## How to Install

NEOS Web UI uses `pnpm` as its package manager.
To install the dependencies, run:

```bash
cd web
pnpm install
```

## How to Run in Development Mode

> [!NOTE]
> Ensure the Python API service is running before starting the web UI.

Start the web UI development server:

```bash
cd web
pnpm dev
```

By default, the web UI will be available at `http://localhost:3000`.

You can set the `NEXT_PUBLIC_API_URL` environment variable if you're using a different host or location.

```ini
# .env
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

## Docker

You can also run this project with Docker.

First, you need read the [configuration](#configuration) below. Make sure `.env` file is ready.

Second, to build a Docker image of your own web server:

```bash
docker build --build-arg NEXT_PUBLIC_API_URL=YOUR_DEER-FLOW_API -t deer-flow-web .
```

Final, start up a docker container running the web server:

```bash
# Replace deer-flow-web-app with your preferred container name
docker run -d -t -p 3000:3000 --env-file .env --name deer-flow-web-app deer-flow-web

# stop the server
docker stop deer-flow-web-app
```

### Docker Compose

You can also setup this project with the docker compose:

```bash
# building docker image
docker compose build

# start the server
docker compose up
```
