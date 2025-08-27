# CI/CD Setup Guide

## Required Secrets

To enable automatic Docker image builds and pushes, configure these secrets in your GitHub repository settings:

### Docker Hub Secrets

- `DOCKER_USERNAME`: Your Docker Hub username
- `DOCKER_PASSWORD`: Your Docker Hub access token (not password!)

### How to set up Docker Hub access token

1. Go to Docker Hub → Account Settings → Security
2. Create a new access token with "Read, Write, Delete" permissions
3. Copy the token and add it as `DOCKER_PASSWORD` secret in GitHub

### GitHub Container Registry

- `GITHUB_TOKEN`: Automatically provided by GitHub Actions (no setup needed)

## Workflow Features

### ✅ Multi-Architecture Builds

- **linux/amd64** (Intel/AMD x86_64)
- **linux/arm64** (ARM64, Apple Silicon, Raspberry Pi)
- **linux/arm/v7** (32-bit ARM, Raspberry Pi 2/3/4)
- **linux/arm/v6** (ARMv6, Raspberry Pi Zero/1)
- **linux/riscv64** (RISC-V 64-bit)
- **linux/mips64le** (MIPS 64-bit little-endian)

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

Docker will automatically pull the correct architecture for your platform. Supported architectures:

- **x86_64/amd64**: Standard Intel/AMD processors
- **ARM64**: Apple Silicon Macs, modern ARM servers
- **ARMv7**: Raspberry Pi 2/3/4, modern 32-bit ARM devices
- **ARMv6**: Raspberry Pi Zero/1, older ARM devices  
- **RISC-V 64-bit**: SiFive boards, emerging RISC-V systems
- **MIPS64LE**: MIPS-based routers and embedded systems
