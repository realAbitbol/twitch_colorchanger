# CI/CD Setup Guide

## 🆕 Recent Updates (August 2025)

- ✅ Updated to latest GitHub Actions versions
- ✅ Optimized dependencies (removed unused `requests` library)
- ✅ Enhanced security scanning with Trivy
- ✅ Improved Docker build caching
- ✅ Code quality audit completed

## Required Secrets

To enable all CI/CD features, configure these secrets in your GitHub repository settings:

### Docker Hub Secrets

- `DOCKER_USERNAME`: Your Docker Hub username
- `DOCKER_PASSWORD`: Your Docker Hub access token (not password!)

#### How to set up Docker Hub access token

1. Go to Docker Hub → Account Settings → Security
2. Create a new access token with "Read, Write, Delete" permissions
3. Copy the token and add it as `DOCKER_PASSWORD` secret in GitHub

### Test Coverage & Security Secrets

#### CODECOV_TOKEN

**Purpose:** Upload test coverage reports to Codecov for coverage tracking and badges.

**Setup:**

1. Go to [Codecov.io](https://codecov.io)
2. Sign in with your GitHub account
3. Add your repository `realAbitbol/twitch_colorchanger`
4. Copy the repository upload token
5. In your GitHub repository, go to Settings > Secrets and variables > Actions
6. Click "New repository secret"
7. Name: `CODECOV_TOKEN`
8. Value: Paste the token from Codecov

#### SAFETY_API_KEY

**Purpose:** Run Safety CLI security scanning with full features and updated vulnerability database.

**Setup:**

1. Go to [Safety CLI](https://safetycli.com)
2. Sign up for a free account
3. Navigate to your account settings to find your API key
4. In your GitHub repository, go to Settings > Secrets and variables > Actions
5. Click "New repository secret"
6. Name: `SAFETY_API_KEY`
7. Value: Paste your Safety API key

### GitHub Container Registry

- `GITHUB_TOKEN`: Automatically provided by GitHub Actions (no setup needed)

### Fallback Behavior

If optional secrets are not configured:

- **Codecov:** Coverage upload will be skipped gracefully
- **Safety:** Will attempt to run without authentication (limited functionality but won't fail the build)

### Verifying Setup

After adding the secrets:

1. Push a commit to trigger GitHub Actions
2. Check the Actions tab to see if the workflow runs successfully
3. Verify that:
   - Docker images are pushed to registries
   - Coverage reports appear on Codecov
   - Safety scans complete without authentication prompts

### Security Notes

- Never commit API keys or tokens to your repository
- These secrets are only accessible to GitHub Actions workflows
- Secrets are not exposed in workflow logs
- Only repository administrators can view/edit secrets

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

## Multi-Architecture Support

The pipeline automatically builds Docker images for 5 platforms:

- `linux/amd64` - Standard x86_64 (Intel/AMD)
- `linux/arm64` - ARM 64-bit (Apple Silicon, modern ARM servers)
- `linux/arm/v7` - ARM 32-bit (Raspberry Pi 2/3/4)
- `linux/arm/v6` - ARM v6 (Raspberry Pi Zero/1)
- `linux/riscv64` - RISC-V 64-bit
- **MIPS64LE**: MIPS-based routers and embedded systems
