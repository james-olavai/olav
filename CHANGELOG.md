# Changelog

All notable changes to OLAV will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-02-25

### 🚀 Features

- **Architecture**: Complete migration to DeepAgents + LangGraph framework
- **CLI**: Full migration to deepagents-cli with native components
- **CLI**: Migration to argparse for argument parsing
- **CLI**: Add daemon mode for persistent agent process
- **Ops**: Implement skill independence for diff and web search tools
- **Ops**: Add search_cache tool for semantic cache lookup
- **Ops**: Add execute_sql table output
- **Core**: Add ResponseCache with snapshot-aware invalidation
- **Knowledge Base**: Integrate unified KB system with DuckDB
- **Cron**: Implement periodic task scheduler with python-crontab
- **Command Learner**: Implement Command Learner Agent v2.1.0
- **Admin**: Implement ultra-minimalist Admin Agent v2.1.0
- **Reporting**: Enhance report quality with deep LLM analysis and root cause reasoning

### ⚡ Performance

- Add DuckDB response cache for instant repeated queries
- Add --prewarm flag for faster first query
- Make prewarm default, optimize cache check order
- Implement lazy loading + large data handling
- Add streaming output + direct SQL mode

### 🐛 Bug Fixes

- Fix CLI startup and tool discovery issues
- Add prewarm to interactive mode
- Eliminate duplicate output by replacing streaming with single invoke+render
- Replace hardcoded snapshot commands with NTC-based dynamic resolution

### 🔧 Maintenance

- Refactor CLI: remove dead code, cli_main.py and stale cache functions
- Consolidate hardcoded parameters into KnowledgeSettings config
- CLI simplification: remove admin prefix

### 📚 Documentation

- Complete AUDIT user guide in Chinese and English
- Unified documentation structure
- Clean up legacy code
- Implement Map-Reduce batch fix script functionality

---

## [0.9.x] - 2026-01 to 2026-02 (Legacy)

Previous versions documentation is available in `_legacy_archived/` directory.

- v0.9.9: DeepAgents CLI migration phase 1-3
- v0.9.8: Command Learner Agent v2.0
- v0.9.7: Knowledge Base integration
- v0.9.6: Response caching
- v0.9.5: Cron scheduler
- v0.9.0-v0.9.4: Legacy architecture
