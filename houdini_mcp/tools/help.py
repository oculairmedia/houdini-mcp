"""Houdini documentation fetching tool.

This module provides tools for fetching Houdini documentation from
the SideFX website. It does NOT require a Houdini connection.
"""

import logging
import traceback
from typing import Any, Dict, List

from ._common import _add_response_metadata

logger = logging.getLogger("houdini_mcp.tools.help")


def get_houdini_help(
    help_type: str,
    item_name: str,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Fetch Houdini documentation from SideFX website.

    Retrieves and parses help documentation for nodes, VEX functions,
    and Python API. Helps AI understand Houdini concepts without
    hallucinating parameter names or functionality.

    NOTE: This tool does NOT require a Houdini connection - it fetches
    documentation directly from the SideFX website.

    Args:
        help_type: Type of documentation to fetch. Supported types:
            - "sop": SOP nodes (e.g., "box", "scatter", "vdbfrompolygons")
            - "obj": Object nodes (e.g., "geo", "cam", "light")
            - "dop": DOP nodes (e.g., "pyrosolver", "rbdpackedobject")
            - "cop2": COP nodes (e.g., "mosaic", "blur")
            - "chop": CHOP nodes (e.g., "math", "wave")
            - "vop": VOP nodes (e.g., "bind", "noise")
            - "lop": LOP/Solaris nodes (e.g., "usdimport", "materiallibrary")
            - "top": TOP/PDG nodes (e.g., "pythonscript", "wedge")
            - "rop": ROP nodes (e.g., "geometry", "karma")
            - "vex_function": VEX functions (e.g., "noise", "lerp", "chramp")
            - "python_hou": Python hou module classes (e.g., "Node", "Geometry")
        item_name: Name of the node or function (e.g., "box", "noise", "Node")
        timeout: Request timeout in seconds (default: 10)

    Returns:
        Dict with:
        - status: "success" or "error"
        - title: Documentation title
        - url: Source URL
        - description: Summary description
        - parameters: List of parameters with names, descriptions, and options
        - inputs: List of input connections (for nodes)
        - outputs: List of output connections (for nodes)

    Examples:
        get_houdini_help("sop", "box")  # Get box SOP documentation
        get_houdini_help("vex_function", "noise")  # Get VEX noise function docs
        get_houdini_help("python_hou", "Node")  # Get hou.Node class docs
        get_houdini_help("obj", "cam")  # Get camera object docs
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return {
            "status": "error",
            "message": "Required packages not installed. Run: pip install requests beautifulsoup4",
        }

    base_url = "https://www.sidefx.com/docs/houdini/"

    # Map help types to URL paths
    url_mapping = {
        "obj": f"nodes/obj/{item_name}.html",
        "sop": f"nodes/sop/{item_name}.html",
        "dop": f"nodes/dop/{item_name}.html",
        "cop2": f"nodes/cop2/{item_name}.html",
        "chop": f"nodes/chop/{item_name}.html",
        "vop": f"nodes/vop/{item_name}.html",
        "lop": f"nodes/lop/{item_name}.html",
        "top": f"nodes/top/{item_name}.html",
        "rop": f"nodes/out/{item_name}.html",  # ROPs are under /out/
        "vex_function": f"vex/functions/{item_name}.html",
        "python_hou": f"hom/hou/{item_name}.html",
    }

    if help_type not in url_mapping:
        return {
            "status": "error",
            "message": f"Unsupported help type: {help_type}. "
            f"Supported types: {', '.join(sorted(url_mapping.keys()))}",
        }

    full_url = base_url + url_mapping[help_type]

    try:
        response = requests.get(full_url, timeout=timeout)

        if response.status_code == 404:
            return {
                "status": "error",
                "message": f"Documentation not found for {help_type}/{item_name}. "
                f"Check if the name is correct.",
                "url": full_url,
            }

        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"Failed to fetch help page. HTTP status: {response.status_code}",
                "url": full_url,
            }

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title
        h1 = soup.find("h1", class_="title")
        if h1:
            title_text = h1.contents[0].strip() if h1.contents else ""
            subtitle = h1.find("span", class_="subtitle")
            subtitle_text = subtitle.get_text(strip=True) if subtitle else ""
            title = f"{title_text} - {subtitle_text}" if subtitle_text else title_text
        else:
            title = item_name

        # Extract description/summary
        summary_p = soup.find("p", class_="summary")
        description = summary_p.get_text(strip=True) if summary_p else ""

        # Extract parameters
        parameters = []
        for param_div in soup.find_all("div", class_="parameter"):
            name_tag = param_div.find("p", class_="label")
            desc_tag = param_div.find("div", class_="content")

            if not name_tag:
                continue

            param_name = name_tag.get_text(strip=True)
            param_desc = ""
            if desc_tag:
                param_desc_p = desc_tag.find("p")
                param_desc = param_desc_p.get_text(strip=True) if param_desc_p else ""

            # Extract menu options if present
            options = []
            if desc_tag:
                defs = desc_tag.find("div", class_="defs")
                if defs:
                    for def_item in defs.find_all("div", class_="def"):
                        label = def_item.find("p", class_="label")
                        desc = def_item.find("div", class_="content")
                        if label:
                            option_name = label.get_text(strip=True)
                            option_desc = desc.get_text(strip=True) if desc else ""
                            options.append({"name": option_name, "description": option_desc})

            param_info: Dict[str, Any] = {
                "name": param_name,
                "description": param_desc,
            }
            if options:
                param_info["options"] = options

            parameters.append(param_info)

        # Helper to extract inputs/outputs sections
        def extract_section(section_id: str) -> List[Dict[str, str]]:
            items = []
            section_body = soup.find("div", id=f"{section_id}-body")
            if section_body:
                for def_item in section_body.find_all("div", class_="def"):
                    label = def_item.find("p", class_="label")
                    desc_div = def_item.find("div", class_="content")
                    if label:
                        items.append(
                            {
                                "name": label.get_text(strip=True),
                                "description": desc_div.get_text(strip=True) if desc_div else "",
                            }
                        )
            return items

        inputs = extract_section("inputs")
        outputs = extract_section("outputs")

        # For VEX functions, also extract signature and return type
        vex_info: Dict[str, Any] = {}
        if help_type == "vex_function":
            # Look for function signature
            sig_div = soup.find("div", class_="signature")
            if sig_div:
                vex_info["signature"] = sig_div.get_text(strip=True)

            # Look for return type in the body
            returns_section = soup.find("div", id="returns-body")
            if returns_section:
                vex_info["returns"] = returns_section.get_text(strip=True)

        # For Python hou module, extract methods
        methods: List[Dict[str, str]] = []
        if help_type == "python_hou":
            for method_div in soup.find_all("div", class_="method"):
                method_name_tag = method_div.find("p", class_="label")
                method_desc_tag = method_div.find("div", class_="content")
                if method_name_tag:
                    methods.append(
                        {
                            "name": method_name_tag.get_text(strip=True),
                            "description": (
                                method_desc_tag.get_text(strip=True)[:200] + "..."
                                if method_desc_tag
                                and len(method_desc_tag.get_text(strip=True)) > 200
                                else method_desc_tag.get_text(strip=True)
                                if method_desc_tag
                                else ""
                            ),
                        }
                    )

        result: Dict[str, Any] = {
            "status": "success",
            "title": title,
            "url": full_url,
            "help_type": help_type,
            "item_name": item_name,
            "description": description,
        }

        if parameters:
            result["parameters"] = parameters
            result["parameter_count"] = len(parameters)

        if inputs:
            result["inputs"] = inputs

        if outputs:
            result["outputs"] = outputs

        if vex_info:
            result["vex_info"] = vex_info

        if methods:
            result["methods"] = methods[:50]  # Limit to first 50 methods
            result["method_count"] = len(methods)
            if len(methods) > 50:
                result["methods_truncated"] = True

        return _add_response_metadata(result)

    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": f"Request timed out after {timeout} seconds",
            "url": full_url,
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Network error: {str(e)}",
            "url": full_url,
        }
    except Exception as e:
        logger.error(f"Error fetching Houdini help: {e}")
        return {
            "status": "error",
            "message": str(e),
            "url": full_url,
            "traceback": traceback.format_exc(),
        }
