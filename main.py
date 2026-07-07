#!/usr/bin/env python3
"""
GitHub API Key Miner - Production-grade security research tool.

Scans GitHub repositories for exposed API keys and secrets.
Saves findings to a JSON file with full context and metadata.
"""

import os
import sys
import re
import json
import time
import logging
import argparse
import base64
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import yaml
import requests
from github import Github, GithubException, RateLimitExceededException
from tqdm import tqdm

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_CONFIG = {
    "github": {
        "token": None,  # Will be read from env GITHUB_TOKEN if not set
        "search_queries": [
            "api_key",
            "api_secret",
            "secret_key",
            "private_key",
            "access_token",
            "auth_token",
            "password",
            "client_secret",
            "token",
            "key",
            "secret",
        ],
        "max_repos": 100,
        "languages": [],  # e.g., ["python", "javascript"]
        "min_stars": 0,
        "exclude_repos": [],  # list of full repo names to skip
        "include_repos": [],  # if set, only scan these (overrides search)
    },
    "scanning": {
        "max_file_size": 1_000_000,  # 1 MB
        "exclude_extensions": [
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
            ".mp4", ".mp3", ".wav", ".avi", ".mkv",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx",
            ".zip", ".tar", ".gz", ".bz2",
            ".exe", ".dll", ".so", ".dylib", ".bin",
            ".pyc", ".class", ".o", ".obj"
        ],
        "exclude_paths": [
            "test", "example", "sample", "mock", "fixture",
            "node_modules", ".git", "__pycache__", "vendor",
            "dist", "build", "target", "out"
        ],
        "concurrent_workers": 5,
        "request_timeout": 30,
        "max_retries": 3,
        "retry_backoff": 2,  # seconds
    },
    "detection": {
        "min_confidence": 0.3,  # minimum confidence to report
        "mask_length": 4,       # characters to show at start and end
    },
    "output": {
        "json_file": "findings.json",
        "log_file": "github_key_miner.log",
        "log_level": "INFO",
    }
}

# ============================================================================
# KEY PATTERNS
# ============================================================================

