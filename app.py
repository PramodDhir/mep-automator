import io
import math
import zipfile
import ezdxf
from ezdxf import units
import pandas as pd
import streamlit as st

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Enterprise HVAC Staged Automator & Plant Suite", layout="wide"
)
st.title("❄️ Enterprise HVAC Staged Workflow, BOD & Plant Automator")
st.markdown(
    "Senior Consultancy Pipeline: Ingest your Project Basis of Design (BOD),"
    " generate bidirectional ASHRAE-grade equipment schedule templates, and"
    " compile precise P&ID DXFs, hydraulic pump calculations, and CSI Division"
    " 23 BOQs."
)

# --- SIDEBAR: BASIS OF DESIGN (BOD) UPLOAD ---
with st.sidebar:
  st.header("1. Project Basis of Design (BOD)")
  bod_file = st.file_uploader(
      "Upload 'System and project Description.xlsx'",
      type=["xlsx"],
      help="Incorporate project BOD parameters automatically.",
  )

# Parse BOD if uploaded
bod_data = {}
if bod_file is not None:
  try:
    df_bod = pd.read_excel(bod_file, sheet_name="Sheet1")
    for idx, row in df_bod.dropna(subset=["Item"]).iterrows():
      item_name = str(row["Item"]).strip()
      val = str(row["Type / Description"]).strip()
      bod_data[item_name] = val
  except Exception as e:
    st.sidebar.warning(f"Could not parse BOD file: {e}")

# Extract BOD parameters with engineering defaults
project_employer = bod_data.get("Employer", "ITC Hotels")
project_location = bod_data.get("Location", "Colombo")
building_typology = bod_data.get("Building typology", "Mixed use")
building_height = bod_data.get("Building height", "High rise (124 M)")
chw_temp_range = bod_data.get(
    "Chilled water temperature range", "42 Deg F (out) ; 56 Deg F (In)"
)
cw_temp_range = bod_data.get(
    "Condenser water temperature range",
    "91.5 Deg F (In) ; 101.5 Deg F (out)",
)
pumping_system_default = bod_data.get(
    "Chilled water pumping system", "Primary variable"
)
num_floors_default = int(
    float(bod_data.get("Number of floors (above ground)", 24))
)
num_basements_default = int(float(bod_data.get("Number of basements", 3)))
num_risers_default = int(
    float(bod_data.get("No. of Chilled water Risers", 6))
)
chiller_type_default = bod_data.get(
    "Type of chiller", "Air to water (Water cooled)"
)
chiller_loc = bod_data.get("Chiller Plant location", "Basement")
ct_loc = bod_data.get("Cooling tower location", "Terrace")

# --- ITEM 23 ENFORCEMENT ---
bod_tap_off = bod_data.get("Chilled water Tap-off from riser", "Left & Right")

delta_t_default = 14.0
if "42" in chw_temp_range and "56" in chw_temp_range:
  delta_t_default = 14.0

# --- SIDEBAR CONFIGURATION OVERRIDES ---
with st.sidebar:
  st.header("2. Plant Architecture (BOD Linked)")
  chw_system_type = st.selectbox(
      "Chilled Water Flow System",
      [
          "Primary variable",
          "Primary-Secondary Variable",
          "Primary Constant + Variable Secondary",
      ],
      index=0 if "variable" in pumping_system_default.lower() else 1,
  )
  num_chillers = st.number_input(
      "Number of Chillers", min_value=1, max_value=6, value=2
  )
  total_plant_tr = st.number_input(
      "Total Plant Cooling Capacity (TR)", value=1200.0
  )

  st.header("3. Building Geometry & Hydraulics")
  floor_height_ft = st.number_input(
      "Floor-to-Floor Height (ft)", value=12.0, step=1.0
  )
  num_floors = st.number_input(
      "Number of Floors (Above Ground)",
      min_value=1,
      max_value=100,
      value=num_floors_default,
  )
  num_risers = st.number_input(
      "Number of Chilled Water Risers",
      min_value=1,
      max_value=12,
      value=num_risers_default,
  )
  plant_to_riser_ft = st.number_input(
      "Plant Room to Riser Base Distance (ft)", value=120.0, step=10.0
  )
  avg_branch_ft = st.number_input(
      "Avg Riser-to-Equipment Branch Length (ft)", value=45.0, step=5.0
  )
  delta_t_f = st.number_input("Design Delta T (°F)", value=delta_t_default)
  max_vel_fps = st.number_input("Max Allowable Velocity (fps)", value=8.0)
  design_friction_rate = st.number_input(
      "Design Friction Rate (ft / 100 ft)", value=2.5
  )
  insulation_thickness = st.selectbox(
      "Chilled Water Insulation Thickness", ["25mm", "38mm", "50mm"]
  )

