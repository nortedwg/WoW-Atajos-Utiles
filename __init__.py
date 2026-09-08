bl_info = {
    "name": "Atajos Útiles",
    "author": "Norte",
    "version": (3, 4),
    "blender": (3, 4, 0),
    "location": "Menu Vertical",
    "description": "Herramientas de materiales, UVs, atajos de transformación y texturas WMO",
    "category": "World of Warcraft",
}

import bpy
import os
import re
import json
import shutil
import sqlite3
from math import radians
import heapq
from mathutils import Matrix, Vector

addon_keymaps = []
texture_index_stats_cache = None


# =====================================================
# BASE DE DATOS
# =====================================================

def get_desktop():
    if os.name == 'nt':  # Windows
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            desktop, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            return desktop
        except Exception:
            pass
    # Fallback para Mac/Linux (o si falla el registro)
    return os.path.join(os.path.expanduser("~"), "Desktop")

def get_db_path():
    return os.path.join(os.path.dirname(__file__), "WMO_Listado_de_Materiales.json")

def get_texture_index_path():
    return os.path.join(os.path.dirname(__file__), "WMO_Textures.sqlite")

def get_texture_preferences_path():
    return os.path.join(os.path.dirname(__file__), "WMO_Texture_Preferences.json")

def get_default_database():
    return {
        "CUSTOM": {
            "CUSTOM_PiedraHD_Shadowfang": "creature/singleturret/6ih_ironhorde_supertank_moveg.blp"
        },
        "GENERAL": [
            "dungeons/textures/6hu_garrison/6hu_garrison_strmwnd_wall_03.blp",
            "tileset/expansion07/general/8war_grass03_1024.blp"
        ]
    }

def normalize_database(data):
    if not isinstance(data, dict):
        data = get_default_database()

    custom = data.get("CUSTOM", {})
    general = data.get("GENERAL", [])

    if not isinstance(custom, dict):
        custom = {}
    if not isinstance(general, list):
        general = []

    return {
        "CUSTOM": dict(custom),
        "GENERAL": list(general)
    }

def load_base_database():
    path = get_db_path()
    if not os.path.exists(path):
        return get_default_database()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return normalize_database(json.load(f))
    except:
        return get_default_database()

def merge_custom_json_data(data, custom_data):
    if not isinstance(custom_data, dict):
        return

    if "CUSTOM" not in custom_data and "GENERAL" not in custom_data:
        data["CUSTOM"].update(custom_data)
        return

    custom = custom_data.get("CUSTOM", {})
    general = custom_data.get("GENERAL", [])

    if isinstance(custom, dict):
        data["CUSTOM"].update(custom)
    if isinstance(general, list):
        for entry in general:
            if entry not in data["GENERAL"]:
                data["GENERAL"].append(entry)

def load_database():
    data = load_base_database()

    # Fusionar los JSON Customs activos
    config = load_json_config()
    customs_dir = get_json_customs_dir()
    for fname in get_custom_json_files():
        if config.get(fname, True):  # por defecto activo
            fpath = os.path.join(customs_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    merge_custom_json_data(data, json.load(f))
            except:
                pass
    return data

def save_database(data):
    path = get_db_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(normalize_database(data), f, indent=4)

def to_storage_path(path):
    return (path or "").strip().replace('\\', '/')

def to_blender_wow_path(path):
    return to_storage_path(path).replace('/', '\\')

def clean_lookup_name(value):
    name = (value or "").strip()
    name = re.sub(r"\.\d{3}$", "", name)
    lower_name = name.lower()
    for ext in ('.blp', '.png', '.jpg', '.jpeg', '.tga', '.dds', '.webp', '.bmp', '.tif', '.tiff'):
        if lower_name.endswith(ext):
            name = name[:-len(ext)]
            break
    return name.strip().lower()

def path_to_lookup_name(path):
    clean_path = to_storage_path(path)
    filename = clean_path.rsplit('/', 1)[-1]
    return clean_lookup_name(filename)


# =====================================================
# GESTIÓN DE JSON CUSTOMS
# =====================================================

def get_json_customs_dir():
    return os.path.join(os.path.dirname(__file__), "JSON Customs")

def get_json_config_path():
    return os.path.join(get_json_customs_dir(), "_config.json")

def load_json_config():
    """Devuelve {filename: bool} — True = activo"""
    config_path = get_json_config_path()
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_json_config(config):
    os.makedirs(get_json_customs_dir(), exist_ok=True)
    with open(get_json_config_path(), 'w') as f:
        json.dump(config, f, indent=4)

def get_custom_json_files():
    """Devuelve lista de archivos .json (excluyendo _config.json)"""
    d = get_json_customs_dir()
    if not os.path.exists(d):
        return []
    return sorted([f for f in os.listdir(d) if f.endswith('.json') and f != '_config.json'])

def get_json_save_items(self, context):
    items = [
        ("__MAIN__", "Base principal", "Guardar en WMO_Listado_de_Materiales.json")
    ]
    for fname in get_custom_json_files():
        items.append((fname, fname, "Guardar en este JSON Custom"))
    items.append(("__NEW__", "Crear nuevo JSON", "Crear un JSON Custom nuevo"))
    return items

def sanitize_json_filename(name):
    filename = (name or "").strip()
    if not filename:
        return None
    if not filename.lower().endswith(".json"):
        filename += ".json"
    filename = os.path.basename(filename)
    filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip(" .")
    if not filename or filename == "_config.json":
        return None
    return filename

def load_custom_json_file(filename):
    path = os.path.join(get_json_customs_dir(), filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except:
        return {}

def save_custom_json_file(filename, data):
    os.makedirs(get_json_customs_dir(), exist_ok=True)
    path = os.path.join(get_json_customs_dir(), filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def enable_custom_json(filename):
    config = load_json_config()
    config[filename] = True
    save_json_config(config)

def save_texture_entry_to_target(target, new_json_name, mat_name, wow_path):
    mat_name = (mat_name or "").strip()
    wow_path = to_storage_path(wow_path)

    if target == "__NEW__":
        filename = sanitize_json_filename(new_json_name)
        if not filename:
            return None, "Nombre de JSON no valido"
        target = filename

    if target == "__MAIN__" or not target:
        data = load_base_database()
        if mat_name:
            data["CUSTOM"][mat_name] = wow_path
        elif wow_path not in data["GENERAL"]:
            data["GENERAL"].append(wow_path)
        save_database(data)
        return "Base principal", None

    filename = sanitize_json_filename(target)
    if not filename:
        return None, "JSON destino no valido"

    data = load_custom_json_file(filename)
    if "CUSTOM" not in data and "GENERAL" not in data:
        if mat_name:
            data[mat_name] = wow_path
        else:
            data = {
                "CUSTOM": data,
                "GENERAL": [wow_path]
            }
    else:
        custom = data.setdefault("CUSTOM", {})
        general = data.setdefault("GENERAL", [])
        if not isinstance(custom, dict):
            data["CUSTOM"] = {}
        if not isinstance(general, list):
            data["GENERAL"] = []

        if mat_name:
            data["CUSTOM"][mat_name] = wow_path
        elif wow_path not in data["GENERAL"]:
            data["GENERAL"].append(wow_path)

    save_custom_json_file(filename, data)
    enable_custom_json(filename)
    return filename, None

def load_texture_preferences():
    path = get_texture_preferences_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            prefs = json.load(f)
        if not isinstance(prefs, dict):
            return {}
        return {
            clean_lookup_name(name): to_storage_path(path)
            for name, path in prefs.items()
            if clean_lookup_name(name) and to_storage_path(path)
        }
    except:
        return {}

def save_texture_preferences(prefs):
    path = get_texture_preferences_path()
    clean_prefs = {
        clean_lookup_name(name): to_storage_path(path)
        for name, path in prefs.items()
        if clean_lookup_name(name) and to_storage_path(path)
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(clean_prefs.items())), f, indent=4)

def set_texture_preference(name, wow_path):
    prefs = load_texture_preferences()
    prefs[clean_lookup_name(name)] = to_storage_path(wow_path)
    save_texture_preferences(prefs)

def get_texture_index_stats():
    global texture_index_stats_cache
    db_path = get_texture_index_path()
    if not os.path.exists(db_path):
        texture_index_stats_cache = None
        return {"available": False, "textures": 0, "names": 0}
    try:
        mtime = os.path.getmtime(db_path)
    except:
        mtime = 0

    if texture_index_stats_cache and texture_index_stats_cache.get("mtime") == mtime:
        return texture_index_stats_cache["stats"]

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            textures = int(meta.get("texture_count", "0"))
            names = int(meta.get("name_count", "0"))
            if not textures or not names:
                textures = conn.execute("SELECT COUNT(*) FROM textures").fetchone()[0]
                names = conn.execute("SELECT COUNT(DISTINCT name) FROM textures").fetchone()[0]
        finally:
            conn.close()
        stats = {"available": True, "textures": textures, "names": names}
        texture_index_stats_cache = {"mtime": mtime, "stats": stats}
        return stats
    except:
        texture_index_stats_cache = None
        return {"available": False, "textures": 0, "names": 0}

def query_texture_index(names):
    result = {name: [] for name in names}
    db_path = get_texture_index_path()
    if not names or not os.path.exists(db_path):
        return result

    ordered_names = sorted(set(name for name in names if name))
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for i in range(0, len(ordered_names), 800):
                chunk = ordered_names[i:i + 800]
                marks = ",".join("?" for _ in chunk)
                query = (
                    "SELECT name, filedata_id, path "
                    f"FROM textures WHERE name IN ({marks}) "
                    "ORDER BY name, path"
                )
                for row in conn.execute(query, chunk):
                    result.setdefault(row["name"], []).append({
                        "filedata_id": row["filedata_id"],
                        "path": row["path"],
                        "source": "SQLite"
                    })
        finally:
            conn.close()
    except Exception as e:
        print(f"WMO texture index error: {e}")
    return result

def get_custom_map(data):
    custom_map = {}
    for name, path in data.get("CUSTOM", {}).items():
        lookup_name = clean_lookup_name(name)
        if lookup_name and path:
            custom_map[lookup_name] = to_storage_path(path)
    return custom_map

def get_general_candidates(data):
    candidates = {}
    for path in data.get("GENERAL", []):
        clean_path = to_storage_path(path)
        lookup_name = path_to_lookup_name(clean_path)
        if lookup_name and clean_path:
            candidates.setdefault(lookup_name, []).append({
                "filedata_id": "",
                "path": clean_path,
                "source": "JSON"
            })
    return candidates

def dedupe_candidates(candidates):
    result = []
    seen = set()
    for candidate in candidates:
        path = to_storage_path(candidate.get("path", ""))
        if not path:
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "filedata_id": candidate.get("filedata_id", ""),
            "path": path,
            "source": candidate.get("source", "")
        })
    return result

def build_image_map():
    image_map = {}
    for img in bpy.data.images:
        lookup_name = clean_lookup_name(img.name)
        if lookup_name and lookup_name not in image_map:
            image_map[lookup_name] = img
    return image_map

def assign_wmo_path_to_materials(materials, lookup_name, wow_path, image_map=None):
    image_map = image_map or build_image_map()
    assigned = 0
    paths_filled = 0
    missing_images = 0

    for mat in materials:
        if not hasattr(mat, "wow_wmo_material"):
            continue

        target_image = image_map.get(lookup_name)
        if target_image:
            mat.wow_wmo_material.diff_texture_1 = target_image
        else:
            target_image = getattr(mat.wow_wmo_material, "diff_texture_1", None)

        if target_image:
            assigned += 1
            if hasattr(target_image, "wow_wmo_texture"):
                target_image.wow_wmo_texture.path = to_blender_wow_path(wow_path)
                paths_filled += 1
        else:
            missing_images += 1

    return assigned, paths_filled, missing_images

def refresh_texture_candidate_list(scene):
    scene.wmo_texture_candidates.clear()
    if not scene.wmo_texture_conflicts:
        scene.wmo_texture_candidate_index = 0
        return

    index = max(0, min(scene.wmo_texture_conflict_index, len(scene.wmo_texture_conflicts) - 1))
    if scene.wmo_texture_conflict_index != index:
        scene.wmo_texture_conflict_index = index
        return
    conflict = scene.wmo_texture_conflicts[index]
    try:
        candidates = json.loads(conflict.candidates_json)
    except:
        candidates = []

    for candidate in candidates:
        item = scene.wmo_texture_candidates.add()
        item.filedata_id = str(candidate.get("filedata_id", ""))
        item.path = to_storage_path(candidate.get("path", ""))
        item.source = candidate.get("source", "")

    scene.wmo_texture_candidate_index = 0

def update_wmo_conflict_index(self, context):
    if context and context.scene:
        refresh_texture_candidate_list(context.scene)
        _on_wmo_report_index(context, self.wmo_texture_conflicts, self.wmo_texture_conflict_index)

def clear_texture_conflicts(scene):
    scene.wmo_texture_conflicts.clear()
    scene.wmo_texture_candidates.clear()
    scene.wmo_texture_conflict_index = 0
    scene.wmo_texture_candidate_index = 0
    # Control de Texturas: limpiar informes por categoría
    if hasattr(scene, "wmo_texture_ok"):
        scene.wmo_texture_ok.clear()
    if hasattr(scene, "wmo_texture_notfound"):
        scene.wmo_texture_notfound.clear()
    if hasattr(scene, "wmo_texture_noimage"):
        scene.wmo_texture_noimage.clear()
    if hasattr(scene, "wmo_texture_ok_index"):
        scene.wmo_texture_ok_index = 0
    if hasattr(scene, "wmo_texture_notfound_index"):
        scene.wmo_texture_notfound_index = 0
    if hasattr(scene, "wmo_texture_noimage_index"):
        scene.wmo_texture_noimage_index = 0

def add_texture_conflict(scene, lookup_name, material_count, candidates):
    candidates = dedupe_candidates(candidates)
    if not candidates:
        return False
    item = scene.wmo_texture_conflicts.add()
    item.material_name = lookup_name
    item.material_count = material_count
    item.option_count = len(candidates)
    item.candidates_json = json.dumps(candidates)
    return True

def add_texture_report_item(collection, lookup_name, material_count, detail=""):
    item = collection.add()
    item.material_name = lookup_name
    item.material_count = material_count
    item.detail = detail or ""
    return item

def select_wmo_report_entry(context, lookup_name):
    """Selecciona un objeto que use el material 'lookup_name' y activa ese material.
    Devuelve (obj_name, mat_name) o (None, None) si no se encuentra."""
    scene = context.scene if context else None
    if scene is None or not lookup_name:
        return None, None

    lookup_clean = clean_lookup_name(lookup_name)
    mats = [m for m in bpy.data.materials if clean_lookup_name(m.name) == lookup_clean]
    if not mats:
        mats = [m for m in bpy.data.materials if m.name == lookup_name]
    if not mats:
        return None, None

    # Buscar objeto que use alguno de esos materiales (priorizar visibles)
    candidates = []
    for mat in mats:
        for obj in scene.objects:
            if not hasattr(obj, "material_slots"):
                continue
            for slot_idx, slot in enumerate(obj.material_slots):
                if slot.material == mat:
                    visible = (not getattr(obj, "hide_viewport", False))
                    try:
                        visible = visible and obj.visible_get()
                    except:
                        pass
                    candidates.append((0 if visible else 1, obj, mat, slot_idx))
                    break

    if not candidates:
        return None, None

    candidates.sort(key=lambda c: c[0])
    _, target_obj, target_mat, target_slot = candidates[0]

    try:
        if context.mode != 'OBJECT':
            return target_obj.name, target_mat.name
    except:
        pass

    try:
        for o in list(context.selected_objects):
            try:
                o.select_set(False)
            except:
                pass
        try:
            target_obj.select_set(True)
        except:
            pass
        try:
            context.view_layer.objects.active = target_obj
        except:
            pass
        try:
            if 0 <= target_slot < len(target_obj.material_slots):
                target_obj.active_material_index = target_slot
        except:
            pass
    except Exception as e:
        print(f"WMO select report error: {e}")
        return target_obj.name, target_mat.name

    return target_obj.name, target_mat.name

def _on_wmo_report_index(context, collection, index):
    try:
        if context is None or context.scene is None:
            return
        # Evitar actuar durante limpieza (colección vacía)
        if not collection or len(collection) == 0:
            return
        if index < 0 or index >= len(collection):
            return
        lookup_name = collection[index].material_name
        if lookup_name:
            select_wmo_report_entry(context, lookup_name)
    except Exception as e:
        print(f"WMO report select error: {e}")

def update_wmo_report_ok_index(self, context):
    _on_wmo_report_index(context, self.wmo_texture_ok, self.wmo_texture_ok_index)

def update_wmo_report_notfound_index(self, context):
    _on_wmo_report_index(context, self.wmo_texture_notfound, self.wmo_texture_notfound_index)

def update_wmo_report_noimage_index(self, context):
    _on_wmo_report_index(context, self.wmo_texture_noimage, self.wmo_texture_noimage_index)


# =====================================================
# BAKEAR – helpers (tamano potencia de 2 + ruta)
# =====================================================

WOW_BAKE_SIZES = (256, 512, 1024, 2048, 4096, 8192)
_wow_bake_prev_size = 2048


def update_wow_bake_size(self, context):
    """Fuerza que el tamano sea siempre potencia de 2.

    Las flechas del campo Int suben/bajan de 1 en 1, asi que aqui se salta
    a la siguiente potencia en la direccion del cambio. Si se escribe el
    numero a mano, se ajusta a la potencia mas cercana.
    """
    global _wow_bake_prev_size
    try:
        current = int(self.wow_bake_size)
    except Exception:
        return

    if current in WOW_BAKE_SIZES:
        _wow_bake_prev_size = current
        return

    nearest = min(WOW_BAKE_SIZES, key=lambda s: (abs(s - current), s))
    # Salto pequeno (flechas, paso 1): ir a la siguiente potencia en esa direccion.
    # Salto grande (numero escrito a mano): quedarse con la mas cercana.
    if abs(current - nearest) <= 1:
        if current > nearest:
            mayores = [s for s in WOW_BAKE_SIZES if s > nearest]
            snapped = min(mayores) if mayores else WOW_BAKE_SIZES[-1]
        else:
            menores = [s for s in WOW_BAKE_SIZES if s < nearest]
            snapped = max(menores) if menores else WOW_BAKE_SIZES[0]
    else:
        snapped = nearest

    _wow_bake_prev_size = snapped
    # Asignacion por diccionario para no re-disparar el update en bucle.
    try:
        self["wow_bake_size"] = snapped
    except Exception:
        pass


# =====================================================
# PROPIEDADES
# =====================================================

class WMO_Addon_Props(bpy.types.PropertyGroup):
    new_mat_name: bpy.props.StringProperty(
        name="Nombre Material",
        description="Nombre en Blender (Solo añadir si el material es custom. Dejar vacío si es del propio WoW)"
    )
    new_wow_path: bpy.props.StringProperty(
        name="Ruta WoW",
        description="Ruta completa al .blp"
    )
    save_json_target: bpy.props.EnumProperty(
        name="Guardar en",
        description="JSON donde se guardara esta textura",
        items=get_json_save_items
    )
    new_json_name: bpy.props.StringProperty(
        name="Nuevo JSON",
        description="Nombre del JSON Custom nuevo"
    )

class WMO_TextureConflictItem(bpy.types.PropertyGroup):
    material_name: bpy.props.StringProperty()
    material_count: bpy.props.IntProperty(default=0)
    option_count: bpy.props.IntProperty(default=0)
    candidates_json: bpy.props.StringProperty()

class WMO_TextureCandidateItem(bpy.types.PropertyGroup):
    filedata_id: bpy.props.StringProperty()
    path: bpy.props.StringProperty()
    source: bpy.props.StringProperty()

class WMO_TextureReportItem(bpy.types.PropertyGroup):
    material_name: bpy.props.StringProperty()
    material_count: bpy.props.IntProperty(default=0)
    detail: bpy.props.StringProperty()

class WMO_UL_texture_conflicts(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.material_name, icon='ERROR')
        row.label(text=f"{item.option_count} opciones")

