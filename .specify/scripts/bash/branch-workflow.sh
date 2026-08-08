#!/usr/bin/env bash
# branch-workflow.sh — Create branches, commit, push, and open PRs
# following the We Are Home branch conventions.
#
# Usage:
#   branch-workflow.sh --determine-target <feature|fix|hotfix>
#   branch-workflow.sh --create <type> <description>
#   branch-workflow.sh --push-pr <branch> <target> <title> [body]
#   branch-workflow.sh --auto-from-spec [type]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_get_latest_release() {
    # Find the latest release/X.Y.Z branch on remote
    git branch -r 2>/dev/null \
        | { grep -oP 'origin/release/\d+\.\d+\.\d+' || true; } \
        | sort -V \
        | tail -1 \
        | sed 's|origin/||'
}

_require_gh() {
    if ! command -v gh &>/dev/null; then
        echo "ERROR: gh CLI not found. Install it:"
        echo "  curl -sL https://github.com/cli/cli/releases/download/v2.67.0/gh_2.67.0_linux_amd64.tar.gz | tar xz -C ~/.local/bin"
        exit 1
    fi

    if ! gh auth status &>/dev/null; then
        echo "ERROR: gh CLI not authenticated. Run: gh auth login"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Command: --determine-target
# ---------------------------------------------------------------------------

cmd_determine_target() {
    local type="$1"

    case "$type" in
        feature|fix)
            local release
            release="$(_get_latest_release)"
            if [ -z "$release" ]; then
                echo "ERROR: No release/X.Y.Z branch found on remote."
                echo "Create one first:"
                echo "  git checkout -b release/0.1.0 main"
                echo "  git push -u origin release/0.1.0"
                exit 1
            fi
            echo "TARGET=$release"
            echo "RELEASE=${release#release/}"
            ;;
        hotfix)
            echo "TARGET=main"
            echo "RELEASE=main"
            ;;
        *)
            echo "ERROR: Unknown branch type '$type'. Use: feature, fix, or hotfix"
            exit 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Command: --create
# ---------------------------------------------------------------------------

cmd_create() {
    local type="$1"
    local description="$2"
    local branch="${type}/${description}"

    # Validate description is kebab-case
    if ! echo "$description" | grep -qE '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'; then
        echo "ERROR: Description must be lowercase kebab-case (e.g., 'add-mqtt-support')"
        exit 1
    fi

    # Check for local branch conflict
    if git show-ref --verify --quiet "refs/heads/$branch"; then
        echo "ERROR: Local branch '$branch' already exists."
        echo "  git checkout $branch"
        exit 1
    fi

    # Check for remote branch conflict
    if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
        echo "WARNING: Remote branch 'origin/$branch' already exists."
        echo "Continuing with local checkout..."
    fi

    # Fetch latest from remote
    git fetch origin --quiet 2>/dev/null || true

    # Determine base branch
    local base
    if [ "$type" = "hotfix" ]; then
        base="main"
    else
        base="$(_get_latest_release)"
        if [ -z "$base" ]; then
            echo "ERROR: No release branch found. Create release/0.1.0 first."
            exit 1
        fi
    fi

    # Create branch from the correct base
    git checkout -b "$branch" "origin/$base" 2>/dev/null || {
        echo "Falling back to local base..."
        git checkout -b "$branch" "$base"
    }

    echo "BRANCH=$branch"
    echo "BASE=$base"
}

# ---------------------------------------------------------------------------
# Command: --push-pr
# ---------------------------------------------------------------------------