# Display BOD Summary Expander if uploaded
if bod_file is not None:
  with st.expander(
      "📋 Active Project Basis of Design (BOD) Parameters", expanded=False
  ):
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Employer:** {project_employer}")
    c1.markdown(f"**Location:** {project_location}")
    c1.markdown(f"**Typology:** {building_typology}")
    c2.markdown(f"**Building Height:** {building_height}")
    c2.markdown(f"**CHW Temp Range:** {chw_temp_range}")
    c2.markdown(f"**CW Temp Range:** {cw_temp_range}")
    c3.markdown(f"**Pumping System:** {pumping_system_default}")
    c3.markdown(f"**Tap-off Topology:** {bod_tap_off}")
    c3.markdown(f"**Chiller Location:** {chiller_loc}")
    c3.markdown(f"**Cooling Tower Location:** {ct_loc}")

# Standard Pipe Size Array (Inches)
standard_sizes = [
    0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 30.0, 36.0,
]
gpm_factor = 24.0 / delta_t_f


def calc_pipe_size(gpm):
  if gpm <= 0:
    return 0.5
  theoretical_dia = math.sqrt(gpm / (2.448 * max_vel_fps))
  for size in standard_sizes:
    if size >= theoretical_dia:
      return size
  return standard_sizes[-1]


# --- DXF GRAPHICAL SYMBOL HELPERS ---
def draw_valve(msp, x, y, tag="BFV", layer="VALVES"):
  msp.add_lwpolyline(
      [(x - 1.2, y + 0.8), (x + 1.2, y - 0.8), (x + 1.2, y + 0.8), (x - 1.2, y - 0.8), (x - 1.2, y + 0.8)],
      dxfattribs={"layer": layer},
  )
  msp.add_text(tag, dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}).set_placement((x - 1.5, y + 1.0))


def draw_control_valve(msp, x, y, tag="MCV", layer="VALVES"):
  msp.add_lwpolyline(
      [(x - 1.2, y + 0.8), (x + 1.2, y - 0.8), (x + 1.2, y + 0.8), (x - 1.2, y - 0.8), (x - 1.2, y + 0.8)],
      dxfattribs={"layer": layer},
  )
  msp.add_line((x, y + 0.8), (x, y + 2.2), dxfattribs={"layer": layer})
  msp.add_lwpolyline(
      [(x - 1.0, y + 2.2), (x + 1.0, y + 2.2), (x + 1.0, y + 3.2), (x - 1.0, y + 3.2), (x - 1.0, y + 2.2)],
      dxfattribs={"layer": layer},
  )
  msp.add_text(tag, dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}).set_placement((x - 1.5, y + 3.4))


def draw_strainer(msp, x, y, layer="VALVES"):
  msp.add_circle((x, y), radius=1.0, dxfattribs={"layer": layer})
  msp.add_line((x - 1.0, y + 1.0), (x + 1.0, y - 1.0), dxfattribs={"layer": layer})
  msp.add_text("STR", dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}).set_placement((x - 1.2, y + 1.3))