class WMO_UL_texture_candidates(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        label_id = item.filedata_id if item.filedata_id else "-"
        row.label(text=label_id, icon='TEXT')
        row.label(text=item.path)

class WMO_UL_texture_report(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.material_name, icon='MATERIAL')
        if item.material_count > 1:
            row.label(text=f"x{item.material_count}")
        if item.detail:
            row.label(text=item.detail)


# =====================================================
# OPERADOR 1 – Materiales opacos
# =====================================================

class MATERIAL_OT_opacos(bpy.types.Operator):
    bl_idname = "material.materiales_opacos"
    bl_label = "¿Tu material se transparenta? Arreglar"
    bl_description = "Cambia todos los materiales a OPAQUE"

    def execute(self, context):
        count = 0
        for mat in bpy.data.materials:
            if mat and mat.use_nodes:
                if mat.blend_method != 'OPAQUE':
                    mat.blend_method = 'OPAQUE'
                    count += 1
        self.report({'INFO'}, f"Materiales cambiados a OPAQUE: {count}")
        return {'FINISHED'}


# =====================================================
# OPERADOR 2 – Materiales sin brillo
# =====================================================

class MATERIAL_OT_sin_brillo(bpy.types.Operator):
    bl_idname = "material.materiales_sin_brillo"
    bl_label = "Materiales sin brillo, como en el WoW"
    bl_description = "Quita brillo a todos los Principled BSDF"

    def execute(self, context):
        for mat in bpy.data.materials:
            if mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        node.inputs['Specular'].default_value = 0.0
                        node.inputs['Roughness'].default_value = 1.0
                        node.inputs['Specular Tint'].default_value = 0.0
                        node.inputs['Metallic'].default_value = 0.0
        return {'FINISHED'}


# =====================================================
# OPERADOR 3 – Renombrar UVMap
# =====================================================

class OBJECT_OT_renombrar_uv(bpy.types.Operator):
    bl_idname = "object.renombrar_uvmap"
    bl_label = "Renombrar todas las UV a UVMap"
    bl_description = "Renombra todas las UVs a UVMap"

    def execute(self, context):
        new_name = "UVMap"
        total_objs = 0
        total_uvs = 0
        sin_uv = []

        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                total_objs += 1
                uvl = obj.data.uv_layers
                if not uvl:
                    sin_uv.append(obj.name)
                    continue
                for uv in uvl:
                    uv.name = new_name
                    total_uvs += 1

        def draw(self, context):
            self.layout.label(text=f"Objetos procesados: {total_objs}")
            self.layout.label(text=f"UV maps renombradas: {total_uvs}")
            if sin_uv:
                self.layout.label(text=f"Sin UVs: {', '.join(sin_uv[:5])}...")
                self.layout.label(text=f"({len(sin_uv)} objetos sin UVs)")

        context.window_manager.popup_menu(
            draw,
            title="Renombrado UVs completado ✅",
            icon='INFO'
        )
        return {'FINISHED'}


# =====================================================
# OPERADOR 3b – Renombrar UVMap a Texture
# =====================================================

class OBJECT_OT_renombrar_uv_texture(bpy.types.Operator):
    bl_idname = "object.renombrar_uvmap_texture"
    bl_label = "Renombrar todas las UV a Texture"
    bl_description = "Renombra todas las UVs a Texture"

    def execute(self, context):
        new_name = "Texture"
        total_objs = 0
        total_uvs = 0
        sin_uv = []

        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                total_objs += 1
                uvl = obj.data.uv_layers
                if not uvl:
                    sin_uv.append(obj.name)
                    continue
                for uv in uvl:
                    uv.name = new_name
                    total_uvs += 1

        def draw(self, context):
            self.layout.label(text=f"Objetos procesados: {total_objs}")
            self.layout.label(text=f"UV maps renombradas: {total_uvs}")
            if sin_uv:
                self.layout.label(text=f"Sin UVs: {', '.join(sin_uv[:5])}...")
                self.layout.label(text=f"({len(sin_uv)} objetos sin UVs)")

        context.window_manager.popup_menu(
            draw,
            title="Renombrado UVs a Texture ✅",
            icon='INFO'
        )
        return {'FINISHED'}


# =====================================================
# OPERADOR 4 – Quitar prefijo mat_
# =====================================================

class MATERIAL_OT_quitar_prefijo(bpy.types.Operator):
    bl_idname = "material.quitar_prefijo_mat"
    bl_label = "Quitar prefijo mat_ de los materiales"
    bl_description = "Elimina el prefijo 'mat_' del nombre de todos los materiales."

    def execute(self, context):
        PREFIX = "mat_"
        count = 0
        for mat in bpy.data.materials:
            if mat.name.startswith(PREFIX):
                mat.name = mat.name[len(PREFIX):]
                count += 1
        self.report({'INFO'}, f"Materiales renombrados: {count}")
        return {'FINISHED'}


# =====================================================
# OPERADOR 5 – Nombre según textura
# =====================================================

class MATERIAL_OT_nombre_por_textura(bpy.types.Operator):
    bl_idname = "material.nombre_por_textura"
    bl_label = "Nombrar material como su Imagen"
    bl_description = "Renombra todos los materiales según su textura (sin extensión)."

    def execute(self, context):
        count = 0
        for mat in bpy.data.materials:
            if not mat.use_nodes:
                continue

            nodes = mat.node_tree.nodes
            target_image = None

            # 1) Nodo conectado al Base Color del Principled BSDF (la textura principal)
            bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                base_color_input = bsdf.inputs.get('Base Color')
                if base_color_input and base_color_input.is_linked:
                    from_node = base_color_input.links[0].from_node
                    if from_node.type == 'TEX_IMAGE' and from_node.image:
                        target_image = from_node.image

            # 2) Fallback: primer TEX_IMAGE con filepath real (no incrustado/packed)
            if not target_image:
                for node in nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        if node.image.filepath:
                            target_image = node.image
                            break

            # 3) Fallback final: cualquier TEX_IMAGE con imagen
            if not target_image:
                for node in nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        target_image = node.image
                        break

            if not target_image:
                continue

            filepath = target_image.filepath
            filename = os.path.basename(filepath)
            name_without_ext = os.path.splitext(filename)[0]
            # Fallback: imagen empaquetada o sin filepath → usar image.name
            if not name_without_ext:
                name_without_ext = os.path.splitext(target_image.name)[0]
            if name_without_ext:
                mat.name = name_without_ext
                count += 1

        self.report({'INFO'}, f"Materiales renombrados por textura: {count}")
        return {'FINISHED'}


# =====================================================
# OPERADOR 6 – Eliminar .001 .002 etc de materiales
# =====================================================

class MATERIAL_OT_eliminar_duplicados(bpy.types.Operator):
    bl_idname = "material.eliminar_duplicados_001"
    bl_label = "Eliminar los .001 de los materiales"
    bl_description = "Unifica materiales con sufijos .001/.002/etc y elimina duplicados"

    def execute(self, context):
        pattern = re.compile(r"^(.*)\.(\d+)$")
        groups = {}

        for mat in bpy.data.materials:
            match = pattern.match(mat.name)
            if match:
                base_name = match.group(1)
                number = int(match.group(2))
                groups.setdefault(base_name, []).append((number, mat))

        total_removed = 0

        for base_name, mats in groups.items():
            base_material = bpy.data.materials.get(base_name)

            if base_material is None:
                mats.sort(key=lambda x: x[0])
                lowest_number, lowest_mat = mats.pop(0)
                lowest_mat.name = base_name
                base_material = lowest_mat

            for number, mat in mats:
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material == mat:
                                slot.material = base_material
                bpy.data.materials.remove(mat, do_unlink=True)
                total_removed += 1

        self.report({'INFO'}, f"Materiales duplicados eliminados: {total_removed}")
        return {'FINISHED'}


# =====================================================
# OPERADOR 6b – Unir mats de nombres repetidos
# =====================================================

class MATERIAL_OT_unir_mats_repetidos(bpy.types.Operator):
    bl_idname = "material.unir_mats_repetidos"
    bl_label = "Unir materiales de nombres repetidos"
    bl_description = "Si dos materiales o más tienen el mismo nombre, los unifica en uno solo."

    def execute(self, context):
        # Diccionario: nombre del material -> material que se conservará
        materiales_unicos = {}

        # ---------------------------------------------------------
        # 1. Recorrer todos los materiales y decidir cuál conservar
        # ---------------------------------------------------------
        for mat in bpy.data.materials:
            if mat.name not in materiales_unicos:
                materiales_unicos[mat.name] = mat

        # ---------------------------------------------------------
        # 2. Reasignar los slots de materiales de los objetos
        # ---------------------------------------------------------
        for obj in context.scene.objects:
            # Solo nos interesan objetos que tengan materiales
            if not hasattr(obj.data, "materials"):
                continue

            if not obj.data.materials:
                continue

            # Crear mapa de los slots actuales:
            # índice original -> material único
            nuevos_materiales = []

            for mat in obj.data.materials:
                if mat is None:
                    nuevos_materiales.append(None)
                    continue

                material_unico = materiales_unicos[mat.name]
                nuevos_materiales.append(material_unico)

            # -----------------------------------------------------
            # Reasignar los materiales a las caras
            # -----------------------------------------------------
            # Guardamos qué material tenía cada índice original
            materiales_originales = list(obj.data.materials)

            if hasattr(obj.data, "polygons"):
                for poly in obj.data.polygons:
                    indice_original = poly.material_index

                    if indice_original >= len(materiales_originales):
                        continue

                    mat_original = materiales_originales[indice_original]

                    if mat_original is None:
                        continue

                    mat_unico = materiales_unicos[mat_original.name]

                    # Buscar el índice del material único dentro
                    # de los slots del objeto
                    try:
                        nuevo_indice = nuevos_materiales.index(mat_unico)
                    except ValueError:
                        # No debería ocurrir, pero por seguridad
                        nuevo_indice = 0

                    poly.material_index = nuevo_indice

            # -----------------------------------------------------
            # Eliminar slots duplicados del objeto
            # -----------------------------------------------------
            # Reconstruimos completamente los slots para que
            # cada material aparezca una sola vez.
            materiales_objeto_unicos = []

            for mat in nuevos_materiales:
                if mat is not None and mat not in materiales_objeto_unicos:
                    materiales_objeto_unicos.append(mat)

            # Guardar material de cada cara antes de borrar slots
            materiales_de_caras = []

            if hasattr(obj.data, "polygons"):
                for poly in obj.data.polygons:
                    indice = poly.material_index

                    if indice < len(nuevos_materiales):
                        materiales_de_caras.append(nuevos_materiales[indice])
                    else:
                        materiales_de_caras.append(None)

            # Limpiar slots
            obj.data.materials.clear()

            # Añadir únicamente los materiales únicos
            for mat in materiales_objeto_unicos:
                obj.data.materials.append(mat)

            # Restaurar índices de las caras
            if hasattr(obj.data, "polygons"):
                for poly, mat in zip(obj.data.polygons, materiales_de_caras):
                    if mat is None:
                        poly.material_index = 0
                        continue

                    try:
                        poly.material_index = materiales_objeto_unicos.index(mat)
                    except ValueError:
                        poly.material_index = 0

        # ---------------------------------------------------------
        # 3. Eliminar materiales duplicados de Blender
        # ---------------------------------------------------------
        materiales_a_borrar = []

        for mat in bpy.data.materials:
            material_unico = materiales_unicos.get(mat.name)

            if material_unico is not None and mat != material_unico:
                materiales_a_borrar.append(mat)

        for mat in materiales_a_borrar:
            bpy.data.materials.remove(mat)

        print("==========================================")
        print(" LIMPIEZA DE MATERIALES COMPLETADA")
        print("==========================================")
        print("Materiales únicos:", len(materiales_unicos))
        print("Duplicados eliminados:", len(materiales_a_borrar))

        self.report({'INFO'}, f"Materiales únicos: {len(materiales_unicos)} | Duplicados eliminados: {len(materiales_a_borrar)}")
        return {'FINISHED'}


# =====================================================
# OPERADOR 7 – Rellenar Texturas WMO
# =====================================================

class MATERIAL_OT_wbs_full_auto_custom(bpy.types.Operator):
    bl_idname = "material.wbs_full_auto_custom"
    bl_label = "Rellenar Texturas WMO"
    bl_description = "Asigna texturas WoW por nombre usando JSON Custom y el indice SQLite."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        clear_texture_conflicts(scene)

        data = load_database()
        custom_map = get_custom_map(data)
        general_candidates = get_general_candidates(data)
        preferences = load_texture_preferences()
        image_map = build_image_map()

        materials_by_name = {}
        for mat in bpy.data.materials:
            if not hasattr(mat, "wow_wmo_material"):
                continue
            lookup_name = clean_lookup_name(mat.name)
            if lookup_name:
                materials_by_name.setdefault(lookup_name, []).append(mat)

        # Materiales usados de verdad en geometria.
        # Solo cuenta si el material esta asignado a al menos una cara de un
        # MESH (o al slot en otros tipos). Los que solo estan en slots sin
        # caras, o huerfanos sin objeto, se ignoran en "Sin encontrar".
        # Se compara por as_pointer() porque los wrappers RNA de Blender
        # pueden ser objetos Python distintos para el mismo datablock.
        used_mat_pointers = set()

        def _remember_mat(m):
            if m is None:
                return
            try:
                used_mat_pointers.add(m.as_pointer())
            except Exception:
                used_mat_pointers.add(("__name__", getattr(m, "name", "")))

        for obj in bpy.data.objects:
            try:
                slots = getattr(obj, "material_slots", None)
            except Exception:
                slots = None
            if not slots:
                continue
            if getattr(obj, "type", "") == 'MESH':
                try:
                    mesh = obj.data
                    polys = mesh.polygons if mesh else []
                except Exception:
                    continue
                if not polys or len(polys) == 0:
                    # Malla sin caras: no cuenta como uso real.
                    continue
                try:
                    used_indices = set(p.material_index for p in polys)
                except Exception:
                    continue
                for idx in used_indices:
                    if 0 <= idx < len(slots):
                        try:
                            _remember_mat(slots[idx].material)
                        except Exception:
                            pass
            else:
                for slot in slots:
                    try:
                        _remember_mat(slot.material)
                    except Exception:
                        pass

        def _mat_key(m):
            try:
                return m.as_pointer()
            except Exception:
                return ("__name__", getattr(m, "name", ""))

        def _used_count(materials):
            return sum(1 for m in materials if _mat_key(m) in used_mat_pointers)

        def _has_object_usage(materials):
            return _used_count(materials) > 0

        index_results = query_texture_index(materials_by_name.keys())
        images_assigned = 0
        paths_filled = 0
        missing_images = 0
        not_found = 0
        conflict_count = 0

        print("\n--- RELLENANDO TEXTURAS WMO ---")
        for lookup_name, materials in materials_by_name.items():
            mat_count = len(materials)

            def _register_resolved(target_path, assigned, filled, missing):
                if missing > 0:
                    if missing >= mat_count:
                        detail = target_path
                    else:
                        detail = f"{target_path} ({missing}/{mat_count} sin imagen)"
                    add_texture_report_item(scene.wmo_texture_noimage, lookup_name, mat_count, detail)
                else:
                    add_texture_report_item(scene.wmo_texture_ok, lookup_name, mat_count, target_path)

            target_wow_path = custom_map.get(lookup_name)
            if target_wow_path:
                assigned, filled, missing = assign_wmo_path_to_materials(
                    materials, lookup_name, target_wow_path, image_map
                )
                images_assigned += assigned
                paths_filled += filled
                missing_images += missing
                _register_resolved(target_wow_path, assigned, filled, missing)
                print(f"CUSTOM: {lookup_name} -> {target_wow_path}")
                continue

            preferred_path = preferences.get(lookup_name)
            if preferred_path:
                assigned, filled, missing = assign_wmo_path_to_materials(
                    materials, lookup_name, preferred_path, image_map
                )
                images_assigned += assigned
                paths_filled += filled
                missing_images += missing
                _register_resolved(preferred_path, assigned, filled, missing)
                print(f"PREFERENCIA: {lookup_name} -> {preferred_path}")
                continue

            json_candidates = dedupe_candidates(general_candidates.get(lookup_name, []))
            if len(json_candidates) == 1:
                target_wow_path = json_candidates[0]["path"]
                assigned, filled, missing = assign_wmo_path_to_materials(
                    materials, lookup_name, target_wow_path, image_map
                )
                images_assigned += assigned
                paths_filled += filled
                missing_images += missing
                _register_resolved(target_wow_path, assigned, filled, missing)
                print(f"JSON: {lookup_name} -> {target_wow_path}")
                continue

            if len(json_candidates) > 1:
                candidates = dedupe_candidates(json_candidates + index_results.get(lookup_name, []))
                if add_texture_conflict(scene, lookup_name, mat_count, candidates):
                    conflict_count += 1
                    print(f"CONFLICTO JSON: {lookup_name} ({len(candidates)} opciones)")
                else:
                    used_count = _used_count(materials)
                    if used_count == 0:
                        print(f"IGNORADO (sin objeto): {lookup_name}")
                    else:
                        not_found += used_count
                        add_texture_report_item(scene.wmo_texture_notfound, lookup_name, used_count, "sin candidatos")
                        print(f"NO ENCONTRADO: {lookup_name}")
                continue

            sqlite_candidates = dedupe_candidates(index_results.get(lookup_name, []))
            if len(sqlite_candidates) == 1:
                target_wow_path = sqlite_candidates[0]["path"]
                assigned, filled, missing = assign_wmo_path_to_materials(
                    materials, lookup_name, target_wow_path, image_map
                )
                images_assigned += assigned
                paths_filled += filled
                missing_images += missing
                _register_resolved(target_wow_path, assigned, filled, missing)
                print(f"SQLite: {lookup_name} -> {target_wow_path}")
            elif len(sqlite_candidates) > 1:
                if add_texture_conflict(scene, lookup_name, mat_count, sqlite_candidates):
                    conflict_count += 1
                    print(f"CONFLICTO: {lookup_name} ({len(sqlite_candidates)} opciones)")
                else:
                    used_count = _used_count(materials)
                    if used_count == 0:
                        print(f"IGNORADO (sin objeto): {lookup_name}")
                    else:
                        not_found += used_count
                        add_texture_report_item(scene.wmo_texture_notfound, lookup_name, used_count, "sin candidatos")
                        print(f"NO ENCONTRADO: {lookup_name}")
            else:
                used_count = _used_count(materials)
                if used_count == 0:
                    print(f"IGNORADO (sin objeto): {lookup_name}")
                else:
                    not_found += used_count
                    add_texture_report_item(scene.wmo_texture_notfound, lookup_name, used_count, "sin candidatos")
                    print(f"NO ENCONTRADO: {lookup_name}")

        if scene.wmo_texture_conflicts:
            refresh_texture_candidate_list(scene)

        scene.wmo_texture_summary = (
            f"{paths_filled} rutas, {conflict_count} conflictos, "
            f"{not_found} sin encontrar, {missing_images} sin imagen"
        )
        self.report({'INFO'}, f"Procesado: {scene.wmo_texture_summary}")
        return {'FINISHED'}


# =====================================================
# OPERADOR 8 – Añadir a Base de Datos
# =====================================================

class MATERIAL_OT_wbs_add_to_db(bpy.types.Operator):
    bl_idname = "material.wbs_add_to_db"
    bl_label = "Añadir a Base de Datos"
    bl_description = "Guarda esta ruta en la base de datos."

    def execute(self, context):
        props = context.scene.wmo_auto_props
        if not props.new_wow_path:
            self.report({'ERROR'}, "La Ruta WoW no puede estar vacía")
            return {'CANCELLED'}

        target_label, error = save_texture_entry_to_target(
            props.save_json_target,
            props.new_json_name,
            props.new_mat_name,
            props.new_wow_path
        )
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        if props.new_mat_name:
            self.report({'INFO'}, f"Añadido a Custom en {target_label}: {props.new_mat_name}")
        else:
            self.report({'INFO'}, f"Añadido a General en {target_label}")

        props.new_mat_name = ""
        props.new_wow_path = ""
        props.new_json_name = ""
        return {'FINISHED'}


class MATERIAL_OT_wmo_apply_conflict(bpy.types.Operator):
    bl_idname = "material.wmo_apply_conflict"
    bl_label = "Aplicar selección"
    bl_description = "Aplica la ruta seleccionada al conflicto actual"
    bl_options = {'REGISTER', 'UNDO'}

    remember: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        scene = context.scene
        if not scene.wmo_texture_conflicts:
            self.report({'ERROR'}, "No hay conflictos pendientes")
            return {'CANCELLED'}

        conflict_index = max(0, min(scene.wmo_texture_conflict_index, len(scene.wmo_texture_conflicts) - 1))
        conflict = scene.wmo_texture_conflicts[conflict_index]

        try:
            candidates = json.loads(conflict.candidates_json)
        except:
            candidates = []

        if not candidates:
            self.report({'ERROR'}, "El conflicto no tiene opciones")
            return {'CANCELLED'}

        candidate_index = max(0, min(scene.wmo_texture_candidate_index, len(candidates) - 1))
        chosen_path = to_storage_path(candidates[candidate_index].get("path", ""))
        lookup_name = clean_lookup_name(conflict.material_name)
        materials = [
            mat for mat in bpy.data.materials
            if hasattr(mat, "wow_wmo_material") and clean_lookup_name(mat.name) == lookup_name
        ]

        assigned, filled, missing = assign_wmo_path_to_materials(
            materials, lookup_name, chosen_path, build_image_map()
        )

        if self.remember:
            set_texture_preference(lookup_name, chosen_path)

        # Mover el conflicto resuelto al Control de Texturas
        mat_count = len(materials) if materials else conflict.material_count
        if missing > 0:
            if missing >= mat_count:
                detail = chosen_path
            else:
                detail = f"{chosen_path} ({missing}/{mat_count} sin imagen)"
            add_texture_report_item(scene.wmo_texture_noimage, conflict.material_name, mat_count, detail)
        else:
            add_texture_report_item(scene.wmo_texture_ok, conflict.material_name, mat_count, chosen_path)

        scene.wmo_texture_conflicts.remove(conflict_index)
        if scene.wmo_texture_conflict_index >= len(scene.wmo_texture_conflicts):
            scene.wmo_texture_conflict_index = max(0, len(scene.wmo_texture_conflicts) - 1)
        refresh_texture_candidate_list(scene)

        suffix = " y recordado" if self.remember else ""
        self.report({'INFO'}, f"Aplicado{suffix}: {filled} rutas, {missing} sin imagen")
        return {'FINISHED'}


class MATERIAL_OT_wmo_skip_conflict(bpy.types.Operator):
    bl_idname = "material.wmo_skip_conflict"
    bl_label = "Saltar conflicto"
    bl_description = "Quita el conflicto actual de la lista sin aplicar nada"

    def execute(self, context):
        scene = context.scene
        if not scene.wmo_texture_conflicts:
            return {'CANCELLED'}

        index = max(0, min(scene.wmo_texture_conflict_index, len(scene.wmo_texture_conflicts) - 1))
        skipped_name = scene.wmo_texture_conflicts[index].material_name
        scene.wmo_texture_conflicts.remove(index)
        if scene.wmo_texture_conflict_index >= len(scene.wmo_texture_conflicts):
            scene.wmo_texture_conflict_index = max(0, len(scene.wmo_texture_conflicts) - 1)
        refresh_texture_candidate_list(scene)
        self.report({'INFO'}, f"Saltado: {skipped_name}")
        return {'FINISHED'}


class MATERIAL_OT_wmo_select_reported(bpy.types.Operator):
    bl_idname = "material.wmo_select_reported"
    bl_label = "Seleccionar objeto / material"
    bl_description = "Selecciona un objeto que use esta textura y activa su material en Material Properties"
    bl_options = {'REGISTER', 'UNDO'}

    collection: bpy.props.StringProperty(default="NOTFOUND")

    def execute(self, context):
        scene = context.scene
        key = (self.collection or "").upper()
        if key == "OK":
            coll, idx = scene.wmo_texture_ok, scene.wmo_texture_ok_index
        elif key == "NOIMAGE":
            coll, idx = scene.wmo_texture_noimage, scene.wmo_texture_noimage_index
        elif key == "CONFLICT":
            coll, idx = scene.wmo_texture_conflicts, scene.wmo_texture_conflict_index
        else:
            coll, idx = scene.wmo_texture_notfound, scene.wmo_texture_notfound_index

        if not coll or idx < 0 or idx >= len(coll):
            self.report({'WARNING'}, "No hay elemento seleccionado en esa lista")
            return {'CANCELLED'}

        lookup_name = coll[idx].material_name
        obj_name, mat_name = select_wmo_report_entry(context, lookup_name)
        if obj_name and mat_name:
            self.report({'INFO'}, f"Seleccionado: {obj_name} -> {mat_name}")
            return {'FINISHED'}
        elif obj_name:
            self.report({'WARNING'}, f"Objeto {obj_name} sin material localizable")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, f"No se encontró objeto para '{lookup_name}'")
            return {'CANCELLED'}