cmd_push_pr() {
    _require_gh

    local branch="$1"
    local target="$2"
    local title="$3"
    local body="${4:-}"

    # Push branch
    echo "Pushing $branch to origin..."
    git push -u origin "$branch"

    # Build PR body if not provided
    if [ -z "$body" ]; then
        local pr_type
        case "$branch" in
            feature/*) pr_type="Feature (target: $target)" ;;
            fix/*)     pr_type="Fix (target: $target)" ;;
            hotfix/*)  pr_type="Hotfix (target: $target)" ;;
            *)         pr_type="Change (target: $target)" ;;
        esac

        body=$(cat <<EOF
## Description

$title

## Type

- [x] $pr_type

## Checklist

- [ ] Code follows project constitution principles
- [ ] Hassfest validation passes
- [ ] HACS validation passes
- [ ] Tests added/updated (if applicable)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)
    fi

    # Create PR
    echo "Creating PR: $branch → $target"
    local pr_url
    pr_url=$(gh pr create \
        --base "$target" \
        --head "$branch" \
        --title "$title" \
        --body "$body" \
        2>&1)

    if echo "$pr_url" | grep -q "https://"; then
        echo "PR_URL=$pr_url"
    else
        echo "ERROR: Failed to create PR: $pr_url"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Command: --auto-from-spec
# ---------------------------------------------------------------------------

cmd_auto_from_spec() {
    local type="${1:-feature}"

    # Validate type
    case "$type" in
        feature|fix|hotfix) ;;
        *)
            echo "ERROR: Unknown branch type '$type'. Use: feature, fix, or hotfix"
            exit 1
            ;;
    esac

    # Read feature.json to find active spec
    local feature_json="$REPO_ROOT/.specify/feature.json"
    if [ ! -f "$feature_json" ]; then
        echo "ERROR: .specify/feature.json not found. Run /speckit-specify first."
        exit 1
    fi

    local feature_dir
    feature_dir=$(python3 -c "
import json, sys
with open('$feature_json') as f:
    data = json.load(f)
print(data.get('feature_directory', ''))
" 2>/dev/null)

    if [ -z "$feature_dir" ]; then
        echo "ERROR: No feature_directory in .specify/feature.json"
        exit 1
    fi

    local spec_file="$REPO_ROOT/$feature_dir/spec.md"
    if [ ! -f "$spec_file" ]; then
        echo "ERROR: spec.md not found at $spec_file"
        exit 1
    fi

    # Extract feature name from spec title (line starting with "# Feature Specification:")
    local feature_name
    feature_name=$(grep -m1 '^# Feature Specification:' "$spec_file" \
        | sed 's/^# Feature Specification: //')

    if [ -z "$feature_name" ]; then
        echo "ERROR: Could not extract feature name from $spec_file title"
        exit 1
    fi

    # Generate kebab-case slug and ascii commit message from feature name
    local converted slug feature_ascii commit_msg
    converted=$(python3 -c "
import unicodedata, re, sys, json

name = sys.stdin.read().strip()

# ASCII-safe version for slug and commit messages
ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')

# Generate slug: lowercase, kebab-case, max 5 words
slug = ascii_name.lower().strip()
slug = re.sub(r'[^a-z0-9\\s-]', '', slug)
slug = re.sub(r'\\s+', '-', slug)
slug = re.sub(r'--+', '-', slug)
slug = slug.strip('-')
words = slug.split('-')[:5]
slug = '-'.join(words)

print(json.dumps({'slug': slug, 'ascii_name': ascii_name.lower().strip()}))
" <<< "$feature_name" 2>/dev/null)

    slug=$(echo "$converted" | python3 -c "import sys,json; print(json.load(sys.stdin)['slug'])")
    feature_ascii=$(echo "$converted" | python3 -c "import sys,json; print(json.load(sys.stdin)['ascii_name'])")

    # Generate commit message
    case "$type" in
        feature)
            commit_msg="feat: add $feature_ascii"
            ;;
        fix)
            commit_msg="fix: $feature_ascii"
            ;;
        hotfix)
            commit_msg="hotfix: $feature_ascii"
            ;;
    esac

    # Read user stories summary for richer context
    local stories_count
    stories_count=$(grep -c '^### User Story' "$spec_file" 2>/dev/null || echo "0")

    echo "TYPE=$type"
    echo "DESCRIPTION=$slug"
    echo "COMMIT_MSG=$commit_msg"
    echo "FEATURE_NAME=$feature_name"
    echo "FEATURE_DIR=$feature_dir"
    echo "STORIES_COUNT=$stories_count"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    if [ $# -lt 1 ]; then
        echo "Usage: branch-workflow.sh --determine-target <type>"
        echo "       branch-workflow.sh --create <type> <description>"
        echo "       branch-workflow.sh --push-pr <branch> <target> <title> [body]"
        exit 1
    fi

    case "$1" in
        --determine-target)
            shift
            cmd_determine_target "$@"
            ;;
        --create)
            shift
            cmd_create "$@"
            ;;
        --push-pr)
            shift
            cmd_push_pr "$@"
            ;;
        --auto-from-spec)
            shift
            cmd_auto_from_spec "$@"
            ;;
        *)
            echo "ERROR: Unknown command '$1'"
            echo "Usage: branch-workflow.sh --determine-target <type>"
            echo "       branch-workflow.sh --create <type> <description>"
            echo "       branch-workflow.sh --push-pr <branch> <target> <title> [body]"
            echo "       branch-workflow.sh --auto-from-spec [type]"
            exit 1
            ;;
    esac
}

main "$@"