def draw_instrument(msp, x, y, label="PI/TI", layer="INSTRUMENTATION"):
  msp.add_circle((x, y), radius=1.2, dxfattribs={"layer": layer})
  msp.add_text(label, dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}).set_placement((x - 1.5, y + 1.5))


# --- STAGED TABS ---
tab1, tab2 = st.tabs(
    ["Stage 1: Generate Schedule Template", "Stage 2: Compile Final Package"]
)

with tab1:
  st.header("Stage 1: Raw Summary Ingestion & Consultant Schedule Template")
  st.markdown(
      "Upload your raw design load summary. The app will parse the data and"
      " generate a fully formatted, professional **Consultant AHU/Equipment"
      " Schedule Template**. If your BOD specifies Left & Right tap-offs, it will automatically split the loads across two branches per floor."
  )

  raw_summary_file = st.file_uploader(
      "Upload Raw Design Summary (.xlsx)", type=["xlsx"], key="raw_upload"
  )

  if raw_summary_file:
    try:
      df_raw = pd.read_excel(raw_summary_file)
      df_raw.columns = df_raw.columns.str.strip()

      rename_map = {}
      for col in df_raw.columns:
        c_lower = col.lower()
        if "riser" in c_lower:
          rename_map[col] = "Riser_ID"
        elif "floor" in c_lower:
          rename_map[col] = "Floor"
        elif "tag" in c_lower or "ahu" in c_lower or "equipment" in c_lower:
          rename_map[col] = "Equipment_Tag"
        elif c_lower in ["gpm", "flow", "design_gpm", "flow_gpm"]:
          rename_map[col] = "Design_GPM"
        elif c_lower in ["tr", "ton", "tons", "rt", "cooling_tr"]:
          rename_map[col] = "Total_TR"

      df_raw = df_raw.rename(columns=rename_map)

      num_rows = len(df_raw)
      if "Equipment_Tag" not in df_raw.columns:
        df_raw["Equipment_Tag"] = [f"AHU-{i+1:02d}" for i in range(num_rows)]
      if "Floor" not in df_raw.columns:
        df_raw["Floor"] = [(i % 24) + 1 for i in range(num_rows)]
      if "Riser_ID" not in df_raw.columns:
        df_raw["Riser_ID"] = [(i % num_risers) + 1 for i in range(num_rows)]
      if "Total_TR" not in df_raw.columns:
        df_raw["Total_TR"] = 25.0

      # ITEM 23 IMPLEMENTATION: Splitting loads for Left & Right taps
      if "Tap_Direction" not in df_raw.columns:
        if "Left & Right" in bod_tap_off:
          left_df = df_raw.copy()
          left_df["Tap_Direction"] = "Left"
          left_df["Equipment_Tag"] = left_df["Equipment_Tag"].astype(str) + "-L"
          left_df["Total_TR"] = left_df["Total_TR"] / 2.0
          
          right_df = df_raw.copy()
          right_df["Tap_Direction"] = "Right"
          right_df["Equipment_Tag"] = right_df["Equipment_Tag"].astype(str) + "-R"
          right_df["Total_TR"] = right_df["Total_TR"] / 2.0
          
          df_raw = pd.concat([left_df, right_df], ignore_index=True)
        else:
          df_raw["Tap_Direction"] = "Right"

      # Re-calculate dependents post-split
      df_raw["Sensible_TR"] = df_raw["Total_TR"] * 0.75
      df_raw["Airflow_CFM"] = df_raw["Total_TR"] * 400
      if "ESP_inwg" not in df_raw.columns:
        df_raw["ESP_inwg"] = 1.5
      df_raw["Design_GPM"] = df_raw["Total_TR"] * gpm_factor
      if "Entering_Water_Temp_F" not in df_raw.columns:
        df_raw["Entering_Water_Temp_F"] = 42.0
      if "Leaving_Water_Temp_F" not in df_raw.columns:
        df_raw["Leaving_Water_Temp_F"] = 56.0
      if "Entering_Air_DB_WB_F" not in df_raw.columns:
        df_raw["Entering_Air_DB_WB_F"] = "80°F DB / 67°F WB"
      if "Leaving_Air_DB_WB_F" not in df_raw.columns:
        df_raw["Leaving_Air_DB_WB_F"] = "54°F DB / 53°F WB"
      if "Motor_HP" not in df_raw.columns:
        df_raw["Motor_HP"] = 5.0
      if "Notes_Grouping" not in df_raw.columns:
        df_raw["Notes_Grouping"] = "Standard Floor AHU"

      consultant_template_cols = [
          "Riser_ID", "Floor", "Tap_Direction", "Equipment_Tag", "Total_TR", 
          "Sensible_TR", "Airflow_CFM", "ESP_inwg", "Design_GPM",
          "Entering_Water_Temp_F", "Leaving_Water_Temp_F", "Entering_Air_DB_WB_F",
          "Leaving_Air_DB_WB_F", "Motor_HP", "Notes_Grouping",
      ]

      df_template = df_raw[consultant_template_cols].sort_values(
          by=["Riser_ID", "Floor"]
      )

      st.success("✅ Professional Consultant AHU Schedule Template Generated!")
      st.dataframe(df_template, use_container_width=True)

      template_buffer = io.BytesIO()
      with pd.ExcelWriter(template_buffer, engine="openpyxl") as writer:
        df_template.to_excel(writer, index=False, sheet_name="AHU_Schedule")
      template_data = template_buffer.getvalue()

      st.download_button(
          label="📥 Download Consultant-Grade AHU Schedule Template (.xlsx)",
          data=template_data,
          file_name="Consultant_AHU_Equipment_Schedule.xlsx",
          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      )
      st.info(
          "👉 Download this professional template, review and adjust risers, tap directions, and tonnages offline, and proceed to **Stage 2**."
      )

    except Exception as e:
      st.error(f"Error parsing raw summary file: {e}")

