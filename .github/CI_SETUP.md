# CI/CD Setup Guide

## Required Secrets

To enable automatic Docker image builds and pushes, configure these secrets in your GitHub repository settings:

### Docker Hub Secrets
- `DOCKER_USERNAME`: Your Docker Hub username
- `DOCKER_PASSWORD`: Your Docker Hub access token (not password!)

### How to set up Docker Hub access token:
1. Go to Docker Hub → Account Settings → Security
2. Create a new access token with "Read, Write, Delete" permissions
3. Copy the token and add it as `DOCKER_PASSWORD` secret in GitHub

### GitHub Container Registry
- `GITHUB_TOKEN`: Automatically provided by GitHub Actions (no setup needed)

## Workflow Features

### ✅ Multi-Architecture Builds
- **linux/amd64** (Intel/AMD x86_64)
- **linux/arm64** (ARM64, Apple Silicon, Raspberry Pi)

### ✅ Dual Registry Push
- **Docker Hub**: `damastah/twitch-colorchanger`
- **GitHub Container Registry**: `ghcr.io/realabitbol/twitch-colorchanger`

### ✅ Security Features
- Vulnerability scanning with Trivy
- SBOM (Software Bill of Materials) generation
- Image provenance tracking
- Non-root container execution

### ✅ Automatic Tagging
- `latest` for main branch
- `v1.0.0` for semantic version tags
- `v1.0` and `v1` for major/minor versions
- Branch names for feature branches

## Usage

### Pull from Docker Hub
```bash
docker pull damastah/twitch-colorchanger:latest
```

### Pull from GitHub Container Registry
```bash
docker pull ghcr.io/realabitbol/twitch-colorchanger:latest
```

### Multi-architecture support
Docker will automatically pull the correct architecture for your platform.