class KeyPatterns:
    """Regex patterns for detecting various credentials."""

    PATTERNS = {
        # AWS
        "aws_access_key": r"AKIA[0-9A-Z]{16}",
        "aws_secret_key": r"(?i)aws_secret_access_key\s*=\s*[\"']?([A-Za-z0-9/+=]{40})[\"']?",
        "aws_session_token": r"ASIA[0-9A-Z]{16}",
        # Google
        "google_api_key": r"AIza[0-9A-Za-z\-_]{35}",
        "google_oauth": r"[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com",
        # GitHub
        "github_personal": r"ghp_[0-9a-zA-Z]{36}",
        "github_oauth": r"gho_[0-9a-zA-Z]{36}",
        "github_app": r"ghu_[0-9a-zA-Z]{36}",
        "github_installation": r"ghs_[0-9a-zA-Z]{36}",
        # Slack
        "slack_token": r"xox[baprs]-[0-9a-zA-Z]{10,48}",
        "slack_webhook": r"https://hooks\.slack\.com/services/[A-Z0-9]+/[A-Z0-9]+/[A-Za-z0-9]+",
        # Stripe
        "stripe_live": r"sk_live_[0-9a-zA-Z]{24}",
        "stripe_test": r"sk_test_[0-9a-zA-Z]{24}",
        "stripe_restricted": r"rk_live_[0-9a-zA-Z]{24}",
        # GitLab
        "gitlab_personal": r"glpat-[0-9a-zA-Z\-_]{20}",
        "gitlab_runner": r"GR1348941[0-9a-zA-Z\-_]{20}",
        # JWT
        "jwt": r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+",
        # Generic
        "private_key": r"-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----",
        "api_key_generic": r"(?i)(?:api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-]{16,64})[\"']?",
        "password": r"(?i)(?:password|passwd|pwd)\s*[:=]\s*[\"']?([^\"'\s]{8,64})[\"']?",
        "token_generic": r"(?i)(?:token|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-\.]{20,64})[\"']?",
    }

    @classmethod
    def get_compiled(cls):
        """Return compiled regex objects for all patterns."""
        compiled = {}
        for name, pattern in cls.PATTERNS.items():
            try:
                compiled[name] = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                logging.getLogger(__name__).warning(f"Invalid regex for {name}: {e}")
        return compiled

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(log_file: str, log_level: str = "INFO"):
    """Configure logging to file and console."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(numeric_level)

    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(numeric_level)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(numeric_level)
    ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)

    return logger

# ============================================================================
# KEY DETECTOR
# ============================================================================

class KeyDetector:
    """Detect secrets in file content using regex patterns with confidence scoring."""

    def __init__(self, config: Dict):
        self.config = config
        self.patterns = KeyPatterns.get_compiled()
        self.min_confidence = config.get("detection", {}).get("min_confidence", 0.3)
        self.mask_len = config.get("detection", {}).get("mask_length", 4)
        self.exclude_extensions = set(config.get("scanning", {}).get("exclude_extensions", []))
        self.exclude_paths = config.get("scanning", {}).get("exclude_paths", [])
        self.max_file_size = config.get("scanning", {}).get("max_file_size", 1_000_000)
        self.logger = logging.getLogger(__name__)

    def should_scan_file(self, file_path: str, size: int = 0) -> bool:
        """Determine if a file should be scanned based on extension, path, and size."""
        # Size check
        if size > self.max_file_size:
            return False

        # Extension check
        ext = Path(file_path).suffix.lower()
        if ext in self.exclude_extensions:
            return False

        # Path pattern check (case-insensitive)
        lower_path = file_path.lower()
        for pattern in self.exclude_paths:
            if pattern in lower_path:
                return False

        return True

    def scan_content(self, content: str, file_path: str) -> List[Dict]:
        """Scan file content for secrets."""
        findings = []
        lines = content.splitlines()

        for pattern_name, pattern in self.patterns.items():
            for match in pattern.finditer(content):
                matched_text = match.group(0)
                # Calculate line number and context
                start_pos = match.start()
                line_no = content[:start_pos].count('\n') + 1
                # Get context (2 lines before and after)
                start_line = max(0, line_no - 3)
                end_line = min(len(lines), line_no + 2)
                context_lines = lines[start_line:end_line]
                context = '\n'.join(context_lines)

                confidence = self._calculate_confidence(matched_text, pattern_name, context)

                if confidence >= self.min_confidence:
                    finding = {
                        "pattern": pattern_name,
                        "matched_text": self._mask_secret(matched_text),
                        "line_number": line_no,
                        "file_path": file_path,
                        "context": context,
                        "confidence": round(confidence, 3),
                        # Keep raw match for verification (optional)
                        "raw_match": matched_text,
                    }
                    findings.append(finding)

        return findings

    def _calculate_confidence(self, secret: str, pattern_name: str, context: str) -> float:
        """Calculate confidence score (0-1) for a detection."""
        confidence = 0.7  # Base

        # Penalize obvious false positives
        fp_indicators = [
            r"example", r"test", r"demo", r"sample",
            r"placeholder", r"your[_-]?", r"changeme",
            r"<[^>]+>",  # HTML placeholders
            r"\{[^}]+\}",  # Template variables
            r"ENV\[[^\]]+\]",  # Environment variable references
        ]
        for fp in fp_indicators:
            if re.search(fp, context, re.IGNORECASE):
                confidence -= 0.15
                break

        # Penalize short secrets (less than 16 chars)
        if len(secret) < 16:
            confidence -= 0.1

        # Penalize if in a comment
        if re.search(r'^\s*//|^\s*#|/\*.*\*/', context, re.MULTILINE):
            confidence -= 0.1

        # Boost if secret appears in assignment or usage
        if re.search(rf'=.*{re.escape(secret)}.*;', context):
            confidence += 0.1

        # Specific pattern boosts
        if "aws" in pattern_name and len(secret) >= 20:
            confidence += 0.1
        if "private_key" in pattern_name:
            confidence += 0.15

        return max(0.0, min(1.0, confidence))

    def _mask_secret(self, secret: str) -> str:
        """Mask the secret, showing only first/last few chars."""
        if len(secret) <= self.mask_len * 2:
            return '*' * len(secret)
        return secret[:self.mask_len] + '*' * (len(secret) - self.mask_len * 2) + secret[-self.mask_len:]

# ============================================================================
# GITHUB MINER
# ============================================================================

class GitHubMiner:
    """Mine GitHub repositories for exposed secrets."""

    def __init__(self, config: Dict):
        self.config = config
        self.token = config["github"].get("token") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token is required. Set GITHUB_TOKEN env or in config.")
        self.github = Github(self.token, timeout=config["scanning"].get("request_timeout", 30))
        self.search_queries = config["github"].get("search_queries", [])
        self.max_repos = config["github"].get("max_repos", 100)
        self.languages = config["github"].get("languages", [])
        self.min_stars = config["github"].get("min_stars", 0)
        self.exclude_repos = set(config["github"].get("exclude_repos", []))
        self.include_repos = set(config["github"].get("include_repos", []))
        self.concurrent_workers = config["scanning"].get("concurrent_workers", 5)
        self.max_retries = config["scanning"].get("max_retries", 3)
        self.retry_backoff = config["scanning"].get("retry_backoff", 2)
        self.detector = KeyDetector(config)
        self.logger = logging.getLogger(__name__)

    def search_repositories(self) -> List:
        """Search GitHub for repositories matching queries."""
        repos = []
        if self.include_repos:
            # If specific repos are listed, fetch them directly
            for repo_name in self.include_repos:
                try:
                    repo = self.github.get_repo(repo_name)
                    repos.append(repo)
                except GithubException as e:
                    self.logger.error(f"Failed to get repo {repo_name}: {e}")
            return repos

        for query in self.search_queries:
            search_query = query
            if self.languages:
                lang_query = ' '.join([f"language:{lang}" for lang in self.languages])
                search_query = f"{search_query} {lang_query}"
            if self.min_stars > 0:
                search_query = f"{search_query} stars:>={self.min_stars}"

            self.logger.info(f"Searching GitHub for: {search_query}")
            try:
                result = self.github.search_repositories(search_query)
                count = 0
                for repo in result:
                    if count >= self.max_repos:
                        break
                    if repo.full_name in self.exclude_repos:
                        continue
                    repos.append(repo)
                    count += 1
                self.logger.info(f"Found {count} repositories for query '{query}'")
            except RateLimitExceededException:
                self._handle_rate_limit()
                continue
            except GithubException as e:
                self.logger.error(f"GitHub search error for '{query}': {e}")
                continue

        return repos

    def scan_repository(self, repo) -> List[Dict]:
        """Scan a single repository for secrets."""
        findings = []
        self.logger.info(f"Scanning repository: {repo.full_name}")

        try:
            # Get default branch
            default_branch = repo.default_branch
            # Get contents recursively using the Git tree API for efficiency
            tree = repo.get_git_tree(sha=default_branch, recursive=True)
            total_files = len(tree.tree)
            self.logger.debug(f"Found {total_files} files in {repo.full_name}")

            # Prepare list of file paths to scan
            files_to_scan = []
            for item in tree.tree:
                if item.type == "blob":
                    file_path = item.path
                    if self.detector.should_scan_file(file_path, item.size):
                        files_to_scan.append((file_path, item.sha, item.size))

            self.logger.info(f"Scanning {len(files_to_scan)} files in {repo.full_name} (after filtering)")

            # Use ThreadPoolExecutor for concurrency
            with ThreadPoolExecutor(max_workers=self.concurrent_workers) as executor:
                future_to_file = {
                    executor.submit(self._fetch_and_scan_file, repo, file_path, sha, size): (file_path, sha)
                    for file_path, sha, size in files_to_scan
                }
                with tqdm(total=len(files_to_scan), desc=f"Scanning {repo.full_name}", unit="file") as pbar:
                    for future in as_completed(future_to_file):
                        file_path, sha = future_to_file[future]
                        try:
                            file_findings = future.result(timeout=30)
                            if file_findings:
                                findings.extend(file_findings)
                        except Exception as e:
                            self.logger.error(f"Error scanning file {file_path} in {repo.full_name}: {e}")
                        pbar.update(1)

        except GithubException as e:
            self.logger.error(f"GitHub error scanning {repo.full_name}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error scanning {repo.full_name}: {e}")

        return findings

    def _fetch_and_scan_file(self, repo, file_path: str, sha: str, size: int) -> List[Dict]:
        """Fetch a single file's content and scan it."""
        if size > self.detector.max_file_size:
            return []

        content = self._get_file_content(repo, file_path, sha)
        if content is None:
            return []

        return self.detector.scan_content(content, file_path)

    def _get_file_content(self, repo, file_path: str, sha: str) -> Optional[str]:
        """Retrieve file content from GitHub, with retries."""
        for attempt in range(self.max_retries):
            try:
                # Use get_contents with ref to get raw content
                content_obj = repo.get_contents(file_path, ref=repo.default_branch)
                if content_obj and content_obj.content:
                    decoded = base64.b64decode(content_obj.content).decode('utf-8', errors='ignore')
                    return decoded
                return None
            except GithubException as e:
                if e.status == 403 and "rate limit" in str(e).lower():
                    self._handle_rate_limit()
                elif e.status in (404, 409):
                    # File might not exist or conflict; skip
                    return None
                else:
                    self.logger.warning(f"Attempt {attempt+1} failed for {file_path}: {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_backoff * (attempt + 1))
            except Exception as e:
                self.logger.warning(f"Attempt {attempt+1} failed for {file_path}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_backoff * (attempt + 1))
        return None

    def _handle_rate_limit(self):
        """Handle rate limit by sleeping until reset."""
        try:
            rate = self.github.get_rate_limit()
            reset_time = rate.core.reset
            sleep_seconds = (reset_time - datetime.now()).total_seconds() + 5
            if sleep_seconds > 0:
                self.logger.warning(f"Rate limit hit. Sleeping for {sleep_seconds:.0f} seconds.")
                time.sleep(sleep_seconds)
        except:
            # If can't get rate limit, sleep default
            time.sleep(60)

    def get_owner_info(self, repo) -> Dict:
        """Get repository owner information."""
        try:
            owner = repo.owner
            return {
                "username": owner.login,
                "email": owner.email if hasattr(owner, 'email') else None,
                "name": owner.name if hasattr(owner, 'name') else None,
                "url": owner.html_url,
                "type": owner.type,
            }
        except:
            return {}

# ============================================================================
# JSON OUTPUT
# ============================================================================

def save_findings_json(findings: List[Dict], output_file: str, metadata: Dict):
    """Save findings to a JSON file with metadata."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "metadata": metadata,
        "findings": findings,
    }
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logging.getLogger(__name__).info(f"Saved {len(findings)} findings to {output_file}")

# ============================================================================
# MAIN
# ============================================================================

def load_config(config_path: Optional[str] = None) -> Dict:
    """Load configuration from file or use defaults."""
    config = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f)
            # Deep merge (simple for now)
            for key, value in user_config.items():
                if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value

    # Override from environment
    if os.environ.get("GITHUB_TOKEN"):
        config["github"]["token"] = os.environ["GITHUB_TOKEN"]

    # Ensure output directory exists
    output_file = config["output"]["json_file"]
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    return config

def parse_args():
    parser = argparse.ArgumentParser(description="GitHub API Key Miner - Security research tool")
    parser.add_argument("-c", "--config", help="Path to configuration YAML file")
    parser.add_argument("-o", "--output", help="Output JSON file (overrides config)")
    parser.add_argument("-q", "--query", action="append", help="Add a search query (can be repeated)")
    parser.add_argument("-l", "--language", action="append", help="Filter by language (can be repeated)")
    parser.add_argument("--max-repos", type=int, help="Maximum repositories to scan")
    parser.add_argument("--include-repo", action="append", help="Specific repo to scan (full name, can be repeated)")
    parser.add_argument("--exclude-repo", action="append", help="Repo to skip (full name, can be repeated)")
    parser.add_argument("--min-stars", type=int, help="Minimum stars filter")
    parser.add_argument("--workers", type=int, help="Concurrent workers")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    return parser.parse_args()

def main():
    args = parse_args()
    config = load_config(args.config)

    # Override with CLI args
    if args.output:
        config["output"]["json_file"] = args.output
    if args.query:
        config["github"]["search_queries"] = args.query
    if args.language:
        config["github"]["languages"] = args.language
    if args.max_repos is not None:
        config["github"]["max_repos"] = args.max_repos
    if args.include_repo:
        config["github"]["include_repos"] = args.include_repo
    if args.exclude_repo:
        config["github"]["exclude_repos"] = args.exclude_repo
    if args.min_stars is not None:
        config["github"]["min_stars"] = args.min_stars
    if args.workers is not None:
        config["scanning"]["concurrent_workers"] = args.workers

    # Setup logging
    log_file = config["output"]["log_file"]
    log_level = config["output"].get("log_level", "INFO")
    logger = setup_logging(log_file, log_level)

    logger.info("=" * 60)
    logger.info("GitHub API Key Miner Started")
    logger.info(f"Config: {config}")

    # Initialize miner
    try:
        miner = GitHubMiner(config)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Search repositories
    repos = miner.search_repositories()
    if not repos:
        logger.warning("No repositories found to scan.")
        sys.exit(0)

    logger.info(f"Found {len(repos)} repositories to scan.")

    # Scan each repository
    all_findings = []
    metadata = {
        "repos_scanned": len(repos),
        "config": config,
    }

    for repo in repos:
        findings = miner.scan_repository(repo)
        if findings:
            # Add repo info to each finding
            owner_info = miner.get_owner_info(repo)
            for f in findings:
                f["repository"] = repo.full_name
                f["owner"] = owner_info
                f["repo_url"] = repo.html_url
                f["default_branch"] = repo.default_branch
            all_findings.extend(findings)

    # Save to JSON
    save_findings_json(all_findings, config["output"]["json_file"], metadata)

    # Summary
    logger.info("=" * 60)
    logger.info(f"Scan completed. Total findings: {len(all_findings)}")
    if all_findings:
        # Group by pattern
        pattern_counts = {}
        for f in all_findings:
            pattern = f["pattern"]
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        logger.info("Findings by pattern:")
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            logger.info(f"  {pattern}: {count}")

    logger.info("Done.")

if __name__ == "__main__":
    main()