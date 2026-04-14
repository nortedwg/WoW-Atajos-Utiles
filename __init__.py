bl_info = {
    "name": "Atajos Útiles",
    "author": "Norte",
    "version": (3, 1),
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
from math import radians
from mathutils import Matrix, Vector

addon_keymaps = []


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

def load_database():
    path = get_db_path()
    default_data = {
        "CUSTOM": {
            "CUSTOM_PiedraHD_Shadowfang": "creature/singleturret/6ih_ironhorde_supertank_moveg.blp"
        },
        "GENERAL": [
            "dungeons/textures/6hu_garrison/6hu_garrison_strmwnd_wall_03.blp",
            "tileset/expansion07/general/8war_grass03_1024.blp"
        ]
    }
    if not os.path.exists(path):
        data = default_data
    else:
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except:
            data = default_data

    # Fusionar los JSON Customs activos
    config = load_json_config()
    customs_dir = get_json_customs_dir()
    for fname in get_custom_json_files():
        if config.get(fname, True):  # por defecto activo
            fpath = os.path.join(customs_dir, fname)
            try:
                with open(fpath, 'r') as f:
                    custom_data = json.load(f)
                # Formato plano {"Nombre": "ruta.blp", ...} → todo va a CUSTOM
                if "CUSTOM" not in custom_data and "GENERAL" not in custom_data:
                    data["CUSTOM"].update(custom_data)
                else:
                    if "CUSTOM" in custom_data:
                        data["CUSTOM"].update(custom_data["CUSTOM"])
                    if "GENERAL" in custom_data:
                        for entry in custom_data["GENERAL"]:
                            if entry not in data["GENERAL"]:
                                data["GENERAL"].append(entry)
            except:
                pass
    return data

def save_database(data):
    path = get_db_path()
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)


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
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    filepath = node.image.filepath
                    filename = os.path.basename(filepath)
                    name_without_ext = os.path.splitext(filename)[0]
                    # Fallback: imagen empaquetada o sin filepath → usar image.name
                    if not name_without_ext:
                        name_without_ext = os.path.splitext(node.image.name)[0]
                    if name_without_ext:
                        mat.name = name_without_ext
                        count += 1
                    break
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
# OPERADOR 7 – Rellenar Texturas WMO
# =====================================================

class MATERIAL_OT_wbs_full_auto_custom(bpy.types.Operator):
    bl_idname = "material.wbs_full_auto_custom"
    bl_label = "Rellenar Texturas WMO"
    bl_description = "Asigna texturas WoW ignorando extensiones y duplicados (.001)."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        data = load_database()
        path_map_general = {}
        for line in data["GENERAL"]:
            clean_path = line.strip().replace('/', '\\')
            filename = os.path.basename(clean_path)
            name_no_ext = os.path.splitext(filename)[0].lower()
            path_map_general[name_no_ext] = clean_path
        custom_map = {k.lower(): v.replace('/', '\\') for k, v in data["CUSTOM"].items()}
        images_assigned = 0
        paths_filled = 0
        print("\n--- INICIANDO PROCESO DE LIMPIEZA ---")
        for mat in bpy.data.materials:
            mat_name_base = mat.name.split('.')[0].lower()
            if not hasattr(mat, "wow_wmo_material"):
                continue
            target_wow_path = custom_map.get(mat_name_base) or path_map_general.get(mat_name_base)
            if not target_wow_path:
                continue
            target_image = None
            for img in bpy.data.images:
                img_name_clean = img.name.split('.')[0].lower()
                if img_name_clean == mat_name_base:
                    target_image = img
                    break
            if target_image:
                mat.wow_wmo_material.diff_texture_1 = target_image
                images_assigned += 1
                if hasattr(target_image, "wow_wmo_texture"):
                    target_image.wow_wmo_texture.path = target_wow_path
                    paths_filled += 1
                print(f"ASIGNADO: {mat_name_base} -> {target_image.name}")
            else:
                print(f"FALLO: No se encontró imagen para {mat_name_base}")
        self.report({'INFO'}, f"Procesado: {images_assigned} imágenes, {paths_filled} rutas.")
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
        data = load_database()
        if props.new_mat_name:
            data["CUSTOM"][props.new_mat_name] = props.new_wow_path
            self.report({'INFO'}, f"Añadido a Custom: {props.new_mat_name}")
        else:
            if props.new_wow_path not in data["GENERAL"]:
                data["GENERAL"].append(props.new_wow_path)
                self.report({'INFO'}, "Añadido a la base de datos.")
        save_database(data)
        props.new_mat_name = ""
        props.new_wow_path = ""
        return {'FINISHED'}


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


# ── Subpanel: Texturas WMO ───────────────────────────

class MATERIAL_PT_sec_texturas(bpy.types.Panel):
    bl_label = "Texturas WMO"
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
        col.label(text=f"{len(data['CUSTOM'])} Custom  |  {len(data['GENERAL'])} General en BD", icon='INFO')

        layout.separator()

        box = layout.box()
        box.label(text="Añadir textura a la base de datos:", icon='ADD')
        box.prop(props, "new_mat_name", text="Custom")
        box.prop(props, "new_wow_path", text="Ruta (.blp)")
        box.operator("material.wbs_add_to_db", icon='FILE_TICK', text="Añadir a la Base de Datos")


# ── Subpanel: Diagnóstico ────────────────────────────

class MATERIAL_PT_sec_diagnostico(bpy.types.Panel):
    bl_label = "Diagnóstico"
    bl_idname = "MATERIAL_PT_sec_diagnostico"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "WoW: Atajos"
    bl_parent_id = "MATERIAL_PT_tools_norte"
    bl_order = 5

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
    bl_order = 6

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
    bl_order = 7

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
    MATERIAL_OT_opacos,
    MATERIAL_OT_sin_brillo,
    OBJECT_OT_renombrar_uv,
    OBJECT_OT_renombrar_uv_texture,
    MATERIAL_OT_quitar_prefijo,
    MATERIAL_OT_nombre_por_textura,
    MATERIAL_OT_eliminar_duplicados,
    MATERIAL_OT_wbs_full_auto_custom,
    MATERIAL_OT_wbs_add_to_db,
    MATERIAL_OT_check_missing_images,
    MATERIAL_OT_count_materials,
    MATERIAL_OT_export_names,
    MATERIAL_OT_export_pngs,
    NORTE_OT_rotate_90_z,
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
    MATERIAL_PT_sec_diagnostico,
    MATERIAL_PT_sec_exportar,
    MATERIAL_PT_sec_importar,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.wmo_auto_props = bpy.props.PointerProperty(type=WMO_Addon_Props)

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

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.wmo_auto_props


if __name__ == "__main__":
    register()