with tab2:
  st.header("Stage 2: Upload Edited Schedule & Compile Final Package")
  st.markdown(
      "Upload your reviewed, grouped, and enhanced AHU schedule Excel sheet."
      " The application will map bidirectional tap-offs logically and output your complete CAD and BOQ package."
  )

  edited_schedule_file = st.file_uploader(
      "Upload Edited & Grouped AHU Schedule (.xlsx)",
      type=["xlsx"],
      key="edited_upload",
  )

  if edited_schedule_file:
    try:
      df_edit = pd.read_excel(edited_schedule_file)
      df_edit.columns = df_edit.columns.str.strip()

      st.success("✅ Edited AHU Schedule uploaded and verified!")
      st.dataframe(df_edit, use_container_width=True)

      if st.button("🚀 Run Hydraulics & Compile Submittal Package", type="primary"):
        with st.spinner("Executing bidirectional hydraulic modeling, drafting DXF layouts, and compiling CSI BOQ..."):

          # Safe mapping
          col_gpm = "Design_GPM" if "Design_GPM" in df_edit.columns else df_edit.columns[8]
          col_tr = "Total_TR" if "Total_TR" in df_edit.columns else df_edit.columns[4]
          col_tag = "Equipment_Tag" if "Equipment_Tag" in df_edit.columns else df_edit.columns[3]
          col_floor = "Floor" if "Floor" in df_edit.columns else df_edit.columns[1]
          col_riser = "Riser_ID" if "Riser_ID" in df_edit.columns else df_edit.columns[0]
          
          # Default to Right if Tap_Direction doesn't exist
          if "Tap_Direction" not in df_edit.columns:
              df_edit["Tap_Direction"] = "Right"

          total_chw_gpm = df_edit[col_gpm].sum()
          max_floor_num = df_edit[col_floor].max()
          unique_risers = df_edit[col_riser].unique()
          actual_num_risers = len(unique_risers)

          header_length_ft = plant_to_riser_ft + (actual_num_risers * 160)
          total_riser_length_ft = max_floor_num * floor_height_ft * actual_num_risers * 2
          total_branch_length_ft = len(df_edit) * avg_branch_ft * 2
          grand_total_chw_pipe_ft = header_length_ft + total_riser_length_ft + total_branch_length_ft

          effective_friction_length_ft = grand_total_chw_pipe_ft * 1.5
          chw_friction_head_ft = (effective_friction_length_ft / 100.0) * design_friction_rate

          total_chw_pump_tdh_ft = (
              chw_friction_head_ft + 14.0 + 12.0 + 10.0 + 5.0 + 5.0
          )

          ct_lift_ft = max_floor_num * floor_height_ft * 0.45 + 40.0
          cw_pipe_length_ft = num_chillers * 200.0
          cw_friction_head_ft = (cw_pipe_length_ft * 1.5 / 100.0) * 3.0
          total_cw_pump_tdh_ft = (
              ct_lift_ft + cw_friction_head_ft + 14.0 + 10.0
          )

          # --- DXF CREATION ---
          doc = ezdxf.new(dxfversion="R2010")
          doc.header["$LTSCALE"] = 100.0
          doc.header["$INSUNITS"] = units.MM
          msp = doc.modelspace()

          doc.layers.add("CHWS_PIPE", color=5)
          doc.layers.add("CHWR_PIPE", color=1)
          doc.layers.add("CDWS_PIPE", color=4)
          doc.layers.add("CDWR_PIPE", color=6)
          doc.layers.add("VALVES", color=3)
          doc.layers.add("INSTRUMENTATION", color=2)
          doc.layers.add("PLANT_EQUIP", color=7)
          doc.layers.add("ANNOTATIONS", color=7)

          ahu_blk = doc.blocks.new(name="EQ-AHU-STD")
          ahu_blk.add_lwpolyline(
              [(0, 0), (24, 0), (24, 16), (0, 16), (0, 0)], dxfattribs={"layer": "PLANT_EQUIP"}
          )
          ahu_blk.add_circle((12, 8), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"})
          ahu_blk.add_attdef("EQUIP_TAG", (12, 12), "Tag:", dxfattribs={"height": 1.2, "layer": "ANNOTATIONS"})
          ahu_blk.add_attdef("CAPACITY", (12, 4), "Capacity:", dxfattribs={"height": 0.9, "layer": "ANNOTATIONS"})

          boq_dict = {}

          def add_csi_item(csi_code, desc, size_rating, qty, unit="EA"):
            key = (csi_code, desc, size_rating, unit)
            boq_dict[key] = boq_dict.get(key, 0.0) + qty

          # Plant Room
          plant_origin_x = -200
          plant_origin_y = 0
          chiller_capacity_tr = total_plant_tr / num_chillers
          chiller_gpm = chiller_capacity_tr * gpm_factor
          chiller_pipe = calc_pipe_size(chiller_gpm)

          msp.add_text(
              f"CHILLER PLANT ROOM ({chiller_loc}) | ARCHITECTURE: {chw_system_type.upper()}",
              dxfattribs={"height": 2.2, "layer": "ANNOTATIONS"},
          ).set_placement((plant_origin_x, plant_origin_y + 55))

          ct_gpm = chiller_gpm * 1.25
          ct_pipe = calc_pipe_size(ct_gpm)

          for c in range(num_chillers):
            cx = plant_origin_x + (c * 65)
            cy = plant_origin_y + 15
            msp.add_lwpolyline([(cx, cy), (cx + 40, cy), (cx + 40, cy + 20), (cx, cy + 20), (cx, cy)], dxfattribs={"layer": "PLANT_EQUIP"})
            msp.add_text(f"CH-{c+1}\n{chiller_capacity_tr:.0f}TR", dxfattribs={"height": 0.9, "layer": "ANNOTATIONS"}).set_placement((cx + 5, cy + 6))
            add_csi_item("23 64 23", f"Water-Chillers ({chiller_type_default})", f"{chiller_capacity_tr:.1f} TR", 1, "EA")

            px = cx + 20
            py = cy - 8
            msp.add_circle((px, py), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"})
            msp.add_text(f"P-CH-{c+1}", dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}).set_placement((px - 5, py - 5))
            add_csi_item("23 21 23", "Hydronic Pumps (Primary End-Suction Centrifugal)", f'{chiller_pipe}" Size @ {total_chw_pump_tdh_ft:.1f} ft TDH', 1, "EA")

            cty = plant_origin_y + 65
            msp.add_lwpolyline([(cx, cty), (cx + 40, cty), (cx + 40, cty + 20), (cx, cty + 20), (cx, cty)], dxfattribs={"layer": "PLANT_EQUIP"})
            msp.add_text(f"CT-{c+1}\n({ct_loc})", dxfattribs={"height": 0.9, "layer": "ANNOTATIONS"}).set_placement((cx + 5, cty + 6))
            add_csi_item("23 65 00", "Induced-Draft Crossflow Cooling Towers (CTI Approved)", f"{ct_gpm:.1f} GPM", 1, "EA")

            cwp_y = cty - 10
            msp.add_circle((px, cwp_y), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"})
            msp.add_text(f"P-CW-{c+1}", dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}).set_placement((px - 5, cwp_y - 5))
            add_csi_item("23 21 23", "Condenser Water Centrifugal Pumps", f'{ct_pipe}" Size @ {total_cw_pump_tdh_ft:.1f} ft TDH', 1, "EA")
            msp.add_line((px, cy + 20), (px, cty), dxfattribs={"layer": "CDWS_PIPE"})
            add_csi_item("23 21 13", "Condenser Water Piping (Carbon Steel ASTM A53 Gr. B)", f'{ct_pipe}" Dia', 140, "ft")

          if "Secondary" in chw_system_type:
            for sp in range(2):
              spx = plant_origin_x + 140 + (sp * 25)
              spy = plant_origin_y + 15
              msp.add_circle((spx, spy), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"})
              add_csi_item("23 21 23", "Hydronic Pumps (Secondary Variable Speed Package)", f'{chiller_pipe}" Size', 1, "EA")

          # Main Headers & Risers
          header_gpm = total_chw_gpm
          header_pipe = calc_pipe_size(header_gpm)
          riser_spacing = 130
          floor_height = 25
          header_offset = 15
          header_length = (actual_num_risers * riser_spacing) + 50

          msp.add_line((0, 0), (header_length, 0), dxfattribs={"layer": "CHWS_PIPE"})
          msp.add_line((0, -header_offset), (header_length, -header_offset), dxfattribs={"layer": "CHWR_PIPE"})

          add_csi_item("23 21 13", "Hydronic Piping - Chilled Water Main Header (Supply & Return)", f'{header_pipe}" Dia', header_length_ft, "ft")
          add_csi_item("23 07 19", f"HVAC Piping Insulation ({insulation_thickness} Elastomeric Nitril)", f'{header_pipe}" Size', header_length_ft, "ft")

          draw_valve(msp, 20, 0, "BFV", "VALVES")
          draw_valve(msp, 20, -header_offset, "BFV", "VALVES")
          add_csi_item("23 05 23", "Butterfly Valve (Isolation - Main Header)", f'{header_pipe}" Size', 2, "EA")

          for i, riser_id in enumerate(unique_risers):
            riser_data = df_edit[df_edit[col_riser] == riser_id].sort_values(by=col_floor)
            riser_gpm = riser_data[col_gpm].sum()
            riser_pipe = calc_pipe_size(riser_gpm)

            r_chws_x = (i + 1) * riser_spacing
            r_chwr_x = r_chws_x + 10
            max_floor = riser_data[col_floor].max()
            riser_top_y = (max_floor * floor_height) + 15

            msp.add_line((r_chws_x, 0), (r_chws_x, riser_top_y), dxfattribs={"layer": "CHWS_PIPE"})
            msp.add_line((r_chwr_x, -header_offset), (r_chwr_x, riser_top_y), dxfattribs={"layer": "CHWR_PIPE"})

            add_csi_item("23 21 13", f"Hydronic Piping - Chilled Water Riser {riser_id} (Supply & Return)", f'{riser_pipe}" Dia', riser_top_y * 2, "ft")
            add_csi_item("23 07 19", f"HVAC Piping Insulation ({insulation_thickness})", f'{riser_pipe}" Size', riser_top_y * 2, "ft")
            
            # Riser Isolation
            draw_valve(msp, r_chws_x, 5, "BFV", "VALVES")
            draw_valve(msp, r_chwr_x, 5, "BFV", "VALVES")
            draw_instrument(msp, r_chws_x, riser_top_y - 5, "DPT", "INSTRUMENTATION")
            add_csi_item("23 05 19", f"Differential Pressure Transmitter (DPT) - Riser {riser_id}", f'{riser_pipe}" Loop', 1, "EA")

            # Bidirectional Drafting Implementation
            for _, row in riser_data.iterrows():
              floor_y = row[col_floor] * floor_height
              ahu_tag = row[col_tag]
              ahu_gpm = row[col_gpm]
              ahu_tr = row[col_tr]
              ahu_pipe = calc_pipe_size(ahu_gpm)
              tap_dir = str(row["Tap_Direction"]).strip().title()

              if tap_dir == "Left":
                  branch_end_x = r_chws_x - 45
                  
                  # Piping branching Left
                  msp.add_line((r_chws_x, floor_y), (branch_end_x, floor_y), dxfattribs={"layer": "CHWS_PIPE"})
                  msp.add_line((r_chwr_x, floor_y - 6), (branch_end_x, floor_y - 6), dxfattribs={"layer": "CHWR_PIPE"})
                  
                  # AHU Block Left
                  ahu_ref = msp.add_blockref("EQ-AHU-STD", insert=(branch_end_x - 26, floor_y - 8))
                  ahu_ref.add_attrib("EQUIP_TAG", str(ahu_tag))
                  ahu_ref.add_attrib("CAPACITY", f"{ahu_tr:.1f}TR")

                  # Valves branching Left
                  draw_valve(msp, r_chws_x - 8, floor_y, "BFV", "VALVES")
                  draw_strainer(msp, r_chws_x - 15, floor_y, "VALVES")
                  draw_control_valve(msp, r_chws_x - 22, floor_y, "MCV", "VALVES")
                  draw_instrument(msp, r_chws_x - 28, floor_y + 2, "PI/TI", "INSTRUMENTATION")

                  draw_valve(msp, r_chwr_x - 8, floor_y - 6, "BFV", "VALVES")
                  draw_instrument(msp, r_chwr_x - 20, floor_y - 4, "PI/TI", "INSTRUMENTATION")

              else:
                  branch_end_x = r_chwr_x + 45
                  
                  # Piping branching Right
                  msp.add_line((r_chws_x, floor_y), (branch_end_x, floor_y), dxfattribs={"layer": "CHWS_PIPE"})
                  msp.add_line((r_chwr_x, floor_y - 6), (branch_end_x, floor_y - 6), dxfattribs={"layer": "CHWR_PIPE"})

                  # AHU Block Right
                  ahu_ref = msp.add_blockref("EQ-AHU-STD", insert=(branch_end_x + 2, floor_y - 8))
                  ahu_ref.add_attrib("EQUIP_TAG", str(ahu_tag))
                  ahu_ref.add_attrib("CAPACITY", f"{ahu_tr:.1f}TR")

                  # Valves branching Right
                  draw_valve(msp, r_chws_x + 8, floor_y, "BFV", "VALVES")
                  draw_strainer(msp, r_chws_x + 15, floor_y, "VALVES")
                  draw_control_valve(msp, r_chws_x + 22, floor_y, "MCV", "VALVES")
                  draw_instrument(msp, r_chws_x + 28, floor_y + 2, "PI/TI", "INSTRUMENTATION")

                  draw_valve(msp, r_chwr_x + 8, floor_y - 6, "BFV", "VALVES")
                  draw_instrument(msp, r_chwr_x + 20, floor_y - 4, "PI/TI", "INSTRUMENTATION")

              # CSI additions logic triggers per row, accurately doubling BOQ quantities for left/right junctions
              add_csi_item("23 73 13", f"Indoor Central-Station Air-Handling Unit ({ahu_tag})", f"{ahu_tr:.1f} TR / {ahu_gpm:.1f} GPM", 1, "EA")
              add_csi_item("23 21 13", f"Hydronic Piping - AHU Branch Line ({ahu_tag})", f'{ahu_pipe}" Dia', avg_branch_ft * 2, "ft")
              add_csi_item("23 07 19", f"HVAC Piping Insulation ({insulation_thickness} Elastomeric Nitril)", f'{ahu_pipe}" Size', avg_branch_ft * 2, "ft")
              add_csi_item("23 05 23", "Butterfly Valve (Isolation - Equipment Drop)", f'{ahu_pipe}" Size', 2, "EA")
              add_csi_item("23 21 16", "Y-Strainer with SS Screen", f'{ahu_pipe}" Size', 1, "EA")
              add_csi_item("23 09 23", "Motorized 2-Way Control Valve with Actuator", f'{ahu_pipe}" Size', 1, "EA")
              add_csi_item("23 05 23", "Manual Hydronic Balancing Valve", f'{ahu_pipe}" Size', 1, "EA")
              add_csi_item("23 05 19", "Pressure & Temperature Gauge Assembly (PI/TI Set)", f'{ahu_pipe}" Size', 2, "SET")

          dxf_stream = io.StringIO()
          doc.write(dxf_stream)

          boq_rows = []
          for (csi_code, desc, size_rating, unit), qty in sorted(boq_dict.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
            boq_rows.append({"CSI Section": csi_code, "Item Description": desc, "Size / Rating": size_rating, "Quantity": round(qty, 1) if unit == "ft" else int(qty), "Unit": unit})
          boq_df = pd.DataFrame(boq_rows)

          excel_buffer = io.BytesIO()
          with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            boq_df.to_excel(writer, index=False, sheet_name="CSI_Division_23_BOQ")

          zip_buffer = io.BytesIO()
          with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Plant_and_Riser_HVAC_Schematic.dxf", dxf_stream.getvalue())
            zf.writestr("CSI_Division_23_HVAC_BOQ.xlsx", excel_buffer.getvalue())
          zip_buffer.seek(0)

          st.session_state["zip_data"] = zip_buffer.getvalue()
          st.session_state["boq_df"] = boq_df
          st.session_state["tdh_chw"] = total_chw_pump_tdh_ft
          st.session_state["tdh_cw"] = total_cw_pump_tdh_ft
          st.session_state["compiled"] = True

    except Exception as e:
      st.error(f"Error processing edited schedule: {e}")

  if st.session_state.get("compiled", False):
    st.success("🎉 Enterprise Submittal Package Compiled Successfully!")
    c1, c2 = st.columns(2)
    c1.metric("Calculated Primary CHW Pump TDH", f"{st.session_state['tdh_chw']:.1f} ft")
    c2.metric("Calculated Condenser Water Pump TDH", f"{st.session_state['tdh_cw']:.1f} ft")

    st.download_button(
        "📥 Download Complete Submittal Package (.zip)",
        data=st.session_state["zip_data"],
        file_name="HVAC_Enterprise_Submittal_Package.zip",
        mime="application/zip",
    )

    st.subheader("CSI MasterFormat Division 23 Bill of Quantities Preview")
    st.dataframe(st.session_state["boq_df"], use_container_width=True)
