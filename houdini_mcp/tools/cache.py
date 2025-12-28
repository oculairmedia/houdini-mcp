"""In-memory caching for expensive Houdini queries.

This module provides caching infrastructure for data that rarely changes
during a Houdini session, such as node types and parameter schemas.

Key features:
- TTL (time-to-live) based expiration
- Manual invalidation support
- Cache stats for monitoring
- Thread-safe operations

Usage:
    from houdini_mcp.tools.cache import node_type_cache, invalidate_all_caches

    # Cache is populated automatically on first call
    types = node_type_cache.get_all_types(hou)

    # Filter from cache (instant)
    sop_types = node_type_cache.filter_types(category="Sop", name_filter="noise")

    # Invalidate on scene load
    invalidate_all_caches()
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("houdini_mcp.tools.cache")


@dataclass
class CacheEntry:
    """A single cache entry with value and metadata."""

    value: Any
    timestamp: float
    ttl: float  # Time-to-live in seconds

    def is_expired(self) -> bool:
        """Check if the entry has expired."""
        if self.ttl <= 0:
            return False  # TTL of 0 means never expire
        return time.time() - self.timestamp > self.ttl


@dataclass
class CacheStats:
    """Statistics for cache performance monitoring."""

    hits: int = 0
    misses: int = 0
    invalidations: int = 0
    last_populate_time_ms: float = 0
    entry_count: int = 0

    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total


class BaseCache:
    """Base class for in-memory caches with TTL support."""

    def __init__(self, name: str, default_ttl: float = 3600.0):
        """
        Initialize the cache.

        Args:
            name: Cache name for logging
            default_ttl: Default TTL in seconds (default: 1 hour, 0 = never expire)
        """
        self.name = name
        self.default_ttl = default_ttl
        self._lock = threading.RLock()
        self._stats = CacheStats()
        self._valid = False

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def is_valid(self) -> bool:
        """Check if cache is populated and valid."""
        return self._valid

    def invalidate(self) -> None:
        """Invalidate the cache, forcing repopulation on next access."""
        with self._lock:
            self._valid = False
            self._stats.invalidations += 1
            logger.debug(f"Cache '{self.name}' invalidated")

    def _record_hit(self) -> None:
        """Record a cache hit."""
        self._stats.hits += 1

    def _record_miss(self) -> None:
        """Record a cache miss."""
        self._stats.misses += 1


class NodeTypeCache(BaseCache):
    """
    Cache for Houdini node types.

    Node types are static during a session - they only change if plugins
    are loaded/unloaded or Houdini restarts. This cache stores all node
    types with their categories and descriptions, allowing instant
    filtering without RPC calls.
    """

    def __init__(self, ttl: float = 0.0):
        """
        Initialize node type cache.

        Args:
            ttl: Time-to-live in seconds. Default 0 = never expire.
                 Node types are truly static during a session.
        """
        super().__init__("node_types", ttl)
        self._all_types: List[Dict[str, str]] = []
        self._by_category: Dict[str, List[Dict[str, str]]] = {}
        self._categories: List[str] = []

    def get_all_types(
        self,
        hou: Any,
        host: str = "localhost",
        port: int = 18811,
    ) -> List[Dict[str, str]]:
        """
        Get all node types, populating cache if needed.

        This is the primary method to populate the cache. On first call,
        it fetches all node types from Houdini. Subsequent calls return
        cached data instantly.

        Args:
            hou: The hou module (from ensure_connected)
            host: Houdini host (for cache key)
            port: Houdini port (for cache key)

        Returns:
            List of all node types with category, name, description
        """
        with self._lock:
            if self._valid and self._all_types:
                self._record_hit()
                return self._all_types

            self._record_miss()
            self._populate(hou)
            return self._all_types

    def filter_types(
        self,
        category: Optional[str] = None,
        name_filter: Optional[str] = None,
        max_results: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, str]], int, bool]:
        """
        Filter cached node types.

        This is a fast operation that works on cached data.
        Must call get_all_types() first to populate cache.

        Args:
            category: Optional category filter (case-insensitive)
            name_filter: Optional substring filter for type names
            max_results: Maximum results to return
            offset: Number of results to skip

        Returns:
            Tuple of (filtered_types, total_matched, has_more)
        """
        with self._lock:
            if not self._valid:
                return [], 0, False

            # Start with category filter
            if category:
                cat_lower = category.lower()
                source = self._by_category.get(cat_lower, [])
            else:
                source = self._all_types

            # Apply name filter
            if name_filter:
                filter_lower = name_filter.lower()
                source = [t for t in source if filter_lower in t["name"].lower()]

            total_matched = len(source)

            # Apply pagination
            start = offset
            end = offset + max_results
            result = source[start:end]

            has_more = end < total_matched

            return result, total_matched, has_more

    def get_categories(self, hou: Any) -> List[str]:
        """
        Get list of available node type categories.

        Args:
            hou: The hou module

        Returns:
            List of category names
        """
        with self._lock:
            if not self._valid:
                self.get_all_types(hou)
            return self._categories.copy()

    def _populate(self, hou: Any) -> None:
        """
        Populate the cache with all node types.

        This is called internally when cache is invalid.
        Uses batch fetching for performance.
        """
        start_time = time.time()
        logger.info(f"Populating node type cache...")

        all_types: List[Dict[str, str]] = []
        by_category: Dict[str, List[Dict[str, str]]] = {}
        categories: List[str] = []

        try:
            # Try fast batch approach first (using remote exec)
            all_types, by_category, categories = self._populate_fast(hou)

            if not all_types:
                # Fallback to standard approach
                all_types, by_category, categories = self._populate_standard(hou)

        except Exception as e:
            logger.warning(f"Cache population failed: {e}")
            all_types, by_category, categories = [], {}, []

        self._all_types = all_types
        self._by_category = by_category
        self._categories = categories
        self._valid = True
        self._stats.entry_count = len(all_types)

        elapsed_ms = (time.time() - start_time) * 1000
        self._stats.last_populate_time_ms = elapsed_ms
        logger.info(
            f"Node type cache populated: {len(all_types)} types in "
            f"{len(categories)} categories ({elapsed_ms:.1f}ms)"
        )

    def _populate_fast(
        self, hou: Any
    ) -> Tuple[List[Dict[str, str]], Dict[str, List[Dict[str, str]]], List[str]]:
        """
        Fast population using remote Python execution.

        Runs entirely on Houdini side to avoid per-type RPC calls.
        """
        from .hscript import HscriptBatch

        batch = HscriptBatch(hou)

        if not batch.has_remote_exec():
            logger.debug("Remote exec not available, using standard method")
            return [], {}, []

        # Execute Python on Houdini side to collect all node types
        code = """
