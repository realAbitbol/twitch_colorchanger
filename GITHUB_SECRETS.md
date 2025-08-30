# GitHub Actions Secrets Setup

This project uses GitHub Actions for CI/CD and requires the following secrets to be configured for full functionality.

## Required Secrets

### 1. CODECOV_TOKEN

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

### 2. SAFETY_API_KEY

**Purpose:** Run Safety CLI security scanning with full features and updated vulnerability database.

**Setup:**
1. Go to [Safety CLI](https://safetycli.com)
2. Sign up for a free account
3. Navigate to your account settings to find your API key
4. In your GitHub repository, go to Settings > Secrets and variables > Actions
5. Click "New repository secret"
6. Name: `SAFETY_API_KEY`
7. Value: Paste your Safety API key

## Fallback Behavior

If these secrets are not configured:

- **Codecov:** Coverage upload will be skipped (the environment variable will be empty)
- **Safety:** Will attempt to run without authentication, which may have limited functionality but won't fail the build

## Verifying Setup

After adding the secrets:

1. Push a commit to trigger GitHub Actions
2. Check the Actions tab to see if the workflow runs successfully
3. Verify that:
   - Coverage reports appear on Codecov
   - Safety scans complete without authentication prompts

## Security Notes

- Never commit API keys or tokens to your repository
- These secrets are only accessible to GitHub Actions workflows
- Secrets are not exposed in workflow logs
- Only repository administrators can view/edit secrets