# =====================================================
# OPERADOR 9 – Analizar Materiales sin imagen
# =====================================================

class MATERIAL_OT_check_missing_images(bpy.types.Operator):
    bl_idname = "material.check_missing_images"
    bl_label = "Analizar Materiales"
    bl_description = "Muestra en consola qué materiales no tienen imagen asignada y en qué objeto están."
    bl_options = {'REGISTER'}

    def execute(self, context):
        bpy.ops.wm.console_toggle()
        materiales_sin_imagen = []
        for obj in bpy.context.scene.objects:
            if obj.type != 'MESH':
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None:
                    materiales_sin_imagen.append({"objeto": obj.name, "material": "(slot vacío)", "motivo": "Sin material asignado"})
                    continue
                if not mat.use_nodes:
                    materiales_sin_imagen.append({"objeto": obj.name, "material": mat.name, "motivo": "No usa nodos"})
                    continue
                tiene_imagen = False
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image is not None:
                        tiene_imagen = True
                        break
                if not tiene_imagen:
                    nodos = [n.type for n in mat.node_tree.nodes]
                    if 'TEX_IMAGE' in nodos:
                        motivo = "Nodo Image Texture SIN imagen cargada"
                    elif len(nodos) <= 2:
                        motivo = "Material vacío/básico (sin Image Texture)"
                    else:
                        motivo = "Material procedural (sin Image Texture)"
                    materiales_sin_imagen.append({"objeto": obj.name, "material": mat.name, "motivo": motivo})

        print("\n" + "="*60)
        print("  ANÁLISIS DE MATERIALES SIN IMAGEN")
        print("="*60)
        if not materiales_sin_imagen:
            print("\n✅ Todos los materiales tienen imagen asignada.")
        else:
            print(f"\n⚠️  Se encontraron {len(materiales_sin_imagen)} problema(s):\n")
            for i, item in enumerate(materiales_sin_imagen, 1):
                print(f"  [{i}] Objeto:   {item['objeto']}")
                print(f"       Material: {item['material']}")
                print(f"       Motivo:   {item['motivo']}")
                print()
        total_mesh = sum(1 for o in bpy.context.scene.objects if o.type == 'MESH')
        print("="*60)
        print(f"  TOTAL OBJETOS ANALIZADOS: {total_mesh}")
        print(f"  TOTAL PROBLEMAS:          {len(materiales_sin_imagen)}")
        print("="*60 + "\n")
        if materiales_sin_imagen:
            self.report({'WARNING'}, f"{len(materiales_sin_imagen)} materiales sin imagen. Revisa la consola.")
        else:
            self.report({'INFO'}, "Todos los materiales tienen imagen asignada.")
        return {'FINISHED'}


# =====================================================
# OPERADOR 10 – Contar materiales
# =====================================================

class MATERIAL_OT_count_materials(bpy.types.Operator):
    bl_idname = "material.count_materials"
    bl_label = "Nº Total de Materiales"
    bl_description = "Abre la consola y muestra el desglose completo de materiales del proyecto."
    bl_options = {'REGISTER'}

    def execute(self, context):
        bpy.ops.wm.console_toggle()

        # Total en el proyecto (bpy.data)
        total_proyecto = len(bpy.data.materials)

        # Materiales usados por algún objeto (cualquier objeto, visible o no)
        mats_con_objeto = set()
        for obj in bpy.data.objects:
            if obj.type != 'MESH':
                continue
            for slot in obj.material_slots:
                if slot.material is not None:
                    mats_con_objeto.add(slot.material.name)

        # Materiales sin ningún objeto
        mats_sin_objeto = [mat.name for mat in bpy.data.materials if mat.name not in mats_con_objeto]

        # Materiales del objeto seleccionado
        obj = context.active_object
        mats_objeto = []
        if obj and obj.type == 'MESH':
            for slot in obj.material_slots:
                if slot.material is not None:
                    mats_objeto.append(slot.material.name)

        print("\n" + "="*60)
        print("  CONTEO DE MATERIALES")
        print("="*60)
        print(f"\n  📦 Total en el proyecto       : {total_proyecto}")
        print(f"  🔗 Usados por objetos         : {len(mats_con_objeto)}")
        print(f"  👻 Sin ningún objeto (huérfanos): {len(mats_sin_objeto)}")
        if mats_sin_objeto:
            for nombre in mats_sin_objeto:
                print(f"       · {nombre}")

        print()
        if obj:
            print(f"  🔷 Objeto seleccionado        : {obj.name}")
            print(f"  📄 Materiales asignados       : {len(mats_objeto)}")
            if mats_objeto:
                for i, nombre in enumerate(mats_objeto, 1):
                    print(f"       [{i}] {nombre}")
            else:
                print("       (ninguno)")
        else:
            print("  ⚠️  No hay ningún objeto activo seleccionado.")

        print("\n" + "="*60 + "\n")
        self.report({'INFO'}, (
            f"Total: {total_proyecto} | Con objeto: {len(mats_con_objeto)} | "
            f"Huérfanos: {len(mats_sin_objeto)} | Seleccionado: {len(mats_objeto)}"
        ))
        return {'FINISHED'}


# =====================================================
# OPERADOR 11 – Exportar nombres de materiales
# =====================================================

