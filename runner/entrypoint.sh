#!/bin/bash
set -e

if [ -z "$GITHUB_OWNER" ] || [ -z "$GITHUB_REPO" ] || [ -z "$RUNNER_TOKEN" ]; then
    echo "Error: GITHUB_OWNER, GITHUB_REPO, and RUNNER_TOKEN must be set."
    echo ""
    echo "To get RUNNER_TOKEN:"
    echo "  1. Go to https://github.com/<OWNER>/<REPO>/settings/actions/runners"
    echo "  2. Click 'New self-hosted runner'"
    echo "  3. Copy the token from the configuration command"
    echo ""
    echo "Example docker-compose.yml environment:"
    echo "  GITHUB_OWNER=menglingjie"
    echo "  GITHUB_REPO=aetftrace"
    echo "  RUNNER_TOKEN=AXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    exit 1
fi

./config.sh \
    --url "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}" \
    --token "${RUNNER_TOKEN}" \
    --name "${RUNNER_NAME:-self-hosted-runner}" \
    --labels "self-hosted,linux,x64,domestic" \
    --work "_work" \
    --replace

./run.sh
