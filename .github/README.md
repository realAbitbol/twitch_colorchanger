# CI/CD Configuration

This repository includes automated Docker image builds using GitHub Actions.

## Features

- **Multi-platform builds**: Automatically builds Docker images for both `linux/amd64` (x86_64) and `linux/arm64` architectures
- **Smart tagging**: Images are tagged based on Git refs:
  - `latest` tag for pushes to main branch
  - Version tags (e.g., `v1.2.3`, `1.2`, `1`) for releases
  - Branch names for feature branches
- **Efficient builds**: Uses GitHub Actions cache to speed up subsequent builds
- **Security**: Only pushes images for main branch and tags, not pull requests

## Setup Requirements

To enable automatic Docker image publishing, configure the following repository secrets:

1. `DOCKER_USERNAME` - Your Docker Hub username
2. `DOCKER_PASSWORD` - Your Docker Hub password or access token

## Workflow Triggers

The workflow runs on:
- Push to `main` branch → builds and pushes `latest` tag
- Push of version tags (e.g., `v1.0.0`) → builds and pushes versioned tags
- Pull requests → builds only (does not push to registry)

## Generated Images

Images are published to: `damastah/twitch-colorchanger`

Available tags:
- `latest` - Latest stable version from main branch
- `v1.2.3` - Specific version tags
- `1.2` - Major.minor version tags
- `1` - Major version tags