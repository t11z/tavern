#!/usr/bin/env bash
# Configure GitHub repository settings for Tavern.
# Requires: GitHub CLI (gh) authenticated with admin access to the repo.
#
# Usage: bash scripts/setup-repo.sh
#
# Run once after creating the repository. Safe to re-run — settings are
# idempotent, branch protection is overwritten on each run.

set -euo pipefail

REPO="t11z/tavern"

echo "Configuring repository settings for $REPO..."
echo ""

# ============================================
# 1. Repository metadata
# ============================================

echo "→ Repository metadata"

gh repo edit "$REPO" \
  --description "An AI Game Master for tabletop RPG campaigns — open source, self-hosted, and cheaper than a coffee." \
  --homepage "https://t11z.github.io/tavern" \
  --enable-issues \
  --enable-wiki=false \
  --enable-projects \
  --enable-discussions \
  --default-branch main

# Topics for discoverability
gh api -X PUT "repos/$REPO/topics" \
  -f '{"names":["dnd","tabletop-rpg","ai","llm","claude","game-master","srd","5e","open-source","self-hosted","discord-bot","python","fastapi","react"]}' \
  --silent 2>/dev/null || \
gh api -X PUT "repos/$REPO/topics" \
  --input - <<EOF
{"names":["dnd","tabletop-rpg","ai","llm","claude","game-master","srd","5e","open-source","self-hosted","discord-bot","python","fastapi","react"]}
EOF

echo "  ✓ Description, homepage, topics set"
echo "  ✓ Wiki disabled (docs live in repo per ADR-0000)"
echo "  ✓ Discussions enabled"

# ============================================
# 2. Branch protection — main
# ============================================

echo ""
echo "→ Branch protection: main"

gh api -X PUT "repos/$REPO/branches/main/protection" \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "test"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
EOF

echo "  ✓ PRs required (1 approval)"
echo "  ✓ Status checks required (lint, test)"
echo "  ✓ Stale reviews dismissed on new commits"
echo "  ✓ Linear history enforced (no merge commits)"
echo "  ✓ Conversation resolution required"
echo "  ✓ Force pushes and branch deletion blocked"

# ============================================
# 3. Default merge settings
# ============================================

echo ""
echo "→ Merge settings"

gh repo edit "$REPO" \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --enable-auto-merge \
  --delete-branch-on-merge

echo "  ✓ Squash merge only (clean linear history)"
echo "  ✓ Auto-merge enabled"
echo "  ✓ Branches deleted after merge"

# ============================================
# 4. Discussion categories
# ============================================

echo ""
echo "→ Discussion categories"

# GitHub Discussions categories must be created via the web UI or GraphQL.
# The gh CLI does not support creating categories directly.
# Print instructions instead.

echo "  ⚠ Create these Discussion categories manually in Settings → Discussions:"
echo ""
echo "    📢 Announcements      (Announcement format — maintainer only)"
echo "    💡 Ideas & Features    (Open format — community proposals)"
echo "    🏗️ Architecture        (Open format — ADR discussions before formal proposals)"
echo "    🎲 Show & Tell         (Showoff format — campaign stories, world presets, screenshots)"
echo "    ❓ Q&A                 (Question/Answer format — how-to, setup help, rules questions)"
echo "    🐛 Bug Reports         (redirect to Issues — add a note in the category description)"

# ============================================
# 5. Labels
# ============================================

echo ""
echo "→ Labels"

# Remove GitHub defaults that don't match our taxonomy
for label in "duplicate" "invalid" "question" "wontfix"; do
  gh label delete "$label" --yes 2>/dev/null && echo "  removed default: $label" || true
done

# Create project labels (idempotent — updates existing)
create_or_update() {
  local name="$1" color="$2" description="$3"
  if gh label view "$name" &>/dev/null 2>&1; then
    gh label edit "$name" --color "$color" --description "$description"
    echo "  updated: $name"
  else
    gh label create --force "$name" --color "$color" --description "$description"
    echo "  created: $name"
  fi
}

# Component labels
create_or_update "rules-engine"   "1d76db" "Rules Engine — combat, spells, dice, conditions, characters"
create_or_update "narrator"       "7c3aed" "Narrator / DM Interface — Claude integration, prompts, context builder"
create_or_update "web-client"     "0ea5e9" "Web client — React UI"
create_or_update "discord-bot"    "5865f2" "Discord bot client"
create_or_update "srd-data"       "b45309" "SRD game data — spells, monsters, class features, schemas"
create_or_update "world-preset"   "16a34a" "Community world presets"
create_or_update "api"            "06b6d4" "API layer — endpoints, WebSocket events"
create_or_update "infrastructure" "6b7280" "Docker, CI, deployment, database"

# Type labels
create_or_update "bug"            "d73a4a" "Something isn't working correctly"
create_or_update "enhancement"    "a2eeef" "New feature or improvement"
create_or_update "documentation"  "0075ca" "Documentation changes"
create_or_update "adr"            "fbca04" "Architecture Decision Record — new or superseding"
create_or_update "refactor"       "d4c5f9" "Code restructuring without behavior change"
create_or_update "test"           "bfd4f2" "Test additions or improvements"

# Priority labels
create_or_update "critical"       "b60205" "Blocks gameplay or causes data loss"
create_or_update "important"      "e99695" "Significant but not blocking"

# Status labels
create_or_update "good-first-issue" "7057ff" "Good for newcomers — well-scoped, clear requirements"
create_or_update "help-wanted"      "008672" "Maintainer welcomes community contributions"
create_or_update "needs-adr"        "fbca04" "Requires an Architecture Decision Record before implementation"
create_or_update "needs-discussion" "d876e3" "Needs design discussion before implementation"
create_or_update "blocked"          "b60205" "Blocked by another issue or decision"

echo ""
echo "  $(gh label list --limit 100 --json name --jq '. | length') labels configured"

# ============================================
# 6. Security settings
# ============================================

echo ""
echo "→ Security"

gh api -X PUT "repos/$REPO/vulnerability-alerts" --silent 2>/dev/null || true
gh api -X PUT "repos/$REPO/automated-security-fixes" --silent 2>/dev/null || true

echo "  ✓ Dependabot vulnerability alerts enabled"
echo "  ✓ Automated security fixes enabled"

# ============================================
# 7. GitHub Pages
# ============================================

echo ""
echo "→ GitHub Pages"

# Pages are deployed via GitHub Actions (deploy-docs.yml), not from a branch.
# This requires Pages to be enabled with "GitHub Actions" as the source.
# The gh CLI doesn't support configuring Pages source directly.

echo "  ⚠ Enable GitHub Pages manually:"
echo "    Settings → Pages → Source: GitHub Actions"
echo "    The deploy-docs.yml workflow handles deployment automatically."

# ============================================
# Summary
# ============================================

echo ""
echo "============================================"
echo "  Repository setup complete."
echo ""
echo "  Manual steps remaining:"
echo "    1. Create Discussion categories (listed above)"
echo "    2. Enable GitHub Pages (Settings → Pages → Source: GitHub Actions)"
echo "    3. Add secrets: ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN (optional)"
echo "    4. Optionally add DISCORD_BOT_TOKEN for Discord integration"
echo "============================================"