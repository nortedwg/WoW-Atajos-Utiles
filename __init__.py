import bpy
import os
import json

bl_info = {
    "name": "WMO Texturas Automaticas",
    "author": "Norte",
    "version": (1.4),
    "blender": (3, 4, 0),
    "location": "Propiedades de Material > WoW Blender Studio",
    "description": "Establece automaticamente los materiales del WMO.",
    "category": "Material",
}

# --- GESTIÓN DE BASE DE DATOS ---
def get_db_path():
    # Guarda el JSON en la misma carpeta que el script
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
        return default_data
    
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default_data

def save_database(data):
    path = get_db_path()
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)

# --- PROPIEDADES TEMPORALES PARA LA UI ---
class WMO_Addon_Props(bpy.types.PropertyGroup):
    new_mat_name: bpy.props.StringProperty(name="Nombre Material", description="Nombre en Blender (Solo añadir si el material es custom. Dejar vacío si es del propio WoW)")
    new_wow_path: bpy.props.StringProperty(name="Ruta WoW", description="Ruta completa al .blp")

# --- OPERADORES ---

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
        
        # Si hay nombre de material, va a CUSTOM. Si no, a GENERAL.
        if props.new_mat_name:
            data["CUSTOM"][props.new_mat_name] = props.new_wow_path
            self.report({'INFO'}, f"Añadido a Custom: {props.new_mat_name}")
        else:
            if props.new_wow_path not in data["GENERAL"]:
                data["GENERAL"].append(props.new_wow_path)
                self.report({'INFO'}, "Añadido a la base de datos.")
        
        save_database(data)
        # Limpiar campos
        props.new_mat_name = ""
        props.new_wow_path = ""
        return {'FINISHED'}

class MATERIAL_OT_wbs_full_auto_custom(bpy.types.Operator):
    bl_idname = "material.wbs_full_auto_custom"
    bl_label = "Ejecutar Relleno Automático"
    bl_description = "Asigna texturas WoW ignorando extensiones y duplicados (.001)."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        data = load_database()
        
        # 1. Preparar mapas del JSON
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
            # Limpiar nombre del material (quitar .001)
            mat_name_base = mat.name.split('.')[0].lower()
            
            if not hasattr(mat, "wow_wmo_material"):
                continue

            # Buscar ruta en JSON
            target_wow_path = custom_map.get(mat_name_base) or path_map_general.get(mat_name_base)

            if not target_wow_path:
                continue

            # 2. BUSCADOR DE IMAGEN MEJORADO
            target_image = None
            for img in bpy.data.images:
                # Quitamos TODOS los puntos y extensiones: 
                # "lt_human_window1.png.002" -> ["lt_human_window1", "png", "002"] -> "lt_human_window1"
                img_name_clean = img.name.split('.')[0].lower()
                
                if img_name_clean == mat_name_base:
                    target_image = img
                    break
            
            # 3. Asignación
            if target_image:
                mat.wow_wmo_material.diff_texture_1 = target_image
                images_assigned += 1
                if hasattr(target_image, "wow_wmo_texture"):
                    target_image.wow_wmo_texture.path = target_wow_path
                    paths_filled += 1
                print(f"ASIGNADO: {mat_name_base} -> {target_image.name}")
            else:
                print(f"FALLO: No se encontró imagen para {mat_name_base} (Buscaba algo parecido a {mat_name_base}.png)")

        self.report({'INFO'}, f"Procesado: {images_assigned} imágenes, {paths_filled} rutas.")
        return {'FINISHED'}

# --- INTERFAZ (PANEL) ---

# --- INTERFAZ (PANEL) ---

class MATERIAL_PT_wbs_custom_panel(bpy.types.Panel):
    bl_label = "Texturas del WMO Automáticas"
    bl_idname = "MATERIAL_PT_wbs_custom_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    def draw(self, context):
        layout = self.layout
        props = context.scene.wmo_auto_props
        data = load_database()
        
        # Sección de Ejecución
        col = layout.column(align=True)
        col.operator("material.wbs_full_auto_custom", icon='BRUSH_DATA', text="[ Rellenar Texturas WMO ]")
        
        row = col.row()
        row.label(text=f"Cargados: ({len(data['CUSTOM'])} Custom | {len(data['GENERAL'])} General)", icon='INFO')
        
        layout.separator()
        
        # Sección para añadir nuevos
        box = layout.box()
        box.label(text="Añadir una nueva textura a la base de datos:", icon='ADD')
        box.prop(props, "new_mat_name", text="Custom")
        box.prop(props, "new_wow_path", text="Ruta (.blp)")
        box.operator("material.wbs_add_to_db", icon='FILE_TICK', text="Añadir a la Base de Datos")

# --- REGISTRO ---

classes = (WMO_Addon_Props, MATERIAL_OT_wbs_add_to_db, MATERIAL_OT_wbs_full_auto_custom, MATERIAL_PT_wbs_custom_panel)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.wmo_auto_props = bpy.props.PointerProperty(type=WMO_Addon_Props)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.wmo_auto_props

if __name__ == "__main__":
    register()