"""Schema-Aware SuzieQ tools - 2 universal tools instead of 120+.

Extended to support advanced analytical operations declared in prompts:
    - top: Sort records by a metric and return top N
    - describe: Return schema & field metadata for a table
    - lpm: Longest Prefix Match lookup in routes
    - path_show: Path trace between source/dest (alias of path table get)
    - assert: Verification checks (maps to aver)

Note: SuzieQ is optional dependency (used via Docker).
Set ENABLE_SUZIEQ=true to enable local SuzieQ tools.
"""

@tool
async def suzieq_schema_search(query: str) -> dict[str, Any]:
    """Search SuzieQ schema to discover available tables and fields."""
    cache_key = f"suzieq_schema_search:{query.strip().lower()}"
    redis_url = getattr(settings, "redis_url", None) or os.getenv("REDIS_URL")
    rds = None
    if redis_url:
        try:
            rds = redis.from_url(redis_url, decode_responses=True)
        except Exception:
            rds = None
    if rds:
        cached = rds.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass
    keywords = query.lower().split()
    matching_tables = [
        table for table in SUZIEQ_SCHEMA
        if any(keyword in table.lower() or keyword in SUZIEQ_SCHEMA[table]["description"].lower() for keyword in keywords)
    ]
    if not matching_tables:
        matching_tables = list(SUZIEQ_SCHEMA.keys())[:5]
    result: dict[str, Any] = {"tables": matching_tables}
    for table in matching_tables:
        result[table] = {
            **SUZIEQ_SCHEMA[table],
            "methods": ["get", "summarize"],
        }
    if rds:
        try:
            rds.setex(cache_key, 600, json.dumps(result, ensure_ascii=False))
        except Exception as e:
            logging.warning(f"Redis cache set failed: {e}")
    return result
    "macs": {
        "fields": ["namespace", "hostname", "vlan", "macaddr", "oif", "remoteVtepIp"],
        "description": "MAC address table",
    },
                    "error": f"Unknown table '{table}'. Use suzieq_schema_search to discover available tables.",
                    "available_tables": list(SUZIEQ_SCHEMA.keys()),
                }
            parquet_dir = os.getenv("SUZIEQ_PARQUET_DIR", "data/suzieq-parquet")
            table_dir = os.path.join(parquet_dir, table)


