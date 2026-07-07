#!/usr/bin/env python3
"""
GitHub API Key Miner - Production-grade security research tool.

Scans GitHub repositories for exposed API keys and secrets.
Features:
- Incremental JSON output (flush after each repo or every N findings)
- Resume support (--resume)
- Graceful shutdown (Ctrl+C saves progress)
- Rate-limit handling with Retry-After
- Deduplication per repository
- Extensive key patterns (AWS, Google, GitHub, Slack, Stripe, OpenAI, Azure, JWT, generic)
- Configurable via YAML, env, or CLI
- Prioritises scanning common config files (.env, Dockerfile, etc.)
"""

import os
import sys
import re
import json
import time
import logging
import argparse
import base64
import signal
import hashlib
import random
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import yaml
import requests
from github import Github, GithubException, RateLimitExceededException, Auth
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
        # Files that should always be scanned, even if they match exclude_paths/extensions
        "priority_files": [
            ".env", ".env.example", ".env.local", ".env.production", ".env.staging",
            "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
            "settings.py", "config.py", "application.properties", "application.yml",
            "config.json", "config.yaml", "config.yml",
            "credentials.json", "secrets.json", "secrets.yaml",
            ".aws/credentials", ".ssh/id_rsa", "id_rsa",
            "wp-config.php", "database.yml", "appsettings.json",
        ],
        "concurrent_workers": 5,
        "request_timeout": 30,
        "max_retries": 3,
        "retry_backoff": 2,  # seconds (initial)
        "jitter": 0.5,       # random jitter fraction
    },
    "detection": {
        "min_confidence": 0.3,
        "mask_length": 4,
        "dedup": True,       # remove duplicates within same repo
        "env_var_pattern": r"^(?i)(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*([\"']?)([^\"'\s]+)\2",  # for .env files
    },
    "output": {
        "json_file": "findings.json",
        "state_file": "state.json",
        "log_file": "github_key_miner.log",
        "log_level": "INFO",
        "flush_interval": 0,      # flush after every N findings (0 = only flush on repo completion)
        "flush_on_repo": True,    # flush after each repository
    }
}

# ============================================================================
# KEY PATTERNS (extended)
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
        # OpenAI
        "openai": r"sk-[A-Za-z0-9]{32,48}",
        # Azure
        "azure_connection_string": r"DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9/+]{40}==[;]?",
        "azure_key": r"[A-Za-z0-9]{32,64}",
        # JWT
        "jwt": r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+",
        # Generic / high entropy
        "private_key": r"-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----",
        "api_key_generic": r"(?i)(?:api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-]{16,64})[\"']?",
        "password": r"(?i)(?:password|passwd|pwd)\s*[:=]\s*[\"']?([^\"'\s]{8,64})[\"']?",
        "token_generic": r"(?i)(?:token|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-\.]{20,64})[\"']?",
    }

    @classmethod
    def get_compiled(cls):
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

