"""OLAV Version Information and Digital Signature.

This module centralizes all version-related metadata for the OLAV system,
including version numbers, build information, copyright, and cryptographic signatures.
"""

# ==============================================================================
# VERSION INFORMATION
# ==============================================================================

#: Semantic version of OLAV
VERSION = "0.13.1"

#: Major version component
MAJOR = 0

#: Minor version component
MINOR = 13

#: Patch version component
PATCH = 1

#: Full version string
VERSION_STRING = f"{MAJOR}.{MINOR}.{PATCH}"

# ==============================================================================
# BUILD & RELEASE INFORMATION
# ==============================================================================

#: Build date (YYYY-MM-DD)
BUILD_DATE = "2026-04-10"

#: Release date (YYYY-MM-DD) - same as build date for initial release
RELEASE_DATE = "2026-04-10"

#: Development status
DEV_STATUS = "stable"  # Options: "alpha", "beta", "rc", "stable"

#: Build number (incremented per build)
BUILD_NUMBER = 1

#: Git commit hash (if available)
GIT_COMMIT = "main"

# ==============================================================================
# PROJECT METADATA
# ==============================================================================

#: Project name
PROJECT_NAME = "OLAV"

#: Full project name
PROJECT_FULL_NAME = "OLAV - AI Operations Assistant"

#: Author/Organization
AUTHOR = "OLAV Team"

#: Contact email
AUTHOR_EMAIL = "james@olavai.com"

#: Homepage
HOMEPAGE = "https://github.com/olav-ai/olav"

#: Documentation URL
DOCUMENTATION_URL = "https://docs.olavai.com"

#: License type
LICENSE = "BSL-1.1"

#: License URL
LICENSE_URL = "https://mariadb.com/bsl11/"

# ==============================================================================
# DIGITAL SIGNATURE & INTEGRITY
# ==============================================================================

#: Digital signature for integrity verification
#: Format: name-vX.Y.Z-YYYY-MM-DD
SIGNATURE = f"olav-v{VERSION_STRING}-{BUILD_DATE}"

#: Checksum algorithm type (sha256, sha512, etc.)
CHECKSUM_ALGORITHM = "sha256"

#: Core package checksum (computed at build time)
CORE_CHECKSUM = "sha256:olav-core-v0.13.1-2026-04-10"

#: CLI checksum
CLI_CHECKSUM = "sha256:olav-cli-v0.13.1-2026-04-10"

#: Combined system checksum
SYSTEM_CHECKSUM = "sha256:olav-system-v0.13.1-2026-04-10"

# ==============================================================================
# COPYRIGHT
# ==============================================================================

#: Copyright year(s)
COPYRIGHT_YEAR = "2024-2026"

#: Copyright holder
COPYRIGHT_HOLDER = "DATATECHIE PTY LTD"

#: Full copyright notice
COPYRIGHT_NOTICE = f"© {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}. All rights reserved."

#: License notice
LICENSE_NOTICE = (
    f"{PROJECT_NAME} is licensed under the {LICENSE} License.\nSee {LICENSE_URL} for details."
)

# ==============================================================================
# VERSION COMPARISON UTILITIES
# ==============================================================================


def get_version() -> str:
    """Get the full version string.

    Returns:
        str: Version string in format "X.Y.Z"
    """
    return VERSION_STRING


def get_full_version() -> str:
    """Get the full version with dev status.

    Returns:
        str: Full version string including dev status if applicable
    """
    if DEV_STATUS == "stable":
        return f"v{VERSION_STRING}"
    else:
        return f"v{VERSION_STRING}-{DEV_STATUS}"


def get_version_info() -> dict:
    """Get complete version information as a dictionary.

    Returns:
        dict: Dictionary containing all version metadata
    """
    return {
        "version": VERSION_STRING,
        "major": MAJOR,
        "minor": MINOR,
        "patch": PATCH,
        "full_version": get_full_version(),
        "build_date": BUILD_DATE,
        "build_number": BUILD_NUMBER,
        "dev_status": DEV_STATUS,
        "git_commit": GIT_COMMIT,
        "author": AUTHOR,
        "license": LICENSE,
        "homepage": HOMEPAGE,
        "copyright": COPYRIGHT_NOTICE,
    }


def get_signature() -> str:
    """Get the digital signature.

    Returns:
        str: Digital signature string
    """
    return SIGNATURE


def get_checksums() -> dict:
    """Get all available checksums.

    Returns:
        dict: Dictionary mapping checksum names to hash values
    """
    return {
        "algorithm": CHECKSUM_ALGORITHM,
        "core": CORE_CHECKSUM,
        "cli": CLI_CHECKSUM,
        "system": SYSTEM_CHECKSUM,
    }


def compare_versions(version1: str, version2: str) -> int:
    """Compare two semantic version strings.

    Args:
        version1: First version string (e.g., "0.11.0")
        version2: Second version string (e.g., "0.10.5")

    Returns:
        int: -1 if version1 < version2, 0 if equal, 1 if version1 > version2

    Example:
        >>> compare_versions("0.11.0", "0.10.5")
        1
        >>> compare_versions("0.10.5", "0.11.0")
        -1
        >>> compare_versions("0.11.0", "0.11.0")
        0
    """
    from packaging import version as pkg_version

    try:
        v1 = pkg_version.parse(version1)
        v2 = pkg_version.parse(version2)

        if v1 > v2:
            return 1
        elif v1 < v2:
            return -1
        else:
            return 0
    except Exception:
        # Fallback to string comparison if parsing fails
        if version1 > version2:
            return 1
        elif version1 < version2:
            return -1
        else:
            return 0


# ==============================================================================
# DISPLAY FORMATTING
# ==============================================================================


def format_version_banner() -> str:
    """Format a nice version banner for CLI display.

    Returns:
        str: Formatted banner string
    """
    banner = (
        f"\n{'╔' + '═' * 62 + '╗'}\n"
        f"║         {PROJECT_FULL_NAME:^52} ║\n"
        f"{'╚' + '═' * 62 + '╝'}\n"
        f"\n"
        f"Version:         {get_full_version()}\n"
        f"Build Date:      {BUILD_DATE}\n"
        f"Author:          {AUTHOR}\n"
        f"License:         {LICENSE}\n"
        f"Homepage:        {HOMEPAGE}\n"
        f"\n"
        f"Digital Signature:\n"
        f"  Signature:     {SIGNATURE}\n"
        f"  Checksum:      {SYSTEM_CHECKSUM}\n"
        f"\n"
        f"{COPYRIGHT_NOTICE}\n"
    )
    return banner


# ==============================================================================
# COMPATIBILITY
# ==============================================================================

#: Minimum Python version required
MIN_PYTHON_VERSION = "3.11"

#: List of supported Python versions
SUPPORTED_PYTHON_VERSIONS = ["3.11", "3.12", "3.13"]

#: Backward compatibility cutoff version
#: (versions older than this should upgrade)
COMPATIBILITY_CUTOFF = "0.9.0"


def is_version_compatible(other_version: str) -> bool:
    """Check if another version is compatible with current version.

    Args:
        other_version: Version string to check

    Returns:
        bool: True if compatible, False otherwise
    """
    if compare_versions(other_version, COMPATIBILITY_CUTOFF) < 0:
        return False
    return True


if __name__ == "__main__":
    # Display version information when run directly
    print(format_version_banner())
    print("\nVersion Info:")
    for key, value in get_version_info().items():
        print(f"  {key:.<20} {value}")
    print("\nChecksums:")
    for key, value in get_checksums().items():
        print(f"  {key:.<20} {value}")