class MATERIAL_OT_export_names(bpy.types.Operator):
    bl_idname = "material.export_names"
    bl_label = "Exportar Nombres Texturas a Escritorio"
    bl_description = "Guarda los nombres de los materiales de todos los objetos visibles en materiales.txt en el Escritorio."
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Recoger materiales únicos de todos los objetos visibles (ojito encendido)
        nombres_vistos = set()
        materiales_ordenados = []

        for obj in bpy.data.objects:
            if obj.type != 'MESH':
                continue
            if obj.hide_viewport:
                continue  # Ojito apagado → ignorar
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None:
                    continue
                if mat.name not in nombres_vistos:
                    nombres_vistos.add(mat.name)
                    materiales_ordenados.append(mat.name)

        ruta = os.path.join(get_desktop(), "materiales.txt")

        try:
            with open(ruta, "w") as f:
                for nombre in materiales_ordenados:
                    f.write(nombre + "\n")
            print(f"\n✅ Exportados {len(materiales_ordenados)} materiales únicos de objetos visibles:\n   {ruta}\n")
            self.report({'INFO'}, f"Exportados {len(materiales_ordenados)} materiales → Escritorio/materiales.txt")
        except Exception as e:
            self.report({'ERROR'}, f"Error al guardar: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


# =====================================================
# OPERADOR 12 – Exportar PNGs
# =====================================================

class MATERIAL_OT_export_pngs(bpy.types.Operator):
    bl_idname = "material.export_pngs"
    bl_label = "Exportar PNGs Escritorio"
    bl_description = "Exporta como PNG las texturas DiffuseTexture1 de todos los objetos visibles a Escritorio/texturas/."
    bl_options = {'REGISTER'}

    NODE_LABEL_TARGET = "DiffuseTexture1"

    def execute(self, context):
        output_folder = os.path.join(get_desktop(), "texturas")
        os.makedirs(output_folder, exist_ok=True)

        def get_image_by_node_label(mat, label):
            if mat is None or not mat.use_nodes:
                return None
            for node in mat.node_tree.nodes:
                if node.type != 'TEX_IMAGE':
                    continue
                if node.label == label or node.name == label:
                    return node.image
            return None

        # Recoger imágenes únicas de todos los objetos visibles (ojito encendido)
        imagenes = {}   # img.name -> (img, mat.name, obj.name)
        sin_nodo = []   # (mat.name, obj.name)

        objetos_visibles = [
            obj for obj in bpy.data.objects
            if obj.type == 'MESH' and not obj.hide_viewport
        ]

        if not objetos_visibles:
            self.report({'ERROR'}, "No hay objetos Mesh visibles en el proyecto.")
            return {'CANCELLED'}

        print(f"\n══════════════════════════════════════════")
        print(f"  Objetos visibles procesados: {len(objetos_visibles)}")
        print(f"  Buscando nodo: '{self.NODE_LABEL_TARGET}'")
        print(f"  Salida  : {output_folder}")
        print(f"══════════════════════════════════════════")

        for obj in objetos_visibles:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None:
                    continue
                img = get_image_by_node_label(mat, self.NODE_LABEL_TARGET)
                if img is not None:
                    if img.name not in imagenes:
                        imagenes[img.name] = (img, mat.name, obj.name)
                else:
                    sin_nodo.append((mat.name, obj.name))

        print(f"\n  Texturas únicas encontradas: {len(imagenes)}")
        if sin_nodo:
            print(f"\n  ⚠️  Materiales sin el nodo '{self.NODE_LABEL_TARGET}' ({len(sin_nodo)}):")
            for mat_name, obj_name in sin_nodo:
                print(f"       · [{obj_name}] {mat_name}")

        exportadas = []
        errores = []
        scene = context.scene

        for img_name, (img, mat_name, obj_name) in imagenes.items():
            safe_name = bpy.path.clean_name(img_name)
            if not safe_name.lower().endswith(".png"):
                safe_name += ".png"
            out_path = os.path.join(output_folder, safe_name)
            try:
                orig_path = img.filepath_raw
                orig_format = img.file_format
                img.filepath_raw = out_path
                img.file_format = 'PNG'
                img.save()
                img.filepath_raw = orig_path
                img.file_format = orig_format
                exportadas.append((obj_name, mat_name, img_name, safe_name))
            except Exception:
                try:
                    rs = scene.render.image_settings
                    orig_fmt = rs.file_format
                    rs.file_format = 'PNG'
                    img.save_render(out_path, scene=scene)
                    rs.file_format = orig_fmt
                    exportadas.append((obj_name, mat_name, img_name, safe_name))
                except Exception as e2:
                    errores.append((obj_name, mat_name, img_name, str(e2)))

        print(f"\n  Exportadas: {len(exportadas)}")
        for obj_name, mat_name, img_name, file_name in exportadas:
            print(f"  ✅  [{obj_name}] [{mat_name}]  {img_name}  →  {file_name}")
        if errores:
            print(f"\n  Errores: {len(errores)}")
            for obj_name, mat_name, img_name, err in errores:
                print(f"  ❌  [{obj_name}] [{mat_name}]  {img_name}  →  {err}")
        print(f"\n  📁 {output_folder}")
        print(f"══════════════════════════════════════════\n")

        self.report({'INFO'}, f"Exportadas {len(exportadas)} texturas → Escritorio/texturas/")
        return {'FINISHED'}


# =====================================================
# OPERADOR EXTRA – Cerrar Consola
# =====================================================

class WM_OT_cerrar_consola(bpy.types.Operator):
    bl_idname = "wm.cerrar_consola"
    bl_label = "Cerrar Consola"
    bl_description = "Cierra la consola del sistema"

    def execute(self, context):
        bpy.ops.wm.console_toggle()
        return {'FINISHED'}


# =====================================================
# OPERADOR EXTRA – Abrir carpeta del AddOn
# =====================================================

class WM_OT_abrir_carpeta_addon(bpy.types.Operator):
    bl_idname = "wm.abrir_carpeta_addon"
    bl_label = "Ir a la Carpeta del AddOn"
    bl_description = "Abre en el explorador de archivos la carpeta donde está instalado el addon"

    def execute(self, context):
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        bpy.ops.wm.path_open(filepath=addon_dir)
        return {'FINISHED'}


# =====================================================
# OPERADOR IMPORT – Importar JSON Custom
# =====================================================

class WM_OT_importar_json_custom(bpy.types.Operator):
    bl_idname = "wm.importar_json_custom"
    bl_label = "JSON de Materiales Custom"
    bl_description = "Selecciona un archivo JSON y lo importa a la carpeta JSON Customs del addon"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath.lower().endswith('.json'):
            self.report({'ERROR'}, "Selecciona un archivo .json")
            return {'CANCELLED'}

        customs_dir = get_json_customs_dir()
        os.makedirs(customs_dir, exist_ok=True)

        fname = os.path.basename(self.filepath)
        dest = os.path.join(customs_dir, fname)

        try:
            shutil.copy2(self.filepath, dest)
        except Exception as e:
            self.report({'ERROR'}, f"Error al copiar el archivo: {e}")
            return {'CANCELLED'}

        # Marcar como activo por defecto
        config = load_json_config()
        if fname not in config:
            config[fname] = True
        save_json_config(config)

        self.report({'INFO'}, f"JSON importado y activado: {fname}")
        return {'FINISHED'}


# =====================================================
# OPERADOR IMPORT – Activar/Desactivar JSON Custom
# =====================================================

class WM_OT_toggle_json_custom(bpy.types.Operator):
    bl_idname = "wm.toggle_json_custom"
    bl_label = "Activar/Desactivar JSON"
    bl_description = "Activa o desactiva este JSON para que el addon lo use al crear materiales"

    filename: bpy.props.StringProperty()

    def execute(self, context):
        config = load_json_config()
        config[self.filename] = not config.get(self.filename, True)
        save_json_config(config)
        # Forzar refresco del área
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


# =====================================================
# MENÚ – Lista de JSON Custom
# =====================================================

class WM_MT_lista_json_custom(bpy.types.Menu):
    bl_idname = "WM_MT_lista_json_custom"
    bl_label = "JSON Customs importados"

    def draw(self, context):
        layout = self.layout
        files = get_custom_json_files()
        config = load_json_config()

        if not files:
            layout.label(text="No hay ningún JSON importado todavía.", icon='INFO')
            layout.label(text="Usa 'JSON de Materiales Custom' para importar uno.")
        else:
            for fname in files:
                activo = config.get(fname, True)
                icon = 'CHECKBOX_HLT' if activo else 'CHECKBOX_DEHLT'
                op = layout.operator(
                    "wm.toggle_json_custom",
                    text=fname,
                    icon=icon,
                    depress=activo
                )
                op.filename = fname

        layout.separator()
        layout.label(text="Cambios en el siguiente 'Rellenar Texturas'.", icon='INFO')


# =====================================================
# OPERADOR EXTRA – Rotar 90° en Z (Shift + R)
# =====================================================

class NORTE_OT_rotate_90_z(bpy.types.Operator):
    bl_idname = "norte.rotate_90_z"
    bl_label = "Rotar 90° en Z"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = context.selected_objects
        if not objs:
            return {'CANCELLED'}

        center = Vector((0.0, 0.0, 0.0))
        for obj in objs:
            center += obj.location
        center /= len(objs)

        rot = Matrix.Rotation(radians(90), 4, 'Z')

        for obj in objs:
            obj.location -= center
            obj.location = rot @ obj.location
            obj.location += center
            obj.rotation_euler.rotate(rot)

        return {'FINISHED'}


# =====================================================
# OPERADOR – Dividir objeto en Sub-grupos WMO
# =====================================================

class OBJECT_OT_dividir_wmo(bpy.types.Operator):
    bl_idname = "object.dividir_wmo"
    bl_label = "Triangular y Dividir (Preciso)"
    bl_description = (
        "Triangula y divide con mas precision, respetando grupos y cortes naturales. "
        "Muy lento en mallas grandes"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # MOVI stores vertex indices as uint16 and MOBA stores num_indices as uint16.
    # 20k triangles = 60k indices, leaving room below 65,535 per material batch.
    MAX_VERTICES = 60000
    MAX_GROUP_TRIANGLES = 60000
    MAX_BATCH_TRIANGLES = 20000

    # The topology-aware Python path is ideal for ordinary WMO pieces, but it
    # must not be run repeatedly over a multi-million-triangle source.  Above
    # this threshold we read mesh data once with Blender's bulk API and make
    # every region before separating anything.
    FAST_SPLIT_THRESHOLD = 100000
    FAST_REGION_ATTRIBUTE = "_wow_atajos_wmo_region"
    FAST_ORIGINAL_MATERIAL_ATTRIBUTE = "_wow_atajos_wmo_original_material"

    def _mesh_wmo_stats(self, mesh, face_indices=None):
        """Return WMO limits using Blender polygon indices, never BMesh indices.

        Keeping the original polygon IDs is important: the final selection is made
        directly on ``mesh.polygons`` after the topology analysis.
        """
        used_verts = set()
        total_tris = 0
        tris_by_material = {}
        polygons = mesh.polygons if face_indices is None else (
            mesh.polygons[index] for index in face_indices
        )

        for polygon in polygons:
            face_tris = max(0, len(polygon.vertices) - 2)
            total_tris += face_tris
            material_index = polygon.material_index
            tris_by_material[material_index] = (
                tris_by_material.get(material_index, 0) + face_tris
            )
            used_verts.update(polygon.vertices)

        return (
            len(used_verts),
            total_tris,
            max(tris_by_material.values(), default=0),
        )

    def _object_wmo_stats(self, obj):
        return self._mesh_wmo_stats(obj.data)

    def _triangulate_object(self, obj, bmesh):
        # Do not make a complete BMesh copy merely to discover that an imported
        # multi-million-face mesh is already triangles.  ``foreach_get`` reads
        # that fact directly from Blender's contiguous mesh data.
        if len(obj.data.polygons) >= self.FAST_SPLIT_THRESHOLD:
            try:
                import numpy as np
                loop_totals = np.empty(len(obj.data.polygons), dtype=np.int32)
                obj.data.polygons.foreach_get("loop_total", loop_totals)
                if np.all(loop_totals == 3):
                    return 0
            except ImportError:
                pass

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            faces_to_triangulate = [face for face in bm.faces if len(face.verts) != 3]
            if not faces_to_triangulate:
                return 0

            bmesh.ops.triangulate(
                bm,
                faces=faces_to_triangulate,
                quad_method='BEAUTY',
                ngon_method='BEAUTY',
            )
            bm.to_mesh(obj.data)
            obj.data.update()
            return len(faces_to_triangulate)
        finally:
            bm.free()

    def _fits_wmo_limits(self, verts, total_tris, max_batch_tris):
        return (
            verts <= self.MAX_VERTICES and
            total_tris <= self.MAX_GROUP_TRIANGLES and
            max_batch_tris <= self.MAX_BATCH_TRIANGLES
        )

    def _wmo_limit_violations(self, verts, total_tris, max_batch_tris):
        violations = []
        if verts > self.MAX_VERTICES:
            violations.append(f"{verts:,} vertices")
        if total_tris > self.MAX_GROUP_TRIANGLES:
            violations.append(f"{total_tris:,} tris")
        if max_batch_tris > self.MAX_BATCH_TRIANGLES:
            violations.append(f"{max_batch_tris:,} tris en un material")
        return violations

    @staticmethod
    def _edge_key(vertex_a, vertex_b):
        return (vertex_a, vertex_b) if vertex_a < vertex_b else (vertex_b, vertex_a)

    def _uv_edge_is_discontinuous(self, mesh, polygon_a, polygon_b, edge_key):
        """True when an unmarked UV seam is also visible on the active UV map."""
        uv_layer = mesh.uv_layers.active
        if uv_layer is None:
            return False

        def edge_uvs(polygon):
            result = {}
            for loop_index in polygon.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                if vertex_index in edge_key:
                    result[vertex_index] = uv_layer.data[loop_index].uv.copy()
            return result

        uvs_a = edge_uvs(polygon_a)
        uvs_b = edge_uvs(polygon_b)
        if len(uvs_a) != 2 or len(uvs_b) != 2:
            return False

        return any((uvs_a[index] - uvs_b[index]).length > 0.00001 for index in edge_key)

    def _cut_penalty(self, mesh, polygon_a, polygon_b, edge, edge_key):
        """How costly it is visually to leave this shared edge as a WMO cut.

        Large values mean that the faces should stay together.  Material/UV
        seams, marked sharp edges and geometric corners are cheap places to cut.
        """
        penalty = 20.0

        if polygon_a.material_index != polygon_b.material_index:
            penalty -= 14.0
        if getattr(edge, "use_seam", False):
            penalty -= 12.0
        if getattr(edge, "use_edge_sharp", False):
            penalty -= 10.0
        if self._uv_edge_is_discontinuous(mesh, polygon_a, polygon_b, edge_key):
            penalty -= 12.0

        normal_dot = max(-1.0, min(1.0, polygon_a.normal.dot(polygon_b.normal)))
        if normal_dot > 0.985:
            penalty += 10.0       # a smooth wall/floor should not be sliced
        elif normal_dot < 0.82:
            penalty -= 10.0       # geometric corner: naturally discrete cut
        elif normal_dot < 0.94:
            penalty -= 4.0

        # Long, smooth edges are especially conspicuous.  The scaling is
        # deliberately capped, so scene scale cannot dominate the decision.
        edge_length = (mesh.vertices[edge_key[0]].co - mesh.vertices[edge_key[1]].co).length
        penalty += min(8.0, edge_length * 0.25)
        return max(0.25, penalty)

    def _build_face_topology(self, mesh):
        """Build an exact polygon adjacency graph and its natural-cut costs."""
        adjacency = {polygon.index: [] for polygon in mesh.polygons}
        faces_by_edge = {}
        edge_lookup = {
            self._edge_key(edge.vertices[0], edge.vertices[1]): edge
            for edge in mesh.edges
        }

        for polygon in mesh.polygons:
            vertices = list(polygon.vertices)
            for index, vertex_a in enumerate(vertices):
                edge_key = self._edge_key(vertex_a, vertices[(index + 1) % len(vertices)])
                faces_by_edge.setdefault(edge_key, []).append(polygon.index)

        for edge_key, linked_faces in faces_by_edge.items():
            # Do not bridge non-manifold edges: they are collision hazards and
            # connecting through one would create a misleading "room" group.
            if len(linked_faces) != 2:
                continue
            face_a, face_b = linked_faces
            edge = edge_lookup.get(edge_key)
            if edge is None:
                continue
            penalty = self._cut_penalty(
                mesh, mesh.polygons[face_a], mesh.polygons[face_b], edge, edge_key
            )
            adjacency[face_a].append((face_b, penalty))
            adjacency[face_b].append((face_a, penalty))

        components = []
        unvisited = set(adjacency)
        while unvisited:
            start = min(unvisited)
            component = set()
            stack = [start]
            unvisited.remove(start)
            while stack:
                face_index = stack.pop()
                component.add(face_index)
                for neighbor, _ in adjacency[face_index]:
                    if neighbor in unvisited:
                        unvisited.remove(neighbor)
                        stack.append(neighbor)
            components.append(component)

        return adjacency, components

    def _component_center_and_scale(self, mesh, component):
        center = Vector()
        min_corner = Vector((float('inf'), float('inf'), float('inf')))
        max_corner = Vector((float('-inf'), float('-inf'), float('-inf')))

        for face_index in component:
            polygon = mesh.polygons[face_index]
            center += polygon.center
            for vertex_index in polygon.vertices:
                coordinate = mesh.vertices[vertex_index].co
                min_corner.x = min(min_corner.x, coordinate.x)
                min_corner.y = min(min_corner.y, coordinate.y)
                min_corner.z = min(min_corner.z, coordinate.z)
                max_corner.x = max(max_corner.x, coordinate.x)
                max_corner.y = max(max_corner.y, coordinate.y)
                max_corner.z = max(max_corner.z, coordinate.z)

        center /= max(1, len(component))
        return center, max(0.001, (max_corner - min_corner).length)

    def _choose_connected_region(self, mesh, component, adjacency):
        """Create one connected WMO-safe region from an oversized component.

        The priority queue expands through expensive-to-cut edges first.  It is
        therefore deterministic, topology-aware and compact, instead of relying
        on the arbitrary order of imported triangles.
        """
        component_center, component_scale = self._component_center_and_scale(mesh, component)
        seed = min(
            component,
            key=lambda face_index: (
                (mesh.polygons[face_index].center - component_center).length,
                face_index,
            ),
        )

        selected = {seed}
        selected_vertices = set(mesh.polygons[seed].vertices)
        selected_triangles = max(0, len(mesh.polygons[seed].vertices) - 2)
        selected_by_material = {
            mesh.polygons[seed].material_index: selected_triangles,
        }
        joined_cost = {}
        queue = []

        def add_frontier(face_index, edge_cost):
            if face_index in selected or face_index not in component:
                return
            joined_cost[face_index] = joined_cost.get(face_index, 0.0) + edge_cost
            distance = (mesh.polygons[face_index].center - component_center).length / component_scale
            # Higher preserved-cut cost wins; a small compactness penalty stops
            # a piece from travelling through a thin corridor unnecessarily.
            priority = joined_cost[face_index] - distance * 1.5
            heapq.heappush(queue, (-priority, face_index, joined_cost[face_index]))

        for neighbor, edge_cost in adjacency[seed]:
            add_frontier(neighbor, edge_cost)

        while queue:
            _, candidate, queued_cost = heapq.heappop(queue)
            if candidate in selected or joined_cost.get(candidate) != queued_cost:
                continue

            polygon = mesh.polygons[candidate]
            triangle_count = max(0, len(polygon.vertices) - 2)
            added_vertices = set(polygon.vertices) - selected_vertices
            material_triangles = selected_by_material.get(polygon.material_index, 0)
            if (
                len(selected_vertices) + len(added_vertices) > self.MAX_VERTICES
                or selected_triangles + triangle_count > self.MAX_GROUP_TRIANGLES
                or material_triangles + triangle_count > self.MAX_BATCH_TRIANGLES
            ):
                # Limits only become tighter as the region grows, so this face
                # can never become eligible later in this particular region.
                continue

            selected.add(candidate)
            selected_vertices.update(added_vertices)
            selected_triangles += triangle_count
            selected_by_material[polygon.material_index] = material_triangles + triangle_count

            for neighbor, edge_cost in adjacency[candidate]:
                add_frontier(neighbor, edge_cost)

        return selected

    def _next_wmo_region(self, mesh):
        adjacency, components = self._build_face_topology(mesh)
        components.sort(key=lambda component: (-len(component), min(component)))

        # Each already-valid loose component becomes its own group.  This never
        # puts distant rooms, props or shells in a single WMO group.
        for component in components:
            stats = self._mesh_wmo_stats(mesh, component)
            if self._fits_wmo_limits(*stats):
                return component, len(components)

        # The largest remaining connected component has to be partitioned.
        component = components[0]
        region = self._choose_connected_region(mesh, component, adjacency)
        if not region:
            raise RuntimeError("No se pudo construir una region WMO conectada")
        return region, len(components)

    def _select_only_faces(self, obj, face_indices):
        face_indices = set(face_indices)
        mesh = obj.data

        for vert in mesh.vertices:
            vert.select = False
        for edge in mesh.edges:
            edge.select = False
        for poly in mesh.polygons:
            poly.select = poly.index in face_indices

        mesh.update()

    @staticmethod
    def _part_name_and_properties(obj, original_name, part_index):
        """Mark a separated object as one deterministic WMO part."""
        obj.name = f"{original_name}_WMO_{part_index}"
        obj["wow_atajos_wmo_source"] = original_name
        obj["wow_atajos_wmo_split"] = True
        obj["wow_atajos_wmo_part"] = part_index
        obj["wow_atajos_wmo_collision_ready"] = False
        # Blender creates a new Object datablock during Separate.  WBS object
        # properties may therefore return to their default state, in particular
        # ``wow_wmo_group.enabled = False``.  Such a part would be ignored by
        # both Quick Collision and the WMO exporter despite originating from a
        # valid WMO group, so restore its exportable WMO status explicitly.
        try:
            obj.wow_wmo_group.enabled = True
        except AttributeError:
            # Keep this tool usable without WBS installed; the collision tool
            # will clearly report that no WMO properties are available later.
            pass

    @staticmethod
    def _morton_3d(values):
        """Return a 30-bit Morton key for an ``(N, 3)`` uint32 array."""
        values = values.astype('uint32', copy=False)

        def spread(value):
            value &= 0x000003ff
            value = (value | (value << 16)) & 0x30000ff
            value = (value | (value << 8)) & 0x300f00f
            value = (value | (value << 4)) & 0x30c30c3
            value = (value | (value << 2)) & 0x9249249
            return value

        return spread(values[:, 0]) | (spread(values[:, 1]) << 1) | (spread(values[:, 2]) << 2)

    @staticmethod
    def _temporary_attribute_name(mesh, base_name):
        """Return an internal face-attribute name without overwriting user data."""
        name = base_name
        suffix = 1
        while mesh.attributes.get(name) is not None:
            name = f"{base_name}_{suffix}"
            suffix += 1
        return name

    def _fast_spatial_regions(self, mesh):
        """Make WMO-safe, compact spatial regions without Python face loops.

        A region contains at most 20,000 triangles.  It therefore satisfies all
        current WMO limits by construction: no material can exceed 20,000
        triangles and even wholly unshared triangles use only 60,000 vertices.
        Morton ordering keeps each region spatially compact, so the resulting
        cuts are stable and local rather than based on imported polygon order.
        """
        try:
            import numpy as np
        except ImportError as error:
            raise RuntimeError("Esta version de Blender no incluye NumPy para la division de mallas grandes") from error

        polygon_count = len(mesh.polygons)
        if polygon_count == 0:
            return np.empty(0, dtype=np.int32), 0

        loop_starts = np.empty(polygon_count, dtype=np.int32)
        loop_totals = np.empty(polygon_count, dtype=np.int32)
        mesh.polygons.foreach_get("loop_start", loop_starts)
        mesh.polygons.foreach_get("loop_total", loop_totals)
        if not np.all(loop_totals == 3):
            raise RuntimeError("La malla grande no quedo completamente triangulada")

        loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vertices)
        triangles = loop_vertices[
            (loop_starts[:, None] + np.arange(3, dtype=np.int32)).reshape(-1)
        ].reshape((polygon_count, 3))

        coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", coordinates)
        coordinates = coordinates.reshape((-1, 3))
        centers = coordinates[triangles[:, 0]].copy()
        centers += coordinates[triangles[:, 1]]
        centers += coordinates[triangles[:, 2]]
        centers *= (1.0 / 3.0)

        bounds_min = centers.min(axis=0)
        bounds_span = np.maximum(centers.max(axis=0) - bounds_min, 0.00001)
        quantized_centers = np.clip(
            ((centers - bounds_min) / bounds_span * 1023.0).astype(np.uint32),
            0,
            1023,
        )
        face_order = np.argsort(self._morton_3d(quantized_centers), kind='stable')
        del triangles, coordinates, centers, quantized_centers

        triangles_per_region = max(
            1,
            min(
                self.MAX_BATCH_TRIANGLES,
                self.MAX_GROUP_TRIANGLES,
                self.MAX_VERTICES // 3,
            ),
        )
        labels = np.empty(polygon_count, dtype=np.int32)
        labels[face_order] = np.arange(polygon_count, dtype=np.int32) // triangles_per_region
        return labels, int((polygon_count + triangles_per_region - 1) // triangles_per_region)

    @staticmethod
    def _fast_region_values(mesh, attribute_name, np):
        attribute = mesh.attributes.get(attribute_name)
        if attribute is None:
            raise RuntimeError("Blender no conservo las etiquetas internas de division")
        values = np.empty(len(mesh.polygons), dtype=np.int32)
        attribute.data.foreach_get("value", values)
        return values

    @staticmethod
    def _restore_fast_materials(mesh, original_materials, material_attribute_name,
                                region_attribute_name, np):
        """Restore material slots and remove all temporary split attributes."""
        material_attribute = mesh.attributes.get(material_attribute_name)
        if material_attribute is not None:
            original_indices = np.empty(len(mesh.polygons), dtype=np.int32)
            material_attribute.data.foreach_get("value", original_indices)
            mesh.materials.clear()
            for material in original_materials:
                mesh.materials.append(material)
            mesh.polygons.foreach_set("material_index", original_indices)
            mesh.attributes.remove(material_attribute)

        region_attribute = mesh.attributes.get(region_attribute_name)
        if region_attribute is not None:
            mesh.attributes.remove(region_attribute)
        mesh.update()

    def _fast_split_spatial_mesh_bulk(self, context, obj, original_name, triangulate_status):
        """Fallback: separate compact spatial regions in one operation.

        This is used only for one connected component that cannot fit into a
        WMO group on its own.  Whole loose components take precedence, so this
        fallback can never cut a separate column, prop or room island.
        """
        try:
            import numpy as np
        except ImportError:
            self.report({'ERROR'}, "NumPy no esta disponible para dividir esta malla grande")
            return {'CANCELLED'}

        if obj.data.users > 1:
            obj.data = obj.data.copy()

        mesh = obj.data
        original_materials = list(mesh.materials)
        region_attribute_name = self._temporary_attribute_name(mesh, self.FAST_REGION_ATTRIBUTE)
        material_attribute_name = self._temporary_attribute_name(
            mesh,
            self.FAST_ORIGINAL_MATERIAL_ATTRIBUTE,
        )
        temporary_material = None
        window_manager = context.window_manager
        window_manager.progress_begin(0, 100)
        try:
            labels, region_count = self._fast_spatial_regions(mesh)
            if region_count <= 1:
                self._part_name_and_properties(obj, original_name, 1)
                self.report({'INFO'}, f"Objeto {triangulate_status} y listo para WMO")
                return {'FINISHED'}
            window_manager.progress_update(35)

            original_indices = np.empty(len(mesh.polygons), dtype=np.int32)
            mesh.polygons.foreach_get("material_index", original_indices)
            material_attribute = mesh.attributes.new(material_attribute_name, 'INT', 'FACE')
            material_attribute.data.foreach_set("value", original_indices)
            region_attribute = mesh.attributes.new(region_attribute_name, 'INT', 'FACE')
            region_attribute.data.foreach_set("value", labels)
            del labels, original_indices

            # Separate by Material groups by slot index, including duplicate
            # slots that point to the same material.  One existing material is
            # enough; a temporary one is created only for meshes without any.
            slot_material = next((material for material in original_materials if material), None)
            if slot_material is None:
                temporary_material = bpy.data.materials.new("_WOW_Atajos_Temporal")
                slot_material = temporary_material
            while len(mesh.materials) < region_count:
                mesh.materials.append(slot_material)
            mesh.polygons.foreach_set("material_index", self._fast_region_values(
                mesh,
                region_attribute_name,
                np,
            ))
            mesh.update()
            window_manager.progress_update(50)

            before_objects = set(context.scene.objects)
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')
            window_manager.progress_update(80)

            parts = [
                candidate for candidate in context.selected_objects
                if candidate.type == 'MESH' and candidate.data.attributes.get(region_attribute_name)
            ]
            if len(parts) != region_count:
                parts = [
                    candidate for candidate in context.scene.objects
                    if candidate.type == 'MESH' and candidate.data.attributes.get(region_attribute_name) and (
                        candidate is obj or candidate not in before_objects
                    )
                ]
            if len(parts) != region_count:
                raise RuntimeError(
                    f"Blender devolvio {len(parts)} grupos y se esperaban {region_count}"
                )

            ordered_parts = []
            for part in parts:
                region_values = self._fast_region_values(part.data, region_attribute_name, np)
                if not len(region_values) or not np.all(region_values == region_values[0]):
                    raise RuntimeError("Una pieza WMO contiene etiquetas de region mezcladas")
                ordered_parts.append((int(region_values[0]), part))
            ordered_parts.sort(key=lambda item: item[0])

            for part_index, (_, part) in enumerate(ordered_parts, start=1):
                self._restore_fast_materials(
                    part.data,
                    original_materials,
                    material_attribute_name,
                    region_attribute_name,
                    np,
                )
                self._part_name_and_properties(part, original_name, part_index)

            parts = [part for _, part in ordered_parts]
            bpy.ops.object.select_all(action='DESELECT')
            for part in parts:
                part.select_set(True)
            context.view_layer.objects.active = parts[0]
            window_manager.progress_update(100)
            self.report({'INFO'}, (
                f"'{original_name}' {triangulate_status} y dividido en {len(parts)} sub-grupos WMO "
                f"por regiones espaciales compactas"
            ))
            return {'FINISHED'}
        except RuntimeError as error:
            # If Blender aborts after labels were written, return the source or
            # any partially created parts to their original material layout.
            for candidate in context.scene.objects:
                if candidate.type == 'MESH' and candidate.data.attributes.get(material_attribute_name):
                    self._restore_fast_materials(
                        candidate.data,
                        original_materials,
                        material_attribute_name,
                        region_attribute_name,
                        np,
                    )
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()
            if temporary_material is not None and temporary_material.users == 0:
                bpy.data.materials.remove(temporary_material)

    def _fast_topology_regions(self, mesh):
        """Partition a large, triangulated mesh in one topology pass.

        This deliberately avoids Blender RNA access inside a face/edge loop:
        ``foreach_get`` copies the geometry once and NumPy builds a compact
        adjacency table.  The growing regions are still edge-connected.  Their
        priority keeps smooth, same-material surfaces together and makes cuts
        cheaper at material boundaries, UV seams, sharp edges and corners.
        """
        try:
            import numpy as np
        except ImportError as error:
            raise RuntimeError("Esta version de Blender no incluye NumPy para la division de mallas grandes") from error

        polygon_count = len(mesh.polygons)
        if polygon_count == 0:
            return np.empty(0, dtype=np.int32), 0

        loop_starts = np.empty(polygon_count, dtype=np.int32)
        loop_totals = np.empty(polygon_count, dtype=np.int32)
        mesh.polygons.foreach_get("loop_start", loop_starts)
        mesh.polygons.foreach_get("loop_total", loop_totals)
        if not np.all(loop_totals == 3):
            raise RuntimeError("La malla grande no quedo completamente triangulada")

        loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
        loop_edges = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vertices)
        mesh.loops.foreach_get("edge_index", loop_edges)

        corner_offsets = np.arange(3, dtype=np.int32)
        corner_loops = (loop_starts[:, None] + corner_offsets).reshape(-1)
        triangles = loop_vertices[corner_loops].reshape((polygon_count, 3))

        materials = np.empty(polygon_count, dtype=np.int32)
        mesh.polygons.foreach_get("material_index", materials)
        normals = np.empty(polygon_count * 3, dtype=np.float32)
        mesh.polygons.foreach_get("normal", normals)
        normals = normals.reshape((polygon_count, 3))

        coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", coordinates)
        coordinates = coordinates.reshape((-1, 3))
        centers = (
            coordinates[triangles[:, 0]] +
            coordinates[triangles[:, 1]] +
            coordinates[triangles[:, 2]]
        ) / 3.0

        # Three undirected edges per triangle.  Adjacent equal entries after
        # sorting are manifold neighbours; a run of three or more is left
        # disconnected rather than crossing a non-manifold collision hazard.
        edge_vertices_a = np.minimum(triangles, np.roll(triangles, -1, axis=1)).reshape(-1)
        edge_vertices_b = np.maximum(triangles, np.roll(triangles, -1, axis=1)).reshape(-1)
        edge_order = np.lexsort((edge_vertices_b, edge_vertices_a))
        sorted_a = edge_vertices_a[edge_order]
        sorted_b = edge_vertices_b[edge_order]
        equal_next = (sorted_a[:-1] == sorted_a[1:]) & (sorted_b[:-1] == sorted_b[1:])
        pair_starts = equal_next.copy()
        pair_starts[1:] &= ~equal_next[:-1]
        pair_starts[:-1] &= ~equal_next[1:]

        edge_slots_a = edge_order[:-1][pair_starts]
        edge_slots_b = edge_order[1:][pair_starts]
        faces_a = (edge_slots_a // 3).astype(np.int32, copy=False)
        faces_b = (edge_slots_b // 3).astype(np.int32, copy=False)
        different_faces = faces_a != faces_b
        edge_slots_a = edge_slots_a[different_faces]
        edge_slots_b = edge_slots_b[different_faces]
        faces_a = faces_a[different_faces]
        faces_b = faces_b[different_faces]

        if len(faces_a):
            # This is the vectorised counterpart of _cut_penalty.  The edge
            # flags and active UVs are optional because old Blender builds can
            # expose some imported meshes without a usable edge/UV layer.
            penalties = np.full(len(faces_a), 20.0, dtype=np.float32)
            penalties -= (materials[faces_a] != materials[faces_b]) * 14.0

            normal_dot = np.einsum('ij,ij->i', normals[faces_a], normals[faces_b])
            normal_dot = np.clip(normal_dot, -1.0, 1.0)
            penalties += np.where(normal_dot > 0.985, 10.0, 0.0)
            penalties -= np.where(normal_dot < 0.82, 10.0, 0.0)
            penalties -= np.where((normal_dot >= 0.82) & (normal_dot < 0.94), 4.0, 0.0)

            left_loops = corner_loops[edge_slots_a]
            right_loops = corner_loops[edge_slots_b]
            left_next_loops = corner_loops[(edge_slots_a // 3) * 3 + ((edge_slots_a + 1) % 3)]
            right_next_loops = corner_loops[(edge_slots_b // 3) * 3 + ((edge_slots_b + 1) % 3)]
            edge_lengths = np.linalg.norm(
                coordinates[loop_vertices[left_loops]] - coordinates[loop_vertices[left_next_loops]],
                axis=1,
            )
            penalties += np.minimum(8.0, edge_lengths * 0.25)

            try:
                edge_seams = np.empty(len(mesh.edges), dtype=np.bool_)
                edge_sharp = np.empty(len(mesh.edges), dtype=np.bool_)
                mesh.edges.foreach_get("use_seam", edge_seams)
                mesh.edges.foreach_get("use_edge_sharp", edge_sharp)
                left_mesh_edges = loop_edges[left_loops]
                penalties -= edge_seams[left_mesh_edges] * 12.0
                penalties -= edge_sharp[left_mesh_edges] * 10.0
            except (AttributeError, RuntimeError, TypeError):
                pass

            uv_layer = mesh.uv_layers.active
            if uv_layer is not None:
                try:
                    uvs = np.empty(len(mesh.loops) * 2, dtype=np.float32)
                    uv_layer.data.foreach_get("uv", uvs)
                    uvs = uvs.reshape((-1, 2))
                    starts_match = loop_vertices[left_loops] == loop_vertices[right_loops]
                    right_for_left = np.where(starts_match, right_loops, right_next_loops)
                    right_for_next = np.where(starts_match, right_next_loops, right_loops)
                    uv_cut = (
                        np.any(np.abs(uvs[left_loops] - uvs[right_for_left]) > 0.00001, axis=1) |
                        np.any(np.abs(uvs[left_next_loops] - uvs[right_for_next]) > 0.00001, axis=1)
                    )
                    penalties -= uv_cut * 12.0
                except (AttributeError, RuntimeError, TypeError):
                    pass
            penalties = np.maximum(penalties, 0.25)

            # CSR layout: consecutive items in adjacency[start:end] are all
            # neighbours for one face.  This is far smaller and faster than a
            # Python list/dictionary per face on a two-million-face model.
            owners = np.concatenate((faces_a, faces_b))
            neighbours = np.concatenate((faces_b, faces_a))
            adjacency_penalties = np.concatenate((penalties, penalties))
            owner_order = np.argsort(owners, kind='stable')
            adjacency = neighbours[owner_order].astype(np.int32, copy=False)
            adjacency_penalties = adjacency_penalties[owner_order].astype(np.float32, copy=False)
            counts = np.bincount(owners, minlength=polygon_count)
            offsets = np.empty(polygon_count + 1, dtype=np.int64)
            offsets[0] = 0
            np.cumsum(counts, out=offsets[1:])
        else:
            adjacency = np.empty(0, dtype=np.int32)
            adjacency_penalties = np.empty(0, dtype=np.float32)
            offsets = np.zeros(polygon_count + 1, dtype=np.int64)

        # Start each new component in a deterministic spatial order rather
        # than by arbitrary imported polygon order.  The priority queue then
        # grows an edge-connected, compact region from that seed.
        bounds_min = centers.min(axis=0)
        bounds_span = np.maximum(centers.max(axis=0) - bounds_min, 0.00001)
        quantized_centers = np.clip(
            ((centers - bounds_min) / bounds_span * 1023.0).astype(np.uint32),
            0,
            1023,
        )
        seed_order = np.argsort(self._morton_3d(quantized_centers), kind='stable')
        spatial_scale = max(float(np.linalg.norm(bounds_span)), 0.001)

        labels = np.full(polygon_count, -1, dtype=np.int32)
        seed_position = 0
        region_index = 0
        max_material_triangles = self.MAX_BATCH_TRIANGLES

        while seed_position < polygon_count:
            while seed_position < polygon_count and labels[seed_order[seed_position]] >= 0:
                seed_position += 1
            if seed_position >= polygon_count:
                break

            seed = int(seed_order[seed_position])
            labels[seed] = region_index
            region_triangles = 1
            region_vertices = set(int(vertex) for vertex in triangles[seed])
            material_counts = {int(materials[seed]): 1}
            seed_center = centers[seed]
            frontier_costs = {}
            frontier = []

            def add_frontier(face_index, edge_cost):
                if labels[face_index] >= 0:
                    return
                cost = frontier_costs.get(face_index, 0.0) + float(edge_cost)
                frontier_costs[face_index] = cost
                distance = float(np.linalg.norm(centers[face_index] - seed_center)) / spatial_scale
                heapq.heappush(frontier, (-(cost - distance * 1.5), face_index, cost))

            def add_neighbours(face_index):
                for adjacency_index in range(offsets[face_index], offsets[face_index + 1]):
                    add_frontier(
                        int(adjacency[adjacency_index]),
                        adjacency_penalties[adjacency_index],
                    )

            add_neighbours(seed)
            while frontier:
                _, candidate, queued_cost = heapq.heappop(frontier)
                if labels[candidate] >= 0 or frontier_costs.get(candidate) != queued_cost:
                    continue

                material_index = int(materials[candidate])
                if (
                    region_triangles >= self.MAX_GROUP_TRIANGLES
                    or material_counts.get(material_index, 0) >= max_material_triangles
                ):
                    continue

                candidate_vertices = triangles[candidate]
                added_vertex_count = sum(
                    int(vertex) not in region_vertices for vertex in candidate_vertices
                )
                if len(region_vertices) + added_vertex_count > self.MAX_VERTICES:
                    continue

                labels[candidate] = region_index
                region_triangles += 1
                material_counts[material_index] = material_counts.get(material_index, 0) + 1
                region_vertices.update(int(vertex) for vertex in candidate_vertices)
                add_neighbours(candidate)

            region_index += 1

        return labels, region_index

    @staticmethod
    def _fast_region_values(mesh, attribute_name, np):
        attribute = mesh.attributes.get(attribute_name)
        if attribute is None:
            raise RuntimeError("Blender no conservo las etiquetas internas de division")
        values = np.empty(len(mesh.polygons), dtype=np.int32)
        attribute.data.foreach_get("value", values)
        return values

    @staticmethod
    def _remove_fast_region_attribute(mesh, attribute_name):
        attribute = mesh.attributes.get(attribute_name)
        if attribute is not None:
            mesh.attributes.remove(attribute)

    def _select_fast_region(self, mesh, region_index, np):
        values = self._fast_region_values(mesh, self.FAST_REGION_ATTRIBUTE, np)
        selection = values == region_index
        if not np.any(selection):
            return False

        # Face selection alone is not synchronised into Edit mode on every
        # Blender 3.4 build.  Set its vertices and edges in bulk as well; this
        # is equivalent to _select_only_faces but avoids one Python iteration
        # per mesh element for every generated WMO group.
        loop_starts = np.empty(len(mesh.polygons), dtype=np.int32)
        loop_totals = np.empty(len(mesh.polygons), dtype=np.int32)
        mesh.polygons.foreach_get("loop_start", loop_starts)
        mesh.polygons.foreach_get("loop_total", loop_totals)
        loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
        loop_edges = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vertices)
        mesh.loops.foreach_get("edge_index", loop_edges)

        # A mesh stores polygon loops contiguously.  Retain the explicit
        # starts fallback for imported meshes whose loop layout is unusual.
        if np.array_equal(loop_starts, np.cumsum(np.r_[0, loop_totals[:-1]])):
            selected_loops = np.repeat(selection, loop_totals)
        else:
            selected_loops = np.zeros(len(mesh.loops), dtype=np.bool_)
            for polygon_index in np.flatnonzero(selection):
                start = loop_starts[polygon_index]
                selected_loops[start:start + loop_totals[polygon_index]] = True

        selected_vertices = np.zeros(len(mesh.vertices), dtype=np.bool_)
        selected_edges = np.zeros(len(mesh.edges), dtype=np.bool_)
        selected_vertices[loop_vertices[selected_loops]] = True
        selected_edges[loop_edges[selected_loops]] = True
        mesh.vertices.foreach_set("select", selected_vertices)
        mesh.edges.foreach_set("select", selected_edges)
        mesh.polygons.foreach_set("select", selection.astype(np.bool_, copy=False))
        mesh.update()
        return True

    def _fast_split_large_mesh(self, context, obj, original_name, triangulate_status):
        """Separate precomputed large-mesh regions without topology rebuilds."""
        try:
            import numpy as np
        except ImportError:
            self.report({'ERROR'}, "NumPy no esta disponible para dividir esta malla grande")
            return {'CANCELLED'}

        window_manager = context.window_manager
        window_manager.progress_begin(0, 100)
        try:
            labels, region_count = self._fast_topology_regions(obj.data)
            if region_count <= 1:
                self._part_name_and_properties(obj, original_name, 1)
                self.report({'INFO'}, f"Objeto {triangulate_status} y listo para WMO")
                return {'FINISHED'}

            # Generic face attributes are copied by Blender's Separate
            # operation, so they are a stable identity even after polygon
            # indices are compacted in the remaining object.
            old_attribute = obj.data.attributes.get(self.FAST_REGION_ATTRIBUTE)
            if old_attribute is not None:
                obj.data.attributes.remove(old_attribute)
            region_attribute = obj.data.attributes.new(
                self.FAST_REGION_ATTRIBUTE,
                'INT',
                'FACE',
            )
            region_attribute.data.foreach_set("value", labels)
            del labels
            obj.data.update()
            window_manager.progress_update(35)

            created_parts = []
            remaining = obj
            for region_index in range(region_count):
                values = self._fast_region_values(
                    remaining.data,
                    self.FAST_REGION_ATTRIBUTE,
                    np,
                )
                if np.all(values == region_index):
                    self._part_name_and_properties(
                        remaining,
                        original_name,
                        len(created_parts) + 1,
                    )
                    created_parts.append(remaining)
                    break

                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.select_all(action='DESELECT')
                remaining.select_set(True)
                context.view_layer.objects.active = remaining
                if not self._select_fast_region(remaining.data, region_index, np):
                    raise RuntimeError(f"No se encontro la region WMO {region_index + 1}")

                previous_objects = set(context.scene.objects)
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_mode(type='FACE')
                bpy.ops.mesh.separate(type='SELECTED')
                bpy.ops.object.mode_set(mode='OBJECT')

                candidates = [
                    candidate for candidate in context.selected_objects
                    if candidate.type == 'MESH' and len(candidate.data.polygons) > 0
                ]
                if len(candidates) < 2:
                    candidates = [
                        candidate for candidate in context.scene.objects
                        if candidate.type == 'MESH' and len(candidate.data.polygons) > 0 and (
                            candidate is remaining or candidate not in previous_objects
                        )
                    ]

                region_part = None
                next_remaining = None
                candidate_details = []
                for candidate in candidates:
                    candidate_values = self._fast_region_values(
                        candidate.data,
                        self.FAST_REGION_ATTRIBUTE,
                        np,
                    )
                    candidate_details.append(
                        f"{candidate.name} ({len(candidate_values)} caras, "
                        f"etiquetas {int(candidate_values.min())}-{int(candidate_values.max())})"
                    )
                    if np.all(candidate_values == region_index):
                        region_part = candidate
                    else:
                        next_remaining = candidate

                if region_part is None or next_remaining is None:
                    raise RuntimeError(
                        "Blender no devolvio una separacion WMO valida: " + "; ".join(candidate_details)
                    )

                self._part_name_and_properties(
                    region_part,
                    original_name,
                    len(created_parts) + 1,
                )
                created_parts.append(region_part)
                remaining = next_remaining
                window_manager.progress_update(35 + int(55 * (region_index + 1) / region_count))

            if not created_parts or remaining not in created_parts:
                raise RuntimeError("La ultima region WMO no se pudo finalizar")

            invalid_parts = []
            for part in created_parts:
                self._remove_fast_region_attribute(part.data, self.FAST_REGION_ATTRIBUTE)
                verts, tris, max_batch_tris = self._object_wmo_stats(part)
                violations = self._wmo_limit_violations(verts, tris, max_batch_tris)
                if violations:
                    invalid_parts.append(f"{part.name}: {', '.join(violations)}")

            if invalid_parts:
                self.report({'ERROR'}, "Piezas fuera de limite: " + " | ".join(invalid_parts[:3]))
                return {'FINISHED'}

            bpy.ops.object.select_all(action='DESELECT')
            for part in created_parts:
                part.select_set(True)
            context.view_layer.objects.active = created_parts[0]
            self.report({'INFO'}, (
                f"'{original_name}' {triangulate_status} y dividido en {len(created_parts)} sub-grupos WMO "
                f"con topologia analizada una sola vez"
            ))
            return {'FINISHED'}
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()

    def _loose_component_stats(self, obj, np):
        """Return WMO limits and a compact spatial key for one loose island."""
        mesh = obj.data
        material_indices = np.empty(len(mesh.polygons), dtype=np.int32)
        mesh.polygons.foreach_get("material_index", material_indices)
        unique_materials, material_counts = np.unique(material_indices, return_counts=True)
        counts_by_material = {}
        for material_index, count in zip(unique_materials, material_counts):
            material_index = int(material_index)
            material = mesh.materials[material_index] if material_index < len(mesh.materials) else None
            # The material datablock, not a slot number local to this object,
            # identifies a future WMO batch when loose parts are joined.
            material_key = (
                ("material", material.as_pointer()) if material else ("empty", material_index)
            )
            counts_by_material[material_key] = int(count)

        center = sum((obj.matrix_world @ Vector(corner) for corner in obj.bound_box), Vector()) / 8.0
        return {
            "object": obj,
            "vertices": len(mesh.vertices),
            "triangles": len(mesh.polygons),
            "materials": counts_by_material,
            "center": center,
        }

    def _loose_stats_fit(self, stats):
        return self._fits_wmo_limits(
            stats["vertices"],
            stats["triangles"],
            max(stats["materials"].values(), default=0),
        )

    def _can_add_loose_component(self, group_vertices, group_triangles,
                                 group_materials, stats):
        if group_vertices + stats["vertices"] > self.MAX_VERTICES:
            return False
        if group_triangles + stats["triangles"] > self.MAX_GROUP_TRIANGLES:
            return False
        return all(
            group_materials.get(material, 0) + count <= self.MAX_BATCH_TRIANGLES
            for material, count in stats["materials"].items()
        )

    def _ordered_loose_components(self, components, np):
        """Order whole islands spatially; no face is ever divided here."""
        if len(components) < 2:
            return components
        centers = np.asarray([tuple(item["center"]) for item in components], dtype=np.float32)
        bounds_min = centers.min(axis=0)
        bounds_span = np.maximum(centers.max(axis=0) - bounds_min, 0.00001)
        quantized_centers = np.clip(
            ((centers - bounds_min) / bounds_span * 1023.0).astype(np.uint32),
            0,
            1023,
        )
        order = np.argsort(self._morton_3d(quantized_centers), kind='stable')
        return [components[int(index)] for index in order]

    def _separate_loose_components(self, context, obj):
        """Run Blender's compiled loose-parts split once for the full model."""
        before_objects = set(context.scene.objects)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')

        parts = [
            candidate for candidate in context.selected_objects
            if candidate.type == 'MESH' and len(candidate.data.polygons) > 0
        ]
        if not parts:
            parts = [
                candidate for candidate in context.scene.objects
                if candidate.type == 'MESH' and len(candidate.data.polygons) > 0 and (
                    candidate is obj or candidate not in before_objects
                )
            ]
        return parts

    def _fast_split_large_mesh_by_loose_objects(self, context, obj, original_name, triangulate_status):
        """Preserve loose architectural pieces, then pack them into WMO groups.

        The first operation is Blender's native loose-parts separator.  A
        column, arch, window or prop that is disconnected in the source remains
        whole.  Nearby whole islands are joined only when their combined WMO
        vertex, triangle and material-batch limits permit it.  The former
        spatial face splitter is retained exclusively as a fallback for one
        *single connected island* that exceeds a WMO limit by itself.
        """
        try:
            import numpy as np
        except ImportError:
            self.report({'ERROR'}, "NumPy no esta disponible para dividir esta malla grande")
            return {'CANCELLED'}

        if obj.data.users > 1:
            obj.data = obj.data.copy()

        window_manager = context.window_manager
        window_manager.progress_begin(0, 100)
        try:
            loose_parts = self._separate_loose_components(context, obj)
            if not loose_parts:
                raise RuntimeError("Blender no devolvio piezas sueltas para dividir")
            window_manager.progress_update(35)

            safe_components = []
            oversized_components = []
            for loose_part in loose_parts:
                stats = self._loose_component_stats(loose_part, np)
                if self._loose_stats_fit(stats):
                    safe_components.append(stats)
                else:
                    oversized_components.append(loose_part)

            # A component too large to be a WMO group cannot be preserved as
            # one object.  Only this exceptional component reaches the compact
            # spatial fallback; independent columns never do.
            completed_parts = []
            for component_index, oversized in enumerate(oversized_components, start=1):
                component_name = f"{original_name}_isla_grande_{component_index}"
                result = self._fast_split_spatial_mesh_bulk(
                    context,
                    oversized,
                    component_name,
                    "ya triangulado",
                )
                if result != {'FINISHED'}:
                    return result
                completed_parts.extend([
                    candidate for candidate in context.scene.objects
                    if candidate.type == 'MESH' and candidate.get("wow_atajos_wmo_source") == component_name
                ])

            ordered_components = self._ordered_loose_components(safe_components, np)
            packed_groups = []
            current_group = []
            group_vertices = 0
            group_triangles = 0
            group_materials = {}
            for stats in ordered_components:
                if current_group and not self._can_add_loose_component(
                    group_vertices,
                    group_triangles,
                    group_materials,
                    stats,
                ):
                    packed_groups.append(current_group)
                    current_group = []
                    group_vertices = 0
                    group_triangles = 0
                    group_materials = {}

                current_group.append(stats)
                group_vertices += stats["vertices"]
                group_triangles += stats["triangles"]
                for material, count in stats["materials"].items():
                    group_materials[material] = group_materials.get(material, 0) + count
            if current_group:
                packed_groups.append(current_group)

            for group_index, group in enumerate(packed_groups, start=1):
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.select_all(action='DESELECT')
                group_objects = [stats["object"] for stats in group]
                for group_object in group_objects:
                    group_object.select_set(True)
                context.view_layer.objects.active = group_objects[0]
                if len(group_objects) > 1:
                    bpy.ops.object.join()
                completed_parts.append(context.view_layer.objects.active)
                window_manager.progress_update(35 + int(60 * group_index / max(1, len(packed_groups))))

            if not completed_parts:
                raise RuntimeError("No se pudo formar ningun sub-grupo WMO")

            # Result names are deliberately assigned only after every join, so
            # they remain sequential even if one oversized island used fallback.
            completed_parts = list(dict.fromkeys(completed_parts))
            completed_parts.sort(key=lambda part: part.name)
            for part_index, part in enumerate(completed_parts, start=1):
                self._part_name_and_properties(part, original_name, part_index)

            bpy.ops.object.select_all(action='DESELECT')
            for part in completed_parts:
                part.select_set(True)
            context.view_layer.objects.active = completed_parts[0]
            window_manager.progress_update(100)
            self.report({'INFO'}, (
                f"'{original_name}' {triangulate_status} y dividido en {len(completed_parts)} sub-grupos WMO "
                f"con islas completas preservadas"
            ))
            return {'FINISHED'}
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()

    def _mesh_island_face_components(self, context, obj, np):
        """Return a dense connected-island index for every triangle face.

        Geometry Nodes calculates mesh islands in Blender's compiled geometry
        code.  This avoids both the Python graph walk and creating thousands of
        temporary objects with ``Separate by Loose Parts``.
        """
        mesh = obj.data
        attribute_name = self._temporary_attribute_name(mesh, "_wow_atajos_wmo_island")
        node_group = bpy.data.node_groups.new("_WOW_Atajos_Mesh_Islands", 'GeometryNodeTree')
        modifier = None
        try:
            node_group.inputs.new('NodeSocketGeometry', 'Geometry')
            node_group.outputs.new('NodeSocketGeometry', 'Geometry')
            nodes = node_group.nodes
            links = node_group.links
            group_input = nodes.new('NodeGroupInput')
            group_output = nodes.new('NodeGroupOutput')
            island = nodes.new('GeometryNodeInputMeshIsland')
            store = nodes.new('GeometryNodeStoreNamedAttribute')
            store.data_type = 'INT'
            store.domain = 'POINT'
            store.inputs['Name'].default_value = attribute_name
            integer_value_socket = next(
                socket for socket in store.inputs if socket.identifier == 'Value_Int'
            )
            links.new(group_input.outputs['Geometry'], store.inputs['Geometry'])
            links.new(island.outputs['Island Index'], integer_value_socket)
            links.new(store.outputs['Geometry'], group_output.inputs['Geometry'])

            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            modifier = obj.modifiers.new("_WOW_Atajos_Mesh_Islands", 'NODES')
            modifier.node_group = node_group
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            modifier = None
        finally:
            if modifier is not None:
                obj.modifiers.remove(modifier)
            if node_group.users == 0:
                bpy.data.node_groups.remove(node_group)

        mesh = obj.data
        island_attribute = mesh.attributes.get(attribute_name)
        if island_attribute is None:
            raise RuntimeError("Blender no pudo calcular las islas conectadas de la malla")

        vertex_islands = np.empty(len(mesh.vertices), dtype=np.int32)
        island_attribute.data.foreach_get("value", vertex_islands)
        mesh.attributes.remove(island_attribute)

        loop_starts = np.empty(len(mesh.polygons), dtype=np.int32)
        loop_totals = np.empty(len(mesh.polygons), dtype=np.int32)
        mesh.polygons.foreach_get("loop_start", loop_starts)
        mesh.polygons.foreach_get("loop_total", loop_totals)
        if not np.all(loop_totals == 3):
            raise RuntimeError("La malla grande no quedo completamente triangulada")
        loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vertices)

        _, vertex_components = np.unique(vertex_islands, return_inverse=True)
        vertex_components = vertex_components.astype(np.int32, copy=False)
        face_components = vertex_components[loop_vertices[loop_starts]]
        component_count = int(vertex_components.max()) + 1 if len(vertex_components) else 0
        faces_per_component = np.bincount(face_components, minlength=component_count)
        vertices_per_component = np.bincount(vertex_components, minlength=component_count)

        coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", coordinates)
        coordinates = coordinates.reshape((-1, 3))
        component_centers = np.zeros((component_count, 3), dtype=np.float64)
        np.add.at(component_centers, vertex_components, coordinates)
        component_centers /= np.maximum(vertices_per_component[:, None], 1)
        mesh.update()
        return (
            face_components,
            faces_per_component,
            component_centers.astype(np.float32),
            loop_starts,
            loop_vertices,
            coordinates,
        )

    def _island_aware_regions(self, context, obj):
        """Assign WMO group IDs while keeping all safe mesh islands whole."""
        try:
            import numpy as np
        except ImportError as error:
            raise RuntimeError("Esta version de Blender no incluye NumPy para la division de mallas grandes") from error

        (
            face_components,
            faces_per_component,
            component_centers,
            loop_starts,
            loop_vertices,
            coordinates,
        ) = self._mesh_island_face_components(context, obj, np)
        triangle_cap = min(
            self.MAX_BATCH_TRIANGLES,
            self.MAX_GROUP_TRIANGLES,
            self.MAX_VERTICES // 3,
        )
        labels = np.full(len(face_components), -1, dtype=np.int32)
        component_count = len(faces_per_component)
        small_components = np.flatnonzero(faces_per_component <= triangle_cap)

        if len(small_components):
            centers = component_centers[small_components]
            bounds_min = centers.min(axis=0)
            bounds_span = np.maximum(centers.max(axis=0) - bounds_min, 0.00001)
            quantized_centers = np.clip(
                ((centers - bounds_min) / bounds_span * 1023.0).astype(np.uint32),
                0,
                1023,
            )
            component_order = small_components[
                np.argsort(self._morton_3d(quantized_centers), kind='stable')
            ]
        else:
            component_order = np.empty(0, dtype=np.int32)

        group_index = -1
        group_triangles = 0
        for component_index in component_order:
            triangle_count = int(faces_per_component[component_index])
            if group_index < 0 or group_triangles + triangle_count > triangle_cap:
                group_index += 1
                group_triangles = 0
            labels[face_components == component_index] = group_index
            group_triangles += triangle_count

        # Only an island that cannot fit in a WMO group gets cut.  Its faces
        # are kept spatially compact, but independent columns/arcs never enter
        # this fallback because their whole island was labelled above.
        large_components = np.flatnonzero(faces_per_component > triangle_cap)
        for component_index in large_components:
            face_indices = np.flatnonzero(face_components == component_index)
            face_loop_indices = (
                loop_starts[face_indices, None] + np.arange(3, dtype=np.int32)
            ).reshape(-1)
            triangles = loop_vertices[face_loop_indices].reshape((-1, 3))
            centers = coordinates[triangles[:, 0]].copy()
            centers += coordinates[triangles[:, 1]]
            centers += coordinates[triangles[:, 2]]
            centers *= (1.0 / 3.0)
            bounds_min = centers.min(axis=0)
            bounds_span = np.maximum(centers.max(axis=0) - bounds_min, 0.00001)
            quantized_centers = np.clip(
                ((centers - bounds_min) / bounds_span * 1023.0).astype(np.uint32),
                0,
                1023,
            )
            order = np.argsort(self._morton_3d(quantized_centers), kind='stable')
            local_groups = np.arange(len(face_indices), dtype=np.int32) // triangle_cap
            labels[face_indices[order]] = group_index + 1 + local_groups
            group_index += int(local_groups[-1]) + 1

        if np.any(labels < 0):
            raise RuntimeError("No se pudo etiquetar todas las caras de la malla")
        return labels, group_index + 1

    def _bulk_separate_labeled_mesh(self, context, obj, labels, region_count,
                                    original_name, triangulate_status, summary):
        """Separate all precomputed face labels at once and restore materials."""
        try:
            import numpy as np
        except ImportError:
            self.report({'ERROR'}, "NumPy no esta disponible para dividir esta malla grande")
            return {'CANCELLED'}

        mesh = obj.data
        original_materials = list(mesh.materials)
        region_attribute_name = self._temporary_attribute_name(mesh, self.FAST_REGION_ATTRIBUTE)
        material_attribute_name = self._temporary_attribute_name(
            mesh,
            self.FAST_ORIGINAL_MATERIAL_ATTRIBUTE,
        )
        temporary_material = None
        window_manager = context.window_manager
        window_manager.progress_begin(0, 100)
        try:
            if region_count <= 1:
                self._part_name_and_properties(obj, original_name, 1)
                self.report({'INFO'}, f"Objeto {triangulate_status} y listo para WMO")
                return {'FINISHED'}

            original_indices = np.empty(len(mesh.polygons), dtype=np.int32)
            mesh.polygons.foreach_get("material_index", original_indices)
            material_attribute = mesh.attributes.new(material_attribute_name, 'INT', 'FACE')
            material_attribute.data.foreach_set("value", original_indices)
            region_attribute = mesh.attributes.new(region_attribute_name, 'INT', 'FACE')
            region_attribute.data.foreach_set("value", labels)
            del labels, original_indices
            window_manager.progress_update(35)

            slot_material = next((material for material in original_materials if material), None)
            if slot_material is None:
                temporary_material = bpy.data.materials.new("_WOW_Atajos_Temporal")
                slot_material = temporary_material
            while len(mesh.materials) < region_count:
                mesh.materials.append(slot_material)
            mesh.polygons.foreach_set("material_index", self._fast_region_values(
                mesh,
                region_attribute_name,
                np,
            ))
            mesh.update()
            window_manager.progress_update(50)

            before_objects = set(context.scene.objects)
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')
            window_manager.progress_update(80)

            parts = [
                candidate for candidate in context.selected_objects
                if candidate.type == 'MESH' and candidate.data.attributes.get(region_attribute_name)
            ]
            if len(parts) != region_count:
                parts = [
                    candidate for candidate in context.scene.objects
                    if candidate.type == 'MESH' and candidate.data.attributes.get(region_attribute_name) and (
                        candidate is obj or candidate not in before_objects
                    )
                ]
            if len(parts) != region_count:
                raise RuntimeError(
                    f"Blender devolvio {len(parts)} grupos y se esperaban {region_count}"
                )

            ordered_parts = []
            for part in parts:
                region_values = self._fast_region_values(part.data, region_attribute_name, np)
                if not len(region_values) or not np.all(region_values == region_values[0]):
                    raise RuntimeError("Una pieza WMO contiene etiquetas de region mezcladas")
                ordered_parts.append((int(region_values[0]), part))
            ordered_parts.sort(key=lambda item: item[0])

            for part_index, (_, part) in enumerate(ordered_parts, start=1):
                self._restore_fast_materials(
                    part.data,
                    original_materials,
                    material_attribute_name,
                    region_attribute_name,
                    np,
                )
                self._part_name_and_properties(part, original_name, part_index)

            parts = [part for _, part in ordered_parts]
            bpy.ops.object.select_all(action='DESELECT')
            for part in parts:
                part.select_set(True)
            context.view_layer.objects.active = parts[0]
            window_manager.progress_update(100)
            self.report({'INFO'}, f"'{original_name}' {triangulate_status} y dividido en {len(parts)} sub-grupos WMO {summary}")
            return {'FINISHED'}
        except RuntimeError as error:
            for candidate in context.scene.objects:
                if candidate.type == 'MESH' and candidate.data.attributes.get(material_attribute_name):
                    self._restore_fast_materials(
                        candidate.data,
                        original_materials,
                        material_attribute_name,
                        region_attribute_name,
                        np,
                    )
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            window_manager.progress_end()
            if temporary_material is not None and temporary_material.users == 0:
                bpy.data.materials.remove(temporary_material)

    def _fast_split_large_mesh_bulk(self, context, obj, original_name, triangulate_status):
        """Fast WMO split that keeps every fitting connected island intact."""
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        try:
            labels, region_count = self._island_aware_regions(context, obj)
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return self._bulk_separate_labeled_mesh(
            context,
            obj,
            labels,
            region_count,
            original_name,
            triangulate_status,
            "con islas conectadas completas preservadas",
        )

    def execute(self, context):
        import bmesh

        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Selecciona un objeto Mesh activo")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        triangulated_faces = self._triangulate_object(obj, bmesh)
        if not obj.data.polygons:
            self.report({'ERROR'}, "El objeto no tiene caras para triangular ni dividir")
            return {'CANCELLED'}
        triangulate_status = "triangulado" if triangulated_faces else "ya triangulado"
        original_name = obj.name

        if len(obj.data.polygons) >= self.FAST_SPLIT_THRESHOLD:
            return self._fast_split_large_mesh_bulk(
                context,
                obj,
                original_name,
                triangulate_status,
            )

        total_verts, total_tris, max_batch_tris = self._object_wmo_stats(obj)

        _, initial_components = self._build_face_topology(obj.data)
        if self._fits_wmo_limits(total_verts, total_tris, max_batch_tris) and len(initial_components) == 1:
            self.report({'INFO'}, (
                f"Objeto {triangulate_status} y listo para WMO "
                f"({total_verts:,} vertices, {total_tris:,} tris, "
                f"max batch {max_batch_tris:,} tris)"
            ))
            return {'FINISHED'}

        part_index = 1
        pending_parts = [obj]
        created_parts = []
        max_iterations = max(1000, len(obj.data.polygons) + 10)
        iterations = 0

        while pending_parts:
            iterations += 1
            if iterations > max_iterations:
                self.report({'ERROR'}, "Division WMO cancelada: demasiadas iteraciones")
                return {'CANCELLED'}

            current_obj = pending_parts.pop(0)
            verts, tris, max_batch_tris = self._object_wmo_stats(current_obj)
            _, components = self._build_face_topology(current_obj.data)

            if self._fits_wmo_limits(verts, tris, max_batch_tris) and len(components) == 1:
                self._part_name_and_properties(current_obj, original_name, part_index)
                created_parts.append(current_obj)
                part_index += 1
                continue

            try:
                first_group, _ = self._next_wmo_region(current_obj.data)
            except RuntimeError as error:
                self.report({'ERROR'}, str(error))
                return {'CANCELLED'}

            group_stats = self._mesh_wmo_stats(current_obj.data, first_group)
            if not self._fits_wmo_limits(*group_stats):
                self.report({'ERROR'}, "No se puede dividir mas el objeto: una region conectada excede un limite WMO")
                return {'CANCELLED'}

            # ── Seleccionar caras del primer grupo y separar ──
            previous_objects = set(context.scene.objects)
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            current_obj.select_set(True)
            context.view_layer.objects.active = current_obj
            self._select_only_faces(current_obj, first_group)

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type='FACE')
            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.mode_set(mode='OBJECT')

            split_objects = [
                split_obj for split_obj in context.selected_objects
                if split_obj.type == 'MESH' and len(split_obj.data.polygons) > 0
            ]
            if len(split_objects) < 2:
                split_objects = [
                    split_obj for split_obj in context.scene.objects
                    if split_obj.type == 'MESH' and (
                        split_obj is current_obj or split_obj not in previous_objects
                    ) and len(split_obj.data.polygons) > 0
                ]

            if len(split_objects) < 2:
                self.report({'ERROR'}, "Blender no devolvio los dos sub-grupos separados")
                return {'CANCELLED'}

            for split_obj in split_objects:
                pending_parts.append(split_obj)

        invalid_parts = []
        for part in created_parts:
            verts, tris, max_batch_tris = self._object_wmo_stats(part)
            violations = self._wmo_limit_violations(verts, tris, max_batch_tris)
            if violations:
                invalid_parts.append(f"{part.name}: {', '.join(violations)}")

        if invalid_parts:
            self.report({'ERROR'}, "Piezas fuera de limite: " + " | ".join(invalid_parts[:3]))
            return {'FINISHED'}

        bpy.ops.object.select_all(action='DESELECT')
        for part in created_parts:
            part.select_set(True)
        if created_parts:
            context.view_layer.objects.active = created_parts[0]

        self.report({'INFO'}, (
            f"'{original_name}' {triangulate_status} y dividido en {len(created_parts)} sub-grupos WMO "
            f"(max {self.MAX_VERTICES:,} vertices, {self.MAX_GROUP_TRIANGLES:,} tris, "
            f"{self.MAX_BATCH_TRIANGLES:,} tris/material; piezas conectadas y cortes por seams/corners)"
        ))
        return {'FINISHED'}


# =====================================================
# OPERADOR – Dividir objeto en Sub-grupos WMO (Rápido)
# Copia exacta de la version antigua: division greedy por orden de caras,
# imprecisa pero muy rapida.
# =====================================================

class OBJECT_OT_dividir_wmo_rapido(bpy.types.Operator):
    bl_idname = "object.dividir_wmo_rapido"
    bl_label = "Triangular y Dividir (Rápido)"
    bl_description = (
        "Triangula y divide de forma imprecisa pero en poco tiempo. "
        "Rapido para piezas grandes"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # MOVI stores vertex indices as uint16 and MOBA stores num_indices as uint16.
    # 20k triangles = 60k indices, leaving room below 65,535 per material batch.
    MAX_VERTICES = 60000
    MAX_GROUP_TRIANGLES = 60000
    MAX_BATCH_TRIANGLES = 20000

    def _wmo_stats(self, bm):
        used_verts = set()
        total_tris = 0
        tris_by_material = {}

        for face in bm.faces:
            face_tris = max(0, len(face.verts) - 2)
            total_tris += face_tris
            mat_index = face.material_index
            tris_by_material[mat_index] = tris_by_material.get(mat_index, 0) + face_tris
            used_verts.update(v.index for v in face.verts)

        max_batch_tris = max(tris_by_material.values(), default=0)
        return len(used_verts), total_tris, max_batch_tris

    def _object_wmo_stats(self, obj, bmesh):
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            bm.faces.index_update()
            bm.verts.index_update()
            return self._wmo_stats(bm)
        finally:
            bm.free()

    def _triangulate_object(self, obj, bmesh):
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            faces_to_triangulate = [face for face in bm.faces if len(face.verts) != 3]
            if not faces_to_triangulate:
                return 0

            bmesh.ops.triangulate(
                bm,
                faces=faces_to_triangulate,
                quad_method='BEAUTY',
                ngon_method='BEAUTY',
            )
            bm.to_mesh(obj.data)
            obj.data.update()
            return len(faces_to_triangulate)
        finally:
            bm.free()

    def _fits_wmo_limits(self, verts, total_tris, max_batch_tris):
        return (
            verts <= self.MAX_VERTICES and
            total_tris <= self.MAX_GROUP_TRIANGLES and
            max_batch_tris <= self.MAX_BATCH_TRIANGLES
        )

    def _wmo_limit_violations(self, verts, total_tris, max_batch_tris):
        violations = []
        if verts > self.MAX_VERTICES:
            violations.append(f"{verts:,} vertices")
        if total_tris > self.MAX_GROUP_TRIANGLES:
            violations.append(f"{total_tris:,} tris")
        if max_batch_tris > self.MAX_BATCH_TRIANGLES:
            violations.append(f"{max_batch_tris:,} tris en un material")
        return violations

    def _select_only_faces(self, obj, face_indices):
        face_indices = set(face_indices)
        mesh = obj.data

        for vert in mesh.vertices:
            vert.select = False
        for edge in mesh.edges:
            edge.select = False
        for poly in mesh.polygons:
            poly.select = poly.index in face_indices

        mesh.update()

    def execute(self, context):
        import bmesh

        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Selecciona un objeto Mesh activo")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        triangulated_faces = self._triangulate_object(obj, bmesh)
        total_verts, total_tris, max_batch_tris = self._object_wmo_stats(obj, bmesh)
        triangulate_status = "triangulado" if triangulated_faces else "ya triangulado"

        if self._fits_wmo_limits(total_verts, total_tris, max_batch_tris):
            self.report({'INFO'}, (
                f"Objeto {triangulate_status} y listo para WMO "
                f"({total_verts:,} vertices, {total_tris:,} tris, "
                f"max batch {max_batch_tris:,} tris)"
            ))
            return {'FINISHED'}

        original_name = obj.name
        part_index = 1
        pending_parts = [obj]
        created_parts = []
        max_iterations = max(1000, len(obj.data.polygons) + 10)
        iterations = 0

        while pending_parts:
            iterations += 1
            if iterations > max_iterations:
                self.report({'ERROR'}, "Division WMO cancelada: demasiadas iteraciones")
                return {'CANCELLED'}

            current_obj = pending_parts.pop(0)
            verts, tris, max_batch_tris = self._object_wmo_stats(current_obj, bmesh)

            if self._fits_wmo_limits(verts, tris, max_batch_tris):
                current_obj.name = f"{original_name}_WMO_{part_index}"
                created_parts.append(current_obj)
                part_index += 1
                continue
            # ── Recalcular stats del objeto restante ──────────
            bm = bmesh.new()
            bm.from_mesh(current_obj.data)
            bm.faces.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            bm.faces.index_update()
            bm.verts.index_update()

            # ── Calcular primer grupo de caras (greedy) ───────
            first_group = []
            cv = set()   # vértices acumulados
            ct = 0       # triángulos acumulados en el grupo
            ct_by_material = {}

            for face in bm.faces:
                ft = max(0, len(face.verts) - 2)
                mat_index = face.material_index
                fv = {v.index for v in face.verts}
                nv = fv - cv
                material_tris = ct_by_material.get(mat_index, 0)

                if first_group and (
                    len(cv) + len(nv) > self.MAX_VERTICES or
                    ct + ft > self.MAX_GROUP_TRIANGLES or
                    material_tris + ft > self.MAX_BATCH_TRIANGLES
                ):
                    break  # Grupo lleno → separar aquí

                first_group.append(face.index)
                cv |= fv
                ct += ft
                ct_by_material[mat_index] = material_tris + ft

            bm.free()

            if not first_group:
                self.report({'ERROR'}, "No se puede dividir mas el objeto (cara individual supera el limite)")
                return {'CANCELLED'}

            # ── Seleccionar caras del primer grupo y separar ──
            previous_objects = set(context.scene.objects)
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            current_obj.select_set(True)
            context.view_layer.objects.active = current_obj
            self._select_only_faces(current_obj, first_group)

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type='FACE')
            bpy.ops.mesh.separate(type='SELECTED')
            bpy.ops.object.mode_set(mode='OBJECT')

            split_objects = [
                split_obj for split_obj in context.selected_objects
                if split_obj.type == 'MESH' and len(split_obj.data.polygons) > 0
            ]
            if len(split_objects) < 2:
                split_objects = [
                    split_obj for split_obj in context.scene.objects
                    if split_obj.type == 'MESH' and (
                        split_obj is current_obj or split_obj not in previous_objects
                    ) and len(split_obj.data.polygons) > 0
                ]

            if len(split_objects) < 2:
                self.report({'ERROR'}, "Blender no devolvio los dos sub-grupos separados")
                return {'CANCELLED'}

            for split_obj in split_objects:
                verts, tris, max_batch_tris = self._object_wmo_stats(split_obj, bmesh)
                if self._fits_wmo_limits(verts, tris, max_batch_tris):
                    split_obj.name = f"{original_name}_WMO_{part_index}"
                    created_parts.append(split_obj)
                    part_index += 1
                else:
                    pending_parts.append(split_obj)

        invalid_parts = []
        for part in created_parts:
            verts, tris, max_batch_tris = self._object_wmo_stats(part, bmesh)
            violations = self._wmo_limit_violations(verts, tris, max_batch_tris)
            if violations:
                invalid_parts.append(f"{part.name}: {', '.join(violations)}")

        if invalid_parts:
            self.report({'ERROR'}, "Piezas fuera de limite: " + " | ".join(invalid_parts[:3]))
            return {'FINISHED'}

        self.report({'INFO'}, (
            f"'{original_name}' {triangulate_status} y dividido en {len(created_parts)} sub-grupos WMO "
            f"(max {self.MAX_VERTICES:,} vertices, {self.MAX_GROUP_TRIANGLES:,} tris, "
            f"{self.MAX_BATCH_TRIANGLES:,} tris/material)"
        ))
        return {'FINISHED'}


class OBJECT_OT_dar_colision_wmo(bpy.types.Operator):
    """Assign a complete, per-group collision vertex group for WoW Blender Studio."""

    bl_idname = "object.dar_colision_wmo"
    bl_label = "Dar Colisión WMO"
    bl_description = (
        "Asigna Collision a cada malla seleccionada y configura el BSP de los grupos WMO"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # WBS's own Quick Collision operator exports every selected object's full
    # geometry with this leaf-size default.  It is intentionally *not* a world
    # unit nor collision thickness.  Using its known stable value avoids the
    # very deep BSPs produced by the kernel's undocumented dynamic mode on a
    # WMO split into hundreds of pieces.
    QUICK_COLLISION_NODE_SIZE = 2500
    MAX_BSP_FACES = 60000

    @staticmethod
    def _is_wmo_group(obj):
        """True when a selected mesh exposes WBS's export properties."""
        if obj.type != 'MESH':
            return False
        try:
            vertex_info = obj.wow_wmo_vertex_info
            obj.wow_wmo_group
        except AttributeError:
            return False

        return hasattr(vertex_info, "vertex_group") and hasattr(vertex_info, "node_size")

    @staticmethod
    def _ensure_wmo_group_enabled(obj):
        """Restore WBS export status for an accepted selected WMO group."""
        try:
            obj.wow_wmo_group.enabled = True
        except AttributeError:
            pass

    @staticmethod
    def _disable_wmo_group_for_export(obj):
        """Keep invalid selected geometry out of WBS's native exporter."""
        try:
            obj.wow_wmo_group.enabled = False
        except AttributeError:
            pass

    @staticmethod
    def _mesh_collision_preflight(mesh):
        """Return fatal errors and warnings before an exporter sees the mesh."""
        fatal = []
        warnings = []
        if not mesh.polygons:
            return ["no tiene caras"], warnings

        non_triangles = [polygon.index for polygon in mesh.polygons if len(polygon.vertices) != 3]
        if non_triangles:
            fatal.append(f"{len(non_triangles)} caras sin triangular")

        min_corner = Vector((float('inf'), float('inf'), float('inf')))
        max_corner = Vector((float('-inf'), float('-inf'), float('-inf')))
        for vertex in mesh.vertices:
            coordinate = vertex.co
            min_corner.x = min(min_corner.x, coordinate.x)
            min_corner.y = min(min_corner.y, coordinate.y)
            min_corner.z = min(min_corner.z, coordinate.z)
            max_corner.x = max(max_corner.x, coordinate.x)
            max_corner.y = max(max_corner.y, coordinate.y)
            max_corner.z = max(max_corner.z, coordinate.z)

        # Compare squared doubled-area with a scale-relative tolerance.  This
        # catches triangles that produce unstable BSP planes without rejecting
        # legitimately small details in a large WMO.
        area_epsilon = max((max_corner - min_corner).length_squared * 1e-14, 1e-18)
        degenerate = 0
        duplicates = 0
        seen_triangles = set()
        edge_face_count = {}
        for polygon in mesh.polygons:
            vertices = list(polygon.vertices)
            if len(vertices) != 3:
                continue
            coordinate_a, coordinate_b, coordinate_c = (
                mesh.vertices[index].co for index in vertices
            )
            if (coordinate_b - coordinate_a).cross(coordinate_c - coordinate_a).length_squared <= area_epsilon:
                degenerate += 1
            triangle_key = tuple(sorted(vertices))
            if triangle_key in seen_triangles:
                duplicates += 1
            seen_triangles.add(triangle_key)
            for index, vertex_a in enumerate(vertices):
                vertex_b = vertices[(index + 1) % 3]
                edge_key = (vertex_a, vertex_b) if vertex_a < vertex_b else (vertex_b, vertex_a)
                edge_face_count[edge_key] = edge_face_count.get(edge_key, 0) + 1

        if degenerate:
            fatal.append(f"{degenerate} triangulos degenerados")
        if duplicates:
            fatal.append(f"{duplicates} triangulos duplicados")

        non_manifold = sum(1 for count in edge_face_count.values() if count > 2)
        if non_manifold:
            warnings.append(f"{non_manifold} aristas non-manifold")
        return fatal, warnings

    def _auto_node_size(self, bsp_face_count):
        """Use WBS Quick Collision's proven BSP leaf-size default.

        Collision is determined by the selected triangles, not by decreasing
        Node Size.  A 2.5k leaf has far lower BSP overhead for a WMO containing
        many groups while preserving the exact same collision triangles.
        ``bsp_face_count`` is kept in the signature for compatibility with the
        preflight call site and possible future per-group overrides.
        """
        return self.QUICK_COLLISION_NODE_SIZE

    @staticmethod
    def _loop_triangle_count(mesh):
        """Count exactly the loop triangles passed by WBS to the BSP builder."""
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)

    def _bsp_face_count(self, obj):
        """Count visual and explicit collision triangles that share this BSP."""
        face_count = self._loop_triangle_count(obj.data)
        collision_mesh = obj.wow_wmo_group.collision_mesh
        if collision_mesh and collision_mesh.type == 'MESH':
            face_count += self._loop_triangle_count(collision_mesh.data)
        return face_count

    @staticmethod
    def _assign_all_vertices_to_collision(obj):
        """Assign ``Collision`` to every vertex of any selected mesh."""
        collision_group = obj.vertex_groups.get("Collision")
        if collision_group is None:
            collision_group = obj.vertex_groups.new(name="Collision")

        if collision_group.name != "Collision":
            # This would only be possible if Blender had to disambiguate a
            # hidden/linked name.  Exporting through a different group would
            # be ambiguous, so fail before reaching WBS's native exporter.
            raise RuntimeError(
                f"No se pudo crear el grupo canónico 'Collision' (Blender creó '{collision_group.name}')"
            )

        vertex_indices = list(range(len(obj.data.vertices)))
        if vertex_indices:
            # Rebuild the membership rather than appending to a potentially
            # inherited group from the mesh before it was divided.
            try:
                collision_group.remove(vertex_indices)
            except RuntimeError:
                pass
            collision_group.add(vertex_indices, 1.0, 'REPLACE')

        # WBS may not be registered in a file opened with this addon alone.
        # The vertex group still belongs to the selected mesh in that case;
        # when WBS properties are present, point its exporter at the group.
        try:
            obj.wow_wmo_vertex_info.vertex_group = collision_group.name
        except AttributeError:
            pass
        return collision_group

    def _collision_export_preflight(self, obj):
        """Validate data consumed by WBS's native collision batcher.

        A named vertex group alone is not enough when a WMO group also points
        to a separate collision mesh: WBS appends both meshes to the same BSP.
        Reject malformed explicit data here instead of sending it to C++ during
        export, where it can terminate Blender.
        """
        fatal = []
        warnings = []
        collision_mesh = obj.wow_wmo_group.collision_mesh
        if collision_mesh is None:
            return fatal, warnings
        if collision_mesh.type != 'MESH':
            return ["su malla de colisión explícita no es un Mesh"], warnings
        if collision_mesh == obj:
            return ["usa el propio grupo WMO como malla de colisión explícita"], warnings

        collision_fatal, collision_warnings = self._mesh_collision_preflight(collision_mesh.data)
        fatal.extend(
            f"malla de colisión explícita: {message}" for message in collision_fatal
        )
        warnings.extend(
            f"malla de colisión explícita: {message}" for message in collision_warnings
        )
        if collision_mesh.modifiers:
            warnings.append("malla de colisión explícita con modificadores: se exportará su geometría evaluada")
        return fatal, warnings

    def execute(self, context):
        selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected:
            self.report({'ERROR'}, "Selecciona los sub-grupos WMO a los que dar colision")
            return {'CANCELLED'}

        generated = []
        assigned = []
        invalid = []
        ignored = []
        warnings = []

        for obj in selected:
            # Assignment is intentionally unconditional for every selected
            # mesh.  A floor is often a perfectly planar surface, and an
            # object whose WBS flag was reset by Separate still needs its
            # vertex group before it can be exported again.
            try:
                collision_group = self._assign_all_vertices_to_collision(obj)
                assigned.append(obj.name)
            except RuntimeError as error:
                invalid.append(f"{obj.name}: no se pudo asignar Collision ({error})")
                continue

            if not self._is_wmo_group(obj):
                ignored.append(
                    f"{obj.name} (Collision asignado; faltan propiedades de WBS para configurar exportación)"
                )
                continue

            obj["wow_atajos_wmo_collision_ready"] = False

            fatal, mesh_warnings = self._mesh_collision_preflight(obj.data)
            collision_fatal, collision_warnings = self._collision_export_preflight(obj)
            fatal.extend(collision_fatal)
            mesh_warnings.extend(collision_warnings)
            if obj.modifiers:
                fatal.append("tiene modificadores sin aplicar")
            bsp_face_count = self._bsp_face_count(obj)
            if bsp_face_count > self.MAX_BSP_FACES:
                fatal.append(
                    f"{bsp_face_count:,} caras BSP; el limite seguro es {self.MAX_BSP_FACES:,}"
                )
            if fatal:
                self._disable_wmo_group_for_export(obj)
                invalid.append(f"{obj.name}: {', '.join(fatal)}")
                continue

            triangle_count = self._loop_triangle_count(obj.data)
            node_size = self._auto_node_size(bsp_face_count)
            self._ensure_wmo_group_enabled(obj)
            obj.wow_wmo_vertex_info.node_size = node_size
            obj["wow_atajos_wmo_collision_ready"] = True
            obj["wow_atajos_wmo_collision_group"] = collision_group.name
            obj["wow_atajos_wmo_collision_node_size"] = node_size
            obj["wow_atajos_wmo_collision_triangles"] = triangle_count
            obj["wow_atajos_wmo_bsp_faces"] = bsp_face_count
            obj.data.update()
            generated.append(obj.name)
            warnings.extend(f"{obj.name}: {warning}" for warning in mesh_warnings)

        if not assigned:
            self.report({'ERROR'}, "No se pudo asignar el grupo Collision a ninguna malla seleccionada")
            return {'CANCELLED'}

        details = []
        if invalid:
            details.append("sin generar: " + " | ".join(invalid[:2]))
        if warnings:
            details.append("avisos: " + " | ".join(warnings[:2]))
        if ignored:
            shown_ignored = ", ".join(ignored[:3])
            remainder = "" if len(ignored) <= 3 else f" y {len(ignored) - 3} más"
            details.append(f"ignorados: {shown_ignored}{remainder}")

        message = f"Collision asignado en {len(assigned)} malla(s) seleccionada(s)"
        if generated:
            message += (
                f"; BSP listo en {len(generated)} grupo(s) WMO "
                f"(Node Size {self.QUICK_COLLISION_NODE_SIZE})"
            )
        else:
            message += "; ninguna pasó aún la validación BSP"
        if details:
            self.report({'WARNING'}, message + "; " + "; ".join(details))
        else:
            self.report({'INFO'}, message)

        return {'FINISHED'}


# =====================================================
# PANEL PRINCIPAL – colapsa todo al cerrarse
# =====================================================

class MATERIAL_PT_tools_norte(bpy.types.Panel):
    bl_label = "WoW: Atajos Útiles"
    bl_idname = "MATERIAL_PT_tools_norte"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_order = 0

    def draw(self, context):
        self.layout.operator("wm.abrir_carpeta_addon", icon='FILE_FOLDER')


# ── Subpanel: Materiales ─────────────────────────────

class MATERIAL_PT_sec_materiales(bpy.types.Panel):
    bl_label = "Materiales"
    bl_idname = "MATERIAL_PT_sec_materiales"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 1

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("material.materiales_opacos", icon='MATERIAL')
        col.operator("material.materiales_sin_brillo", icon='SHADING_RENDERED')


# ── Subpanel: UVs ────────────────────────────────────

class MATERIAL_PT_sec_uvs(bpy.types.Panel):
    bl_label = "UVs"
    bl_idname = "MATERIAL_PT_sec_uvs"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 2

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.renombrar_uvmap", icon='UV')
        col.operator("object.renombrar_uvmap_texture", icon='UV')


# ── Subpanel: Nombres ────────────────────────────────

class MATERIAL_PT_sec_nombres(bpy.types.Panel):
    bl_label = "Nombres"
    bl_idname = "MATERIAL_PT_sec_nombres"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 3

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("material.quitar_prefijo_mat", icon='SORTALPHA')
        col.operator("material.nombre_por_textura", icon='FILE_IMAGE')
        col.operator("material.eliminar_duplicados_001", icon='TRASH')
        col.operator("material.unir_mats_repetidos", icon='IMAGE_PLANE')


# =====================================================
# OPERADOR – Actualizar informe de texturas (sin regenerar)
# =====================================================

class MATERIAL_OT_wmo_refresh_report(bpy.types.Operator):
    bl_idname = "material.wmo_refresh_report"
    bl_label = "Actualizar"
    bl_description = "Relee el estado actual y quita fallos ya arreglados, sin regenerar texturas"
    bl_options = {'REGISTER', 'UNDO'}

    def _build_used_mat_pointers(self):
        used = set()

        def _remember(m):
            if m is None:
                return
            try:
                used.add(m.as_pointer())
            except Exception:
                used.add(("__name__", getattr(m, "name", "")))

        for obj in bpy.data.objects:
            try:
                slots = getattr(obj, "material_slots", None)
            except Exception:
                slots = None
            if not slots:
                continue
            if getattr(obj, "type", "") == 'MESH':
                try:
                    mesh = obj.data
                    polys = mesh.polygons if mesh else []
                except Exception:
                    continue
                if not polys or len(polys) == 0:
                    continue
                try:
                    used_indices = set(p.material_index for p in polys)
                except Exception:
                    continue
                for idx in used_indices:
                    if 0 <= idx < len(slots):
                        try:
                            _remember(slots[idx].material)
                        except Exception:
                            pass
            else:
                for slot in slots:
                    try:
                        _remember(slot.material)
                    except Exception:
                        pass
        return used

    def _mat_key(self, m):
        try:
            return m.as_pointer()
        except Exception:
            return ("__name__", getattr(m, "name", ""))

    def _lookup_is_fixed_or_unused(self, lookup_name, used_pointers):
        mats = [
            m for m in bpy.data.materials
            if hasattr(m, "wow_wmo_material")
            and clean_lookup_name(m.name) == clean_lookup_name(lookup_name)
        ]
        used_mats = [m for m in mats if self._mat_key(m) in used_pointers]
        if not used_mats:
            return True
        for mat in used_mats:
            try:
                img = getattr(mat.wow_wmo_material, "diff_texture_1", None)
            except Exception:
                img = None
            if img is None:
                return False
            try:
                tex_props = getattr(img, "wow_wmo_texture", None)
                path = getattr(tex_props, "path", "") if tex_props else ""
            except Exception:
                path = ""
            if not path:
                return False
        return True

    def _prune_collection(self, scene, collection_name, used_pointers):
        coll = getattr(scene, collection_name)
        removed = 0
        for idx in range(len(coll) - 1, -1, -1):
            try:
                lookup_name = coll[idx].material_name
            except Exception:
                continue
            if self._lookup_is_fixed_or_unused(lookup_name, used_pointers):
                coll.remove(idx)
                removed += 1
        base = collection_name.replace("wmo_texture_", "")
        idx_name = f"wmo_texture_{base}_index" if base not in ("conflicts",) else "wmo_texture_conflict_index"
        if hasattr(scene, idx_name):
            try:
                coll_len = len(coll)
                cur = int(getattr(scene, idx_name))
                setattr(scene, idx_name, max(0, min(cur, max(0, coll_len - 1))))
            except Exception:
                pass
        return removed

    def execute(self, context):
        scene = context.scene
        used_pointers = self._build_used_mat_pointers()

        removed_nf = self._prune_collection(scene, "wmo_texture_notfound", used_pointers)
        removed_ni = self._prune_collection(scene, "wmo_texture_noimage", used_pointers)

        removed_cf = 0
        conflicts = scene.wmo_texture_conflicts
        for idx in range(len(conflicts) - 1, -1, -1):
            try:
                lookup_name = conflicts[idx].material_name
            except Exception:
                continue
            if self._lookup_is_fixed_or_unused(lookup_name, used_pointers):
                conflicts.remove(idx)
                removed_cf += 1
        try:
            if conflicts:
                scene.wmo_texture_conflict_index = max(
                    0, min(scene.wmo_texture_conflict_index, len(conflicts) - 1)
                )
                refresh_texture_candidate_list(scene)
            else:
                scene.wmo_texture_candidates.clear()
                scene.wmo_texture_conflict_index = 0
                scene.wmo_texture_candidate_index = 0
        except Exception:
            pass

        total = removed_nf + removed_ni + removed_cf
        if total == 0:
            self.report({'INFO'}, "Actualizar: sin cambios, todo sigue igual")
        else:
            self.report({'INFO'}, f"Actualizar: {total} fallo(s) ya arreglado(s), lista al dia")
        return {'FINISHED'}


# ── Subpanel: WMO ────────────────────────────────────

class MATERIAL_PT_sec_texturas(bpy.types.Panel):
    bl_label = "WMO"
    bl_idname = "MATERIAL_PT_sec_texturas"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        props = context.scene.wmo_auto_props

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("material.wbs_full_auto_custom", icon='BRUSH_DATA', text="Rellenar Texturas WMO")

        data = load_database()
        stats = get_texture_index_stats()
        if stats["available"]:
            col.label(text=f"{stats['textures']} BLP indexadas | {len(data['CUSTOM'])} Custom", icon='INFO')
        else:
            col.label(text=f"Sin indice SQLite | {len(data['CUSTOM'])} Custom", icon='ERROR')

        # ── Control de Texturas (desplegable) ──
        scene = context.scene
        n_nf = len(scene.wmo_texture_notfound)
        n_ni = len(scene.wmo_texture_noimage)
        n_cf = len(scene.wmo_texture_conflicts)

        control_box = layout.box()
        header = control_box.row()
        expand_icon = 'TRIA_DOWN' if scene.wmo_texture_control_expanded else 'TRIA_RIGHT'
        header.prop(scene, "wmo_texture_control_expanded", icon=expand_icon, emboss=False,
                    text=f"Control de Texturas (fallos: {n_nf + n_ni + n_cf})")

        if scene.wmo_texture_control_expanded:
            has_report = (n_nf + n_ni + n_cf) > 0 or bool(scene.wmo_texture_summary)
            if not has_report:
                control_box.label(text="Sin informe: pulsa 'Rellenar Texturas WMO'.", icon='QUESTION')
            else:
                # Sin encontrar
                nf_text = f"Sin encontrar ({n_nf}):"
                if n_nf == 0:
                    nf_text += " Todas correctas."
                control_box.label(text=nf_text, icon='ERROR')
                if n_nf:
                    control_box.template_list(
                        "WMO_UL_texture_report", "",
                        scene, "wmo_texture_notfound",
                        scene, "wmo_texture_notfound_index",
                        rows=min(5, max(1, n_nf))
                    )
                    op = control_box.operator("material.wmo_select_reported", icon='RESTRICT_SELECT_OFF', text="Seleccionar objeto / material")
                    op.collection = "NOTFOUND"

                # Sin imagen (ruta encontrada pero sin imagen donde aplicarla)
                ni_text = f"Sin imagen ({n_ni}):"
                if n_ni == 0:
                    ni_text += " Todas correctas."
                control_box.label(text=ni_text, icon='IMAGE_DATA')
                if n_ni:
                    control_box.template_list(
                        "WMO_UL_texture_report", "",
                        scene, "wmo_texture_noimage",
                        scene, "wmo_texture_noimage_index",
                        rows=min(5, max(1, n_ni))
                    )
                    op = control_box.operator("material.wmo_select_reported", icon='RESTRICT_SELECT_OFF', text="Seleccionar objeto / material")
                    op.collection = "NOIMAGE"

                control_box.operator("material.wmo_refresh_report", icon='FILE_REFRESH', text="Actualizar")

        if context.scene.wmo_texture_conflicts:
            layout.separator(factor=0.1)
            conflict_box = layout.box()
            conflict_box.label(text=f"Conflictos pendientes: {len(context.scene.wmo_texture_conflicts)}", icon='ERROR')
            conflict_box.template_list(
                "WMO_UL_texture_conflicts",
                "",
                context.scene,
                "wmo_texture_conflicts",
                context.scene,
                "wmo_texture_conflict_index",
                rows=4
            )
            conflict_box.template_list(
                "WMO_UL_texture_candidates",
                "",
                context.scene,
                "wmo_texture_candidates",
                context.scene,
                "wmo_texture_candidate_index",
                rows=5
            )
            row = conflict_box.row(align=True)
            op = row.operator("material.wmo_apply_conflict", icon='CHECKMARK', text="Aplicar")
            op.remember = False
            op = row.operator("material.wmo_apply_conflict", icon='FILE_TICK', text="Aplicar + recordar")
            op.remember = True
            conflict_box.operator("material.wmo_skip_conflict", icon='X', text="Saltar")
            op = conflict_box.operator("material.wmo_select_reported", icon='RESTRICT_SELECT_OFF', text="Seleccionar objeto / material")
            op.collection = "CONFLICT"

        layout.separator(factor=0.1)

        add_box = layout.box()
        add_header = add_box.row()
        add_expand_icon = 'TRIA_DOWN' if scene.wmo_add_db_expanded else 'TRIA_RIGHT'
        add_header.prop(scene, "wmo_add_db_expanded", icon=add_expand_icon, emboss=False,
                    text="Añadir textura a la base de datos:")
        if scene.wmo_add_db_expanded:
            add_box.prop(props, "new_mat_name", text="Custom")
            add_box.prop(props, "new_wow_path", text="Ruta (.blp)")
            add_box.prop(props, "save_json_target", text="Guardar en")
            if props.save_json_target == "__NEW__":
                add_box.prop(props, "new_json_name", text="Nuevo JSON")
            add_box.operator("material.wbs_add_to_db", icon='FILE_TICK', text="Añadir a la Base de Datos")

        layout.separator()
        split_col = layout.column(align=True)
        split_col.scale_y = 1.4
        split_col.operator("object.dividir_wmo_rapido", icon='MOD_EXPLODE', text="Triangular y Dividir (Rápido)")
        split_col.operator("object.dividir_wmo", icon='FILE_VOLUME', text="Triangular y Dividir (Preciso)")
        row = layout.row()
        row.scale_y = 1.4
        row.operator("object.dar_colision_wmo", icon='MOD_PHYSICS', text="Dar Colisión")


# =====================================================
# OPERADOR – Bakear texturas a una sola imagen
# =====================================================

class OBJECT_OT_bakear_texturas(bpy.types.Operator):
    bl_idname = "object.bakear_texturas_wow"
    bl_label = "Bakear Texturas"
    bl_description = "Duplica la seleccion, la une, le crea una imagen y bakea el difuso a una sola textura"
    bl_options = {'REGISTER', 'UNDO'}

    NEW_IMG_NAME = "Textura_Baked"
    OBJ_SUFFIX = "_Baked"
    EXTRUSION = 0.01
    MARGIN = 16

    def _remove_previous_bake(self, target_name, img_name):
        """Si ya existe un bake anterior con este nombre, lo elimina (objeto,
        malla, material e imagen huerfanos) para evitar duplicados tipo .001."""
        old_obj = bpy.data.objects.get(target_name)
        if old_obj:
            old_mesh = old_obj.data
            old_mats = [s.material for s in old_obj.material_slots if s.material]
            bpy.data.objects.remove(old_obj, do_unlink=True)
            if old_mesh and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
            for m in old_mats:
                if m and m.users == 0:
                    bpy.data.materials.remove(m)

        old_img = bpy.data.images.get(img_name)
        if old_img and old_img.users == 0:
            bpy.data.images.remove(old_img)

    def execute(self, context):
        import math

        scene = context.scene
        img_size = int(getattr(scene, "wow_bake_size", 2048))
        if img_size not in WOW_BAKE_SIZES:
            img_size = min(WOW_BAKE_SIZES, key=lambda s: abs(s - img_size))

        export_dir = getattr(scene, "wow_bake_export_path", "") or get_desktop()
        export_dir = bpy.path.abspath(export_dir)
        try:
            os.makedirs(export_dir, exist_ok=True)
        except Exception as error:
            self.report({'ERROR'}, f"No se pudo crear la carpeta de exportacion: {error}")
            return {'CANCELLED'}

        # Excluye del origen cualquier objeto que ya sea resultado de un bake
        # anterior (evita geometria duplicada si quedo seleccionado sin querer)
        source_objs = [
            o for o in context.selected_objects
            if o.type == 'MESH' and not o.get("is_baked_output", False)
        ]
        if not source_objs:
            self.report({'ERROR'}, "Selecciona al menos un objeto de malla ORIGINAL (no un bake anterior)")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        base_name = source_objs[0].name
        target_name = base_name + self.OBJ_SUFFIX

        try:
            # 0. Limpiar un bake anterior con el mismo nombre, si existe
            self._remove_previous_bake(target_name, self.NEW_IMG_NAME)

            # 1. Duplicar el/los objeto(s) seleccionado(s)
            bpy.ops.object.select_all(action='DESELECT')
            for o in source_objs:
                o.select_set(True)
            context.view_layer.objects.active = source_objs[-1]
            bpy.ops.object.duplicate(linked=False)
            dup_objs = list(context.selected_objects)

            # 2. Si son varias piezas, unirlas en una sola malla
            if len(dup_objs) > 1:
                context.view_layer.objects.active = dup_objs[-1]
                bpy.ops.object.join()
            target = context.view_layer.objects.active
            target.name = target_name
            target["is_baked_output"] = True

            # 3. Quitar todos los materiales del duplicado
            target.data.materials.clear()

            # 4. Crear material nuevo con una imagen nueva en blanco
            mat = bpy.data.materials.new(name=target.name + "_Mat")
            mat.use_nodes = True
            target.data.materials.append(mat)

            nt = mat.node_tree
            bsdf = nt.nodes.get("Principled BSDF")

            # Mismo acabado que "Materiales sin brillo, como en el WoW"
            if bsdf is not None and getattr(bsdf, "type", "") == 'BSDF_PRINCIPLED':
                for input_name, value in (
                    ('Specular', 0.0),
                    ('Roughness', 1.0),
                    ('Specular Tint', 0.0),
                    ('Metallic', 0.0),
                ):
                    if input_name in bsdf.inputs:
                        try:
                            bsdf.inputs[input_name].default_value = value
                        except Exception:
                            pass

            img = bpy.data.images.new(self.NEW_IMG_NAME, width=img_size, height=img_size)

            img_node = nt.nodes.new("ShaderNodeTexImage")
            img_node.image = img
            img_node.location = (bsdf.location.x - 300, bsdf.location.y)
            nt.links.new(img_node.outputs["Color"], bsdf.inputs["Base Color"])

            # El nodo de imagen debe quedar seleccionado y activo
            for n in nt.nodes:
                n.select = False
            img_node.select = True
            nt.nodes.active = img_node

            # 5. UV unwrap dentro del cuadro 0-1 (Smart UV Project)
            bpy.ops.object.select_all(action='DESELECT')
            target.select_set(True)
            context.view_layer.objects.active = target

            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.0)
            bpy.ops.object.mode_set(mode='OBJECT')

            # 6. Render engine -> Cycles (necesario para "Selected to Active")
            scene.render.engine = 'CYCLES'

            # 7. Seleccionar objetos originales + duplicado (activo) y bakear
            bpy.ops.object.select_all(action='DESELECT')
            for o in source_objs:
                o.select_set(True)
            target.select_set(True)
            context.view_layer.objects.active = target

            bpy.ops.object.bake(
                type='DIFFUSE',
                pass_filter={'COLOR'},
                use_selected_to_active=True,
                cage_extrusion=self.EXTRUSION,
                margin=self.MARGIN,
                target='IMAGE_TEXTURES',
            )

            # 8. Exportar el PNG (sobrescribe el anterior si existia)
            out_path = os.path.join(export_dir, self.NEW_IMG_NAME + ".png")
            img.filepath_raw = out_path
            img.file_format = 'PNG'
            img.save()
        except Exception as error:
            self.report({'ERROR'}, f"Fallo el bake: {error}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Bake completo -> objeto '{target.name}' ({img_size}x{img_size}), PNG en: {out_path}")
        return {'FINISHED'}


# ── Subpanel: Bakear ─────────────────────────────────

class MATERIAL_PT_sec_bakear(bpy.types.Panel):
    bl_label = "Bakear"
    bl_idname = "MATERIAL_PT_sec_bakear"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("object.bakear_texturas_wow", icon='IMAGE_ZDEPTH', text="Bakear Texturas")

        tight = layout.column(align=True)
        size_box = tight.box()
        size_box.prop(scene, "wow_bake_size", text="Tamaño")

        path_box = tight.box()
        path_box.prop(scene, "wow_bake_export_path", text="Ruta PNG")


# ── Subpanel: Diagnóstico ────────────────────────────

class MATERIAL_PT_sec_diagnostico(bpy.types.Panel):
    bl_label = "Diagnóstico"
    bl_idname = "MATERIAL_PT_sec_diagnostico"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 6
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.2
        col.operator("material.check_missing_images", icon='IMAGE_DATA', text="¿Todos tienen imagen?")
        col.operator("material.count_materials", icon='MATERIAL', text="Nº Total de Materiales")
        col.operator("wm.cerrar_consola", icon='CONSOLE', text="Cerrar Consola")


# ── Subpanel: Exportar ───────────────────────────────

class MATERIAL_PT_sec_exportar(bpy.types.Panel):
    bl_label = "Exportar"
    bl_idname = "MATERIAL_PT_sec_exportar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 7
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.2
        col.operator("material.export_names", icon='FILE_TEXT', text="Exportar Nombres Materiales a Escritorio")
        col.operator("material.export_pngs", icon='IMAGE_RGB', text="Exportar PNGs a Escritorio")


# ── Subpanel: Importar ───────────────────────────────

class MATERIAL_PT_sec_importar(bpy.types.Panel):
    bl_label = "Importar"
    bl_idname = "MATERIAL_PT_sec_importar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 8
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.2
        col.operator("wm.importar_json_custom", icon='FILE', text="JSON de Materiales Custom")
        col.menu("WM_MT_lista_json_custom", icon='PRESET', text="Lista de JSON Custom")


# =====================================================
# REGISTER
# =====================================================

classes = (
    WMO_Addon_Props,
    WMO_TextureConflictItem,
    WMO_TextureCandidateItem,
    WMO_TextureReportItem,
    WMO_UL_texture_conflicts,
    WMO_UL_texture_candidates,
    WMO_UL_texture_report,
    MATERIAL_OT_opacos,
    MATERIAL_OT_sin_brillo,
    OBJECT_OT_renombrar_uv,
    OBJECT_OT_renombrar_uv_texture,
    MATERIAL_OT_quitar_prefijo,
    MATERIAL_OT_nombre_por_textura,
    MATERIAL_OT_eliminar_duplicados,
    MATERIAL_OT_unir_mats_repetidos,
    MATERIAL_OT_wbs_full_auto_custom,
    MATERIAL_OT_wbs_add_to_db,
    MATERIAL_OT_wmo_apply_conflict,
    MATERIAL_OT_wmo_skip_conflict,
    MATERIAL_OT_wmo_select_reported,
    MATERIAL_OT_wmo_refresh_report,
    MATERIAL_OT_check_missing_images,
    MATERIAL_OT_count_materials,
    MATERIAL_OT_export_names,
    MATERIAL_OT_export_pngs,
    NORTE_OT_rotate_90_z,
    OBJECT_OT_dividir_wmo,
    OBJECT_OT_dividir_wmo_rapido,
    OBJECT_OT_dar_colision_wmo,
    OBJECT_OT_bakear_texturas,
    WM_OT_cerrar_consola,
    WM_OT_abrir_carpeta_addon,
    WM_OT_importar_json_custom,
    WM_OT_toggle_json_custom,
    WM_MT_lista_json_custom,
    MATERIAL_PT_tools_norte,
    MATERIAL_PT_sec_materiales,
    MATERIAL_PT_sec_uvs,
    MATERIAL_PT_sec_nombres,
    MATERIAL_PT_sec_texturas,
    MATERIAL_PT_sec_bakear,
    MATERIAL_PT_sec_diagnostico,
    MATERIAL_PT_sec_exportar,
    MATERIAL_PT_sec_importar,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.wmo_auto_props = bpy.props.PointerProperty(type=WMO_Addon_Props)
    bpy.types.Scene.wmo_texture_conflicts = bpy.props.CollectionProperty(type=WMO_TextureConflictItem)
    bpy.types.Scene.wmo_texture_candidates = bpy.props.CollectionProperty(type=WMO_TextureCandidateItem)
    bpy.types.Scene.wmo_texture_conflict_index = bpy.props.IntProperty(update=update_wmo_conflict_index)
    bpy.types.Scene.wmo_texture_candidate_index = bpy.props.IntProperty()
    bpy.types.Scene.wmo_texture_summary = bpy.props.StringProperty(default="")
    bpy.types.Scene.wmo_texture_ok = bpy.props.CollectionProperty(type=WMO_TextureReportItem)
    bpy.types.Scene.wmo_texture_notfound = bpy.props.CollectionProperty(type=WMO_TextureReportItem)
    bpy.types.Scene.wmo_texture_noimage = bpy.props.CollectionProperty(type=WMO_TextureReportItem)
    bpy.types.Scene.wmo_texture_ok_index = bpy.props.IntProperty(update=update_wmo_report_ok_index)
    bpy.types.Scene.wmo_texture_notfound_index = bpy.props.IntProperty(update=update_wmo_report_notfound_index)
    bpy.types.Scene.wmo_texture_noimage_index = bpy.props.IntProperty(update=update_wmo_report_noimage_index)
    bpy.types.Scene.wmo_texture_control_expanded = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.wmo_add_db_expanded = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.wow_bake_size = bpy.props.IntProperty(
        name="Tamaño",
        description="Tamaño de la textura bakeada (siempre potencia de 2)",
        default=2048,
        min=256,
        max=8192,
        step=1,
        update=update_wow_bake_size,
    )
    bpy.types.Scene.wow_bake_export_path = bpy.props.StringProperty(
        name="Ruta Exportación",
        description="Carpeta donde se exporta el PNG bakeado",
        default=get_desktop(),
        subtype='DIR_PATH',
    )

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
        kmi = km.keymap_items.new(
            NORTE_OT_rotate_90_z.bl_idname,
            type='R',
            value='PRESS',
            shift=True
        )
        addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    del bpy.types.Scene.wmo_texture_summary
    del bpy.types.Scene.wmo_texture_candidate_index
    del bpy.types.Scene.wmo_texture_conflict_index
    del bpy.types.Scene.wmo_texture_candidates
    del bpy.types.Scene.wmo_texture_conflicts
    del bpy.types.Scene.wmo_texture_ok
    del bpy.types.Scene.wmo_texture_notfound
    del bpy.types.Scene.wmo_texture_noimage
    del bpy.types.Scene.wmo_texture_ok_index
    del bpy.types.Scene.wmo_texture_notfound_index
    del bpy.types.Scene.wmo_texture_noimage_index
    del bpy.types.Scene.wmo_texture_control_expanded
    del bpy.types.Scene.wmo_add_db_expanded
    del bpy.types.Scene.wow_bake_size
    del bpy.types.Scene.wow_bake_export_path
    del bpy.types.Scene.wmo_auto_props

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