# Export standalone tool functions for LangChain compatibility
@tool
async def suzieq_schema_search(query: str) -> dict[str, Any]:
    # Parquet-only: always available if files exist
    cache_key = f"suzieq_schema_search:{query.strip().lower()}"
    @tool
    async def suzieq_query(
        table: str,
        method: Literal["get", "summarize"],
        **filters: Any,
    ) -> dict[str, Any]:
        """Query SuzieQ Parquet data for a table."""
        if table not in SUZIEQ_SCHEMA:
            return {
                "error": f"Unknown table '{table}'. Use suzieq_schema_search to discover available tables.",
                "available_tables": list(SUZIEQ_SCHEMA.keys()),
            }
        parquet_dir = os.getenv("SUZIEQ_PARQUET_DIR", "data/suzieq-parquet")
        table_dir = os.path.join(parquet_dir, table)
        if not os.path.exists(table_dir):
            return {
                "error": f"No data found for table '{table}'",
                "hint": "Data may not have been collected yet. Check SuzieQ poller status.",
                "expected_path": table_dir,
            }
        try:
            import glob
            parquet_files = glob.glob(os.path.join(table_dir, "**", "*.parquet"), recursive=True)
            if not parquet_files:
                return {
                    "error": f"No parquet files found in {table_dir}",
                    "hint": "SuzieQ may not have collected data for this table yet.",
                }
            dfs = [pd.read_parquet(f) for f in parquet_files]
            df = pd.concat(dfs, ignore_index=True)
            for field, value in filters.items():
                if field in df.columns:
                    df = df[df[field] == value]
            if method == "get":
                data = df.head(100).to_dict(orient="records")
                return {
                    "data": data,
                    "count": len(df),
                    "columns": list(df.columns),
                    "table": table,
                    "truncated": len(df) > 100,
                }
            elif method == "summarize":
                summary = {}
                if "state" in df.columns:
                    summary["state_counts"] = df["state"].value_counts().to_dict()
                if "adminState" in df.columns:
                    summary["admin_state_counts"] = df["adminState"].value_counts().to_dict()
                if "type" in df.columns:
                    summary["type_counts"] = df["type"].value_counts().to_dict()
                summary["total_records"] = len(df)
                summary["unique_hosts"] = df["hostname"].nunique() if "hostname" in df.columns else 0
                return {
                    "data": [summary],
                    "count": 1,
                    "columns": list(summary.keys()),
                    "table": table,
                }
            else:
                return {"error": f"Unsupported method '{method}'. Use 'get' or 'summarize'."}
        except Exception as e:
            logger.error(f"Error querying SuzieQ parquet: {e}", exc_info=True)
            return {
                "error": f"Failed to query parquet: {str(e)}",
                "table": table,
                "method": method,
            }
    """
    # Parquet-only: always available if files exist
    
    tool_instance = _get_suzieq_tool()
    start = time.perf_counter()
    try:
        original_table = table
        if method == "path_show":
            table = "path"
        if method == "assert":
            method = "aver"
        # Parquet-only: no get_sqobject
        if method == "get":
            # Parquet-only: advanced methods not implemented
        elif method == "summarize":
            # Parquet-only: advanced methods not implemented
        elif method == "unique":
            # Parquet-only: advanced methods not implemented
        elif method == "aver":
            # Parquet-only: advanced methods not implemented
        elif method == "describe":
            raw_schema = tool_instance.schema.get_raw_schema(table)
            result = {
                "table": table,
                "description": raw_schema.get("description", ""),
                "fields": list(raw_schema.get("fields", {}).keys()),
                "primary_key": raw_schema.get("primary_key"),
                "methods": ["get", "summarize", "unique", "aver", "top", "describe", "lpm", "path_show", "assert"],
            }
        elif method == "top":
            sort_field = filters.pop("sort", None)
            limit = int(filters.pop("limit", 10))
            if not sort_field:
                raise ValueError("'top' requires 'sort' field name")
            # Parquet-only: advanced methods not implemented
            if hasattr(df, "sort_values"):
                df2 = df.sort_values(by=sort_field, ascending=False).head(limit)
                result = df2.to_dict(orient="records")
            else:
                result = {"error": "Result not sortable", "records": str(df)}
        elif method == "lpm":
            if original_table != "routes" and table != "routes":
                raise ValueError("'lpm' only valid for routes table")
            prefix = filters.pop("prefix", None)
            if not prefix:
                raise ValueError("'lpm' requires 'prefix' argument (IP address)")
            # Parquet-only: advanced methods not implemented
            matches = []
            ip = ipaddress.ip_address(prefix)
            if hasattr(df, "to_dict"):
                for row in df.to_dict(orient="records"):
                    net = row.get("prefix") or row.get("network")
                    if not net:
                        continue
                    try:
                        network = ipaddress.ip_network(net, strict=False)
                    except Exception:
                        continue
                    if ip in network:
                        matches.append((network.prefixlen, row))
                matches.sort(key=lambda x: x[0], reverse=True)
                result = [m[1] for m in matches[:1]] if matches else []
            else:
                result = []
        else:
            raise ValueError(f"Unsupported method: {method}")

        if hasattr(result, "to_dict"):
            payload = {"data": result.to_dict(orient="records"), "table": table, "method": method}
        elif isinstance(result, list):
            payload = {"data": result, "table": table, "method": method}
        else:
            payload = {"data": result, "table": table, "method": method}
        payload["__meta__"] = {"elapsed_sec": round(time.perf_counter() - start, 6)}
        return payload
    except Exception as e:
        logger.error(f"SuzieQ query failed: table={table}, method={method}, error={e}")
        return {"error": str(e), "table": table, "method": method, "__meta__": {"elapsed_sec": round(time.perf_counter() - start, 6)}}