import json

result = {"types": [], "by_category": {}, "categories": []}

for cat_name, cat in hou.nodeTypeCategories().items():
    result["categories"].append(cat_name)
    cat_types = []

    for type_name, type_obj in cat.nodeTypes().items():
        try:
            desc = type_obj.description()
        except:
            desc = ""

        entry = {"category": cat_name, "name": type_name, "description": desc}
        result["types"].append(entry)
        cat_types.append(entry)

    result["by_category"][cat_name.lower()] = cat_types

print(json.dumps(result))
"""
        import json

        output = batch._exec_python(code)
        if not output:
            return [], {}, []

        try:
            data = json.loads(output.strip())
            all_types = data.get("types", [])
            by_category = data.get("by_category", {})
            categories = data.get("categories", [])
            return all_types, by_category, categories
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse node type JSON: {e}")
            return [], {}, []

    def _populate_standard(
        self, hou: Any
    ) -> Tuple[List[Dict[str, str]], Dict[str, List[Dict[str, str]]], List[str]]:
        """
        Standard population using RPyC proxy calls.

        Slower but works in all environments.
        """
        all_types: List[Dict[str, str]] = []
        by_category: Dict[str, List[Dict[str, str]]] = {}
        categories: List[str] = []

        try:
            for cat_name, cat in hou.nodeTypeCategories().items():
                categories.append(cat_name)
                cat_types: List[Dict[str, str]] = []

                for type_name, type_obj in cat.nodeTypes().items():
                    try:
                        desc = type_obj.description()
                    except Exception:
                        desc = ""

                    entry = {"category": cat_name, "name": type_name, "description": desc}
                    all_types.append(entry)
                    cat_types.append(entry)

                by_category[cat_name.lower()] = cat_types

        except Exception as e:
            logger.warning(f"Standard population failed: {e}")

        return all_types, by_category, categories


class ParameterSchemaCache(BaseCache):
    """
    Cache for parameter schemas.

    Parameter schemas are static per node type - they define what parameters
    a node type has, their types, ranges, etc. This is expensive to fetch
    but never changes for a given node type.
    """

    def __init__(self, ttl: float = 0.0):
        """
        Initialize parameter schema cache.

        Args:
            ttl: Time-to-live in seconds. Default 0 = never expire.
        """
        super().__init__("parameter_schemas", ttl)
        # Key: (category, type_name) -> schema dict
        self._schemas: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def get_schema(
        self,
        hou: Any,
        node_type_category: str,
        node_type_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get parameter schema for a node type.

        Args:
            hou: The hou module
            node_type_category: Node category (e.g., "Sop")
            node_type_name: Node type name (e.g., "sphere")

        Returns:
            Schema dict or None if not found
        """
        key = (node_type_category.lower(), node_type_name.lower())

        with self._lock:
            if key in self._schemas:
                self._record_hit()
                return self._schemas[key]

            self._record_miss()
            schema = self._fetch_schema(hou, node_type_category, node_type_name)
            if schema:
                self._schemas[key] = schema
                self._stats.entry_count = len(self._schemas)
            return schema

    def _fetch_schema(
        self,
        hou: Any,
        node_type_category: str,
        node_type_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch parameter schema from Houdini.

        This is called when schema is not in cache.
        """
        # Implementation would go here - for now return None
        # This can be implemented when needed
        return None


# =============================================================================
# Global Cache Instances
# =============================================================================

# Global node type cache - shared across all tool calls
node_type_cache = NodeTypeCache()

# Global parameter schema cache
parameter_schema_cache = ParameterSchemaCache()


def invalidate_all_caches() -> None:
    """
    Invalidate all caches.

    Call this when:
    - Loading a new scene
    - Creating a new scene
    - Plugins are loaded/unloaded
    - Reconnecting to Houdini
    """
    node_type_cache.invalidate()
    parameter_schema_cache.invalidate()
    logger.info("All caches invalidated")


def get_cache_stats() -> Dict[str, Any]:
    """
    Get statistics for all caches.

    Returns:
        Dict with stats for each cache
    """
    return {
        "node_types": {
            "valid": node_type_cache.is_valid(),
            "hits": node_type_cache.stats.hits,
            "misses": node_type_cache.stats.misses,
            "hit_rate": f"{node_type_cache.stats.hit_rate():.1%}",
            "invalidations": node_type_cache.stats.invalidations,
            "entry_count": node_type_cache.stats.entry_count,
            "last_populate_ms": node_type_cache.stats.last_populate_time_ms,
        },
        "parameter_schemas": {
            "valid": parameter_schema_cache.is_valid(),
            "hits": parameter_schema_cache.stats.hits,
            "misses": parameter_schema_cache.stats.misses,
            "hit_rate": f"{parameter_schema_cache.stats.hit_rate():.1%}",
            "invalidations": parameter_schema_cache.stats.invalidations,
            "entry_count": parameter_schema_cache.stats.entry_count,
        },
    }