def setup_logging(log_file: str, log_level: str = "INFO", quiet: bool = False):
    """Configure logging to file and optionally console."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(numeric_level)

    # File handler (always)
    fh = logging.FileHandler(log_file)
    fh.setLevel(numeric_level)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)

    # Console handler (unless quiet)
    if not quiet:
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
        self.dedup = config.get("detection", {}).get("dedup", True)
        self.exclude_extensions = set(config.get("scanning", {}).get("exclude_extensions", []))
        self.exclude_paths = config.get("scanning", {}).get("exclude_paths", [])
        self.priority_files = set(config.get("scanning", {}).get("priority_files", []))
        self.max_file_size = config.get("scanning", {}).get("max_file_size", 1_000_000)
        self.logger = logging.getLogger(__name__)

    def should_scan_file(self, file_path: str, size: int = 0) -> bool:
        """Determine if a file should be scanned. Prioritises config files."""
        # Always scan priority files (by exact name or ending with)
        for p in self.priority_files:
            if file_path == p or file_path.endswith(p) or p in file_path:
                # Even if it matches excluded path/ext, we scan it
                if size <= self.max_file_size:
                    return True

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
        """Scan file content for secrets, including env‑var style keys."""
        findings = []
        lines = content.splitlines()

        # 1. Standard pattern scanning (generic regexes)
        for pattern_name, pattern in self.patterns.items():
            for match in pattern.finditer(content):
                matched_text = match.group(0)
                start_pos = match.start()
                line_no = content[:start_pos].count('\n') + 1
                start_line = max(0, line_no - 3)
                end_line = min(len(lines), line_no + 2)
                context_lines = lines[start_line:end_line]
                context = '\n'.join(context_lines)

                confidence = self._calculate_confidence(matched_text, pattern_name, context, file_path)
                if confidence >= self.min_confidence:
                    finding = {
                        "pattern": pattern_name,
                        "matched_text": self._mask_secret(matched_text),
                        "line_number": line_no,
                        "file_path": file_path,
                        "context": context,
                        "confidence": round(confidence, 3),
                        "raw_match": matched_text,  # for dedup
                    }
                    findings.append(finding)

        # 2. Environment variable detection (only for config-like files)
        env_pattern = self.config.get("detection", {}).get("env_var_pattern")
        if env_pattern and self._is_config_file(file_path):
            env_re = re.compile(env_pattern)
            for line_no, line in enumerate(lines, 1):
                match = env_re.match(line.strip())
                if match:
                    key = match.group(1)
                    value = match.group(3)
                    if len(value) >= 8:  # minimum length to be interesting
                        # Determine confidence (env vars are often secrets)
                        confidence = 0.85  # high because it's a config file
                        # Adjust down if it's a test/example placeholder
                        if re.search(r'(example|test|demo|sample|placeholder)', value, re.IGNORECASE):
                            confidence -= 0.2
                        # Boost if key contains SECRET, KEY, TOKEN, etc.
                        if re.search(r'(SECRET|KEY|TOKEN|PASSWORD|PASS)', key, re.IGNORECASE):
                            confidence += 0.1
                        confidence = min(1.0, max(0.0, confidence))
                        if confidence >= self.min_confidence:
                            finding = {
                                "pattern": "env_key",
                                "matched_text": f"{key}={self._mask_secret(value)}",
                                "line_number": line_no,
                                "file_path": file_path,
                                "context": line.strip(),
                                "confidence": round(confidence, 3),
                                "raw_match": f"{key}={value}",  # for dedup
                            }
                            findings.append(finding)

        return findings

    def _is_config_file(self, file_path: str) -> bool:
        """Check if file is likely a configuration file."""
        config_patterns = [
            ".env", ".yml", ".yaml", ".json", ".properties", ".xml",
            "settings", "config", "credentials", "secrets", "Dockerfile"
        ]
        lower_path = file_path.lower()
        for pattern in config_patterns:
            if pattern in lower_path:
                return True
        return False

    def _calculate_confidence(self, secret: str, pattern_name: str, context: str, file_path: str) -> float:
        confidence = 0.7
        # Boost if it's a config file
        if self._is_config_file(file_path):
            confidence += 0.1
        # Penalize obvious false positives
        fp_indicators = [
            r"example", r"test", r"demo", r"sample",
            r"placeholder", r"your[_-]?", r"changeme",
            r"<[^>]+>", r"\{[^}]+\}", r"ENV\[[^\]]+\]",
        ]
        for fp in fp_indicators:
            if re.search(fp, context, re.IGNORECASE):
                confidence -= 0.15
                break
        if len(secret) < 16:
            confidence -= 0.1
        if re.search(r'^\s*//|^\s*#|/\*.*\*/', context, re.MULTILINE):
            confidence -= 0.05  # less penalty for config files because comments are common
        if re.search(rf'=.*{re.escape(secret)}.*;', context):
            confidence += 0.1
        if "aws" in pattern_name and len(secret) >= 20:
            confidence += 0.1
        if "private_key" in pattern_name:
            confidence += 0.15
        return max(0.0, min(1.0, confidence))

    def _mask_secret(self, secret: str) -> str:
        if len(secret) <= self.mask_len * 2:
            return '*' * len(secret)
        return secret[:self.mask_len] + '*' * (len(secret) - self.mask_len * 2) + secret[-self.mask_len:]

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

class StateManager:
    """Manages persistent state for resume support."""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.data = self._load()

    def _load(self) -> Dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            "processed_repos": [],
            "total_findings": 0,
            "start_time": datetime.now().isoformat(),
            "last_update": None,
            "repo_stats": {}
        }

    def save(self):
        self.data["last_update"] = datetime.now().isoformat()
        with open(self.state_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def mark_repo_done(self, repo_name: str, findings_count: int, files_scanned: int):
        if repo_name not in self.data["processed_repos"]:
            self.data["processed_repos"].append(repo_name)
        self.data["total_findings"] += findings_count
        self.data["repo_stats"][repo_name] = {
            "findings": findings_count,
            "files_scanned": files_scanned,
            "scanned_at": datetime.now().isoformat()
        }
        self.save()

    def is_repo_processed(self, repo_name: str) -> bool:
        return repo_name in self.data["processed_repos"]

# ============================================================================
# GITHUB MINER
# ============================================================================

class GitHubMiner:
    """Mine GitHub repositories for exposed secrets."""

    def __init__(self, config: Dict, resume: bool = False):
        self.config = config
        self.token = config["github"].get("token") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token is required. Set GITHUB_TOKEN env or in config.")
        # Fix deprecation warning
        auth = Auth.Token(self.token)
        self.github = Github(auth=auth, timeout=config["scanning"].get("request_timeout", 30))
        self.search_queries = config["github"].get("search_queries", [])
        self.max_repos = config["github"].get("max_repos", 100)
        self.languages = config["github"].get("languages", [])
        self.min_stars = config["github"].get("min_stars", 0)
        self.exclude_repos = set(config["github"].get("exclude_repos", []))
        self.include_repos = set(config["github"].get("include_repos", []))
        self.concurrent_workers = config["scanning"].get("concurrent_workers", 5)
        self.max_retries = config["scanning"].get("max_retries", 3)
        self.retry_backoff = config["scanning"].get("retry_backoff", 2)
        self.jitter = config["scanning"].get("jitter", 0.5)
        self.detector = KeyDetector(config)
        self.logger = logging.getLogger(__name__)
        self.resume = resume
        self.state_mgr = StateManager(config["output"]["state_file"]) if resume else None

    def search_repositories(self) -> List:
        repos = []
        if self.include_repos:
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
                    # Skip already processed if resuming
                    if self.resume and self.state_mgr.is_repo_processed(repo.full_name):
                        self.logger.info(f"Skipping already processed repo: {repo.full_name}")
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

    def scan_repository(self, repo) -> Tuple[List[Dict], int]:
        """Returns (findings, files_scanned)."""
        findings = []
        files_scanned = 0
        self.logger.info(f"Scanning repository: {repo.full_name}")

        try:
            default_branch = repo.default_branch
            tree = repo.get_git_tree(sha=default_branch, recursive=True)
            files_to_scan = []
            for item in tree.tree:
                if item.type == "blob":
                    file_path = item.path
                    if self.detector.should_scan_file(file_path, item.size):
                        files_to_scan.append((file_path, item.sha, item.size))

            self.logger.info(f"Scanning {len(files_to_scan)} files in {repo.full_name} (after filtering)")
            files_scanned = len(files_to_scan)

            # Deduplication set (per repo)
            seen_secrets = set()

            with ThreadPoolExecutor(max_workers=self.concurrent_workers) as executor:
                future_to_file = {
                    executor.submit(self._fetch_and_scan_file, repo, file_path, sha, size): (file_path, sha)
                    for file_path, sha, size in files_to_scan
                }
                with tqdm(total=len(files_to_scan), desc=f"Scanning {repo.full_name}", unit="file", disable=self.config.get("no_progress", False)) as pbar:
                    for future in as_completed(future_to_file):
                        file_path, sha = future_to_file[future]
                        try:
                            file_findings = future.result(timeout=30)
                            if file_findings:
                                # Dedup by raw secret content
                                for f in file_findings:
                                    secret_hash = hashlib.sha256(f["raw_match"].encode()).hexdigest()
                                    if self.detector.dedup:
                                        if secret_hash not in seen_secrets:
                                            seen_secrets.add(secret_hash)
                                            findings.append(f)
                                    else:
                                        findings.append(f)
                        except Exception as e:
                            self.logger.error(f"Error scanning file {file_path} in {repo.full_name}: {e}")
                        pbar.update(1)

        except GithubException as e:
            self.logger.error(f"GitHub error scanning {repo.full_name}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error scanning {repo.full_name}: {e}")

        return findings, files_scanned

    def _fetch_and_scan_file(self, repo, file_path: str, sha: str, size: int) -> List[Dict]:
        if size > self.detector.max_file_size:
            return []
        content = self._get_file_content(repo, file_path, sha)
        if content is None:
            return []
        return self.detector.scan_content(content, file_path)

    def _get_file_content(self, repo, file_path: str, sha: str) -> Optional[str]:
        for attempt in range(self.max_retries):
            try:
                content_obj = repo.get_contents(file_path, ref=repo.default_branch)
                if content_obj and content_obj.content:
                    decoded = base64.b64decode(content_obj.content).decode('utf-8', errors='ignore')
                    return decoded
                return None
            except GithubException as e:
                if e.status == 403:
                    # Check for secondary rate limit
                    if "secondary rate limit" in str(e).lower():
                        retry_after = self._parse_retry_after(e)
                        if retry_after:
                            sleep_time = retry_after + random.uniform(0, self.jitter)
                            self.logger.warning(f"Secondary rate limit. Sleeping {sleep_time:.0f}s")
                            time.sleep(sleep_time)
                            continue  # Retry after wait
                    # Otherwise, treat as rate limit
                    self._handle_rate_limit()
                elif e.status in (404, 409):
                    return None
                else:
                    self.logger.warning(f"Attempt {attempt+1} failed for {file_path}: {e}")
                    if attempt < self.max_retries - 1:
                        sleep_time = self.retry_backoff * (attempt + 1) + random.uniform(0, self.jitter)
                        time.sleep(sleep_time)
            except Exception as e:
                self.logger.warning(f"Attempt {attempt+1} failed for {file_path}: {e}")
                if attempt < self.max_retries - 1:
                    sleep_time = self.retry_backoff * (attempt + 1) + random.uniform(0, self.jitter)
                    time.sleep(sleep_time)
        return None

    def _parse_retry_after(self, exception: GithubException) -> Optional[int]:
        if hasattr(exception, 'headers') and 'Retry-After' in exception.headers:
            try:
                return int(exception.headers['Retry-After'])
            except:
                pass
        return None

    def _handle_rate_limit(self):
        try:
            rate = self.github.get_rate_limit()
            reset_time = rate.core.reset
            sleep_seconds = (reset_time - datetime.now()).total_seconds() + 5
            if sleep_seconds > 0:
                self.logger.warning(f"Rate limit hit. Sleeping for {sleep_seconds:.0f} seconds.")
                time.sleep(sleep_seconds)
        except:
            time.sleep(60)

    def get_owner_info(self, repo) -> Dict:
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
# JSON OUTPUT (with incremental flush)
# ============================================================================

class FindingsStore:
    """Manages findings in memory and writes to JSON incrementally."""

    def __init__(self, output_file: str, metadata: Dict, flush_interval: int = 0, flush_on_repo: bool = True):
        self.output_file = output_file
        self.metadata = metadata
        self.findings = []
        self.flush_interval = flush_interval
        self.flush_on_repo = flush_on_repo
        self._lock = None  # For thread safety if needed; we only write from main thread.
        self.logger = logging.getLogger(__name__)

    def add_findings(self, new_findings: List[Dict], repo_name: str):
        """Add findings and optionally flush."""
        if not new_findings:
            return
        # Add repository info to each finding (if not already)
        for f in new_findings:
            f["repository"] = repo_name
            # Remove raw_match if present (we don't want it in output)
            f.pop("raw_match", None)
        self.findings.extend(new_findings)
        # Check flush conditions
        if self.flush_on_repo or (self.flush_interval > 0 and len(self.findings) >= self.flush_interval):
            self.flush()

    def flush(self):
        """Write current findings to JSON file."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "metadata": self.metadata,
            "findings": self.findings,
        }
        tmp_file = self.output_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, self.output_file)
        self.logger.info(f"Flushed {len(self.findings)} findings to {self.output_file}")

    def finalize(self):
        """Final flush and close."""
        self.flush()

