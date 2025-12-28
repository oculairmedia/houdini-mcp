"""Material and shader tools.

This module provides tools for creating, assigning, and inspecting
materials and shaders in Houdini.
"""

import logging
import traceback
from typing import Any, Dict, Optional

from ._common import (
    ensure_connected,
    HoudiniConnectionError,
    CONNECTION_ERRORS,
    _handle_connection_error,
    _add_response_metadata,
)

logger = logging.getLogger("houdini_mcp.tools.materials")


def create_material(
    material_type: str = "principledshader",
    name: Optional[str] = None,
    parent_path: str = "/mat",
    parameters: Optional[Dict[str, Any]] = None,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Create a new material/shader node.

    Creates a material node in the specified context (typically /mat or /shop).
    Supports common material types like Principled Shader, MaterialX, and classic shaders.

    Args:
        material_type: Type of material to create. Common types:
            - "principledshader": Houdini's standard PBR shader (recommended)
            - "mtlxstandard_surface": MaterialX Standard Surface
            - "classicshader": Classic Mantra shader
            - "arnold::standard_surface": Arnold Standard Surface (if Arnold installed)
        name: Optional name for the material. Auto-generated if not provided.
        parent_path: Parent context path (default: "/mat", alternative: "/shop")
        parameters: Optional dict of parameter values to set on the material.
            Common principledshader parameters:
            - basecolor: [r, g, b] base color
            - rough: float roughness (0-1)
            - metallic: float metallic (0-1)
            - ior: float index of refraction
            - basecolor_texture: string path to texture file

    Returns:
        Dict with:
        - status: "success" or "error"
        - material_path: Path to the created material node
        - material_name: Name of the material
        - material_type: Type of material created
        - parameters_set: List of parameters that were set

    Examples:
        create_material()  # Create default principled shader
        create_material("principledshader", "red_metal",
                       parameters={"basecolor": [1, 0, 0], "metallic": 1.0})
        create_material("mtlxstandard_surface", "gold_mtlx")
    """
    try:
        hou = ensure_connected(host, port)

        # Find or create parent context
        parent = hou.node(parent_path)
        if parent is None:
            # Try to create /mat if it doesn't exist
            if parent_path == "/mat":
                try:
                    parent = hou.node("/").createNode("matnet", "mat")
                except Exception:
                    return {
                        "status": "error",
                        "message": f"Cannot find or create material context: {parent_path}",
                    }
            else:
                return {
                    "status": "error",
                    "message": f"Parent context not found: {parent_path}",
                }

        # Generate name if not provided
        if not name:
            name = f"{material_type}_1"

        # Create the material node
        try:
            mat_node = parent.createNode(material_type, name)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create material of type '{material_type}': {str(e)}. "
                f"Check if this material type is available in your Houdini installation.",
            }

        # Set parameters if provided
        parameters_set = []
        if parameters:
            for param_name, value in parameters.items():
                try:
                    parm = mat_node.parm(param_name)
                    if parm:
                        parm.set(value)
                        parameters_set.append(param_name)
                    else:
                        # Try as tuple parameter
                        parm_tuple = mat_node.parmTuple(param_name)
                        if parm_tuple and isinstance(value, (list, tuple)):
                            parm_tuple.set(value)
                            parameters_set.append(param_name)
                        else:
                            logger.warning(
                                f"Parameter '{param_name}' not found on material {mat_node.path()}"
                            )
                except Exception as e:
                    logger.warning(f"Failed to set parameter '{param_name}': {e}")

        return {
            "status": "success",
            "material_path": mat_node.path(),
            "material_name": mat_node.name(),
            "material_type": material_type,
            "parameters_set": parameters_set,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "creating_material")
    except Exception as e:
        logger.error(f"Error creating material: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def assign_material(
    geometry_path: str,
    material_path: str,
    group: str = "",
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Assign a material to geometry.

    Creates a Material SOP inside the geometry node to apply the material.
    If a Material SOP already exists, updates it instead.

    Args:
        geometry_path: Path to the geometry OBJ node (e.g., "/obj/geo1")
        material_path: Path to the material node (e.g., "/mat/principledshader1")
        group: Optional primitive group to apply material to (empty = all primitives)

    Returns:
        Dict with:
        - status: "success" or "error"
        - geometry_path: Path to the geometry node
        - material_path: Path to the assigned material
        - material_sop_path: Path to the Material SOP that was created/modified
        - method: "material_sop" or "shop_materialpath"

    Examples:
        assign_material("/obj/geo1", "/mat/red_metal")
        assign_material("/obj/geo1", "/mat/gold", group="top_faces")
    """
    try:
        hou = ensure_connected(host, port)

        # Validate geometry node
        geo_node = hou.node(geometry_path)
        if geo_node is None:
            return {"status": "error", "message": f"Geometry node not found: {geometry_path}"}

        # Check if it's an OBJ-level geo node
        node_type = geo_node.type().name()
        node_category = geo_node.type().category().name()

        if node_category != "Object":
            return {
                "status": "error",
                "message": f"Node {geometry_path} is not an Object-level node. "
                f"Expected geo node, got {node_category}/{node_type}",
            }

        # Validate material exists
        mat_node = hou.node(material_path)
        if mat_node is None:
            return {"status": "error", "message": f"Material not found: {material_path}"}

        # Method 1: Try setting shop_materialpath on the OBJ node directly
        mat_parm = geo_node.parm("shop_materialpath")
        if mat_parm and not group:
            mat_parm.set(material_path)
            return {
                "status": "success",
                "geometry_path": geometry_path,
                "material_path": material_path,
                "method": "shop_materialpath",
            }

        # Method 2: Create/update Material SOP inside the geometry
        # Find the display node to connect to
        display_node = geo_node.displayNode()
        if display_node is None:
            # No display node, try to find any SOP
            children = geo_node.children()
            if not children:
                return {
                    "status": "error",
                    "message": f"Geometry node {geometry_path} has no SOP nodes inside",
                }
            display_node = children[-1]

        # Check if a material SOP already exists and is connected
        existing_mat_sop = None
        for child in geo_node.children():
            if child.type().name() == "material":
                existing_mat_sop = child
                break

        if existing_mat_sop:
            mat_sop = existing_mat_sop
        else:
            # Create new Material SOP
            mat_sop = geo_node.createNode("material", "material1")
            mat_sop.setFirstInput(display_node)
            mat_sop.setDisplayFlag(True)
            mat_sop.setRenderFlag(True)

        # Set material path
        mat_path_parm = mat_sop.parm("shop_materialpath1")
        if mat_path_parm:
            mat_path_parm.set(material_path)
        else:
            return {
                "status": "error",
                "message": "Cannot find shop_materialpath1 parameter on Material SOP",
            }

        # Set group if provided
        if group:
            group_parm = mat_sop.parm("group1")
            if group_parm:
                group_parm.set(group)

        return {
            "status": "success",
            "geometry_path": geometry_path,
            "material_path": material_path,
            "material_sop_path": mat_sop.path(),
            "method": "material_sop",
            "group": group if group else None,
        }

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "assigning_material")
    except Exception as e:
        logger.error(f"Error assigning material: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


def get_material_info(
    material_path: str,
    host: str = "localhost",
    port: int = 18811,
) -> Dict[str, Any]:
    """
    Get detailed information about a material node.

    Returns material type, parameters, and texture references.

    Args:
        material_path: Path to the material node (e.g., "/mat/principledshader1")

    Returns:
        Dict with:
        - status: "success" or "error"
        - material_path: Path to the material
        - material_name: Name of the material
        - material_type: Type of material (e.g., "principledshader")
        - parameters: Dict of parameter names to current values
        - textures: List of texture file references found in parameters

    Examples:
        get_material_info("/mat/principledshader1")
        get_material_info("/mat/mtlxstandard_surface1")
    """
    try:
        hou = ensure_connected(host, port)

        mat_node = hou.node(material_path)
        if mat_node is None:
            return {"status": "error", "message": f"Material not found: {material_path}"}

        # Get basic info
        result: Dict[str, Any] = {
            "status": "success",
            "material_path": mat_node.path(),
            "material_name": mat_node.name(),
            "material_type": mat_node.type().name(),
            "parameters": {},
            "textures": [],
        }

        # Common material parameter names to include
        common_params = [
            # Principled Shader
            "basecolor",
            "basecolor_texture",
            "rough",
            "rough_texture",
            "metallic",
            "metallic_texture",
            "ior",
            "reflect",
            "reflecttint",
            "coat",
            "coatrough",
            "transparency",
            "transcolor",
            "dispersion",
            "sss",
            "sssdist",
            "ssscolor",
            "sheen",
            "sheentint",
            "emitcolor",
            "emitint",
            "opac",
            "opaccolor",
            # Normal/Bump
            "baseBumpAndNormal_enable",
            "baseNormal_texture",
            "baseBump_bumpTexture",
            # MaterialX Standard Surface
            "base",
            "base_color",
            "diffuse_roughness",
            "specular",
            "specular_color",
            "specular_roughness",
            "specular_IOR",
            "transmission",
            "transmission_color",
            "subsurface",
            "subsurface_color",
            "emission",
            "emission_color",
        ]

        textures = []

        for parm_name in common_params:
            try:
                parm = mat_node.parm(parm_name)
                if parm:
                    value = parm.eval()
                    result["parameters"][parm_name] = value
                    # Check if it's a texture path
                    if isinstance(value, str) and value:
                        if any(
                            ext in value.lower()
                            for ext in [".jpg", ".png", ".exr", ".hdr", ".tif", ".tex"]
                        ):
                            textures.append({"parameter": parm_name, "path": value})
                else:
                    # Try as tuple
                    parm_tuple = mat_node.parmTuple(parm_name)
                    if parm_tuple:
                        value = parm_tuple.eval()
                        result["parameters"][parm_name] = (
                            list(value) if hasattr(value, "__iter__") else value
                        )
            except Exception:
                pass

        result["textures"] = textures
        result["parameter_count"] = len(result["parameters"])

        return _add_response_metadata(result)

    except HoudiniConnectionError as e:
        return {"status": "error", "message": str(e)}
    except CONNECTION_ERRORS as e:
        return _handle_connection_error(e, "getting_material_info")
    except Exception as e:
        logger.error(f"Error getting material info: {e}")
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