# ============================================================================
# MAIN
# ============================================================================

def load_config(config_path: Optional[str] = None) -> Dict:
    config = DEFAULT_CONFIG.copy()
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f)
            for key, value in user_config.items():
                if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value
    if os.environ.get("GITHUB_TOKEN"):
        config["github"]["token"] = os.environ["GITHUB_TOKEN"]
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
    parser.add_argument("--resume", action="store_true", help="Resume from previous state (skip processed repos)")
    parser.add_argument("--flush-interval", type=int, help="Flush findings after every N findings (0=only on repo)")
    parser.add_argument("--no-flush-on-repo", action="store_true", help="Do not flush after each repository")
    parser.add_argument("--quiet", action="store_true", help="Suppress console logging")
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
    if args.flush_interval is not None:
        config["output"]["flush_interval"] = args.flush_interval
    if args.no_flush_on_repo:
        config["output"]["flush_on_repo"] = False
    config["no_progress"] = args.no_progress

    # Setup logging
    log_file = config["output"]["log_file"]
    log_level = config["output"].get("log_level", "INFO")
    logger = setup_logging(log_file, log_level, quiet=args.quiet)

    logger.info("=" * 60)
    logger.info("GitHub API Key Miner Started")
    logger.info(f"Config: {config}")

    # Initialize miner
    try:
        miner = GitHubMiner(config, resume=args.resume)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Search repositories
    repos = miner.search_repositories()
    if not repos:
        logger.warning("No repositories found to scan.")
        sys.exit(0)

    logger.info(f"Found {len(repos)} repositories to scan.")

    # Prepare metadata and findings store
    metadata = {
        "start_time": datetime.now().isoformat(),
        "repos_scanned": len(repos),
        "config": config,
    }
    store = FindingsStore(
        output_file=config["output"]["json_file"],
        metadata=metadata,
        flush_interval=config["output"].get("flush_interval", 0),
        flush_on_repo=config["output"].get("flush_on_repo", True)
    )

    # Signal handler for graceful shutdown
    def signal_handler(sig, frame):
        logger.warning("Received interrupt. Flushing findings and exiting...")
        store.finalize()
        if args.resume and miner.state_mgr:
            miner.state_mgr.save()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    # Scan each repository
    total_findings = 0
    for repo in repos:
        if args.resume and miner.state_mgr.is_repo_processed(repo.full_name):
            continue

        findings, files_scanned = miner.scan_repository(repo)
        if findings:
            owner_info = miner.get_owner_info(repo)
            for f in findings:
                f["owner"] = owner_info
                f["repo_url"] = repo.html_url
                f["default_branch"] = repo.default_branch
            store.add_findings(findings, repo.full_name)
            total_findings += len(findings)

        if args.resume and miner.state_mgr:
            miner.state_mgr.mark_repo_done(repo.full_name, len(findings), files_scanned)

    # Final flush
    store.finalize()
    if args.resume and miner.state_mgr:
        miner.state_mgr.save()

    # Summary
    logger.info("=" * 60)
    logger.info(f"Scan completed. Total findings: {total_findings}")
    if total_findings > 0:
        pattern_counts = {}
        for f in store.findings:
            pattern = f.get("pattern", "unknown")
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        logger.info("Findings by pattern:")
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            logger.info(f"  {pattern}: {count}")

    logger.info("Done.")

if __name__ == "__main__":
    main()