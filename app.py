import io
import math
import zipfile
import ezdxf
from ezdxf import units
import pandas as pd
import streamlit as st

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Enterprise HVAC Staged Engineering Automator", layout="wide"
)
st.title("❄️ Enterprise HVAC Staged Workflow & Plant Automator")
st.markdown(
    "A multi-stage engineering pipeline: upload raw design summaries to generate"
    " standardized schedules, review offline, and upload your enhanced schedule"
    " to compile consultant-grade P&ID DXFs, hydraulic pump calculations, and"
    " CSI Division 23 BOQs."
)

# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
  st.header("1. Plant System Architecture")
  chw_system_type = st.selectbox(
      "Chilled Water Flow System",
      [
          "Primary variable",
          "Primary-Secondary Variable",
          "Primary Constant + Variable Secondary",
      ],
  )
  num_chillers = st.number_input(
      "Number of Chillers", min_value=1, max_value=6, value=2
  )
  total_plant_tr = st.number_input(
      "Total Plant Cooling Capacity (TR)", value=1200.0
  )

  st.header("2. Building Geometry & Hydraulics")
  floor_height_ft = st.number_input(
      "Floor-to-Floor Height (ft)", value=12.0, step=1.0
  )
  plant_to_riser_ft = st.number_input(
      "Plant Room to Riser Base Distance (ft)", value=120.0, step=10.0
  )
  avg_branch_ft = st.number_input(
      "Avg Riser-to-Equipment Branch Length (ft)", value=45.0, step=5.0
  )
  delta_t_f = st.number_input("Design Delta T (°F)", value=14.0)
  max_vel_fps = st.number_input("Max Allowable Velocity (fps)", value=8.0)
  design_friction_rate = st.number_input(
      "Design Friction Rate (ft / 100 ft)", value=2.5
  )
  insulation_thickness = st.selectbox(
      "Chilled Water Insulation Thickness", ["25mm", "38mm", "50mm"]
  )

# Standard Pipe Size Array (Inches)
standard_sizes = [
    0.5,
    0.75,
    1.0,
    1.25,
    1.5,
    2.0,
    2.5,
    3.0,
    4.0,
    5.0,
    6.0,
    8.0,
    10.0,
    12.0,
    14.0,
    16.0,
    18.0,
    20.0,
    24.0,
    30.0,
    36.0,
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
      [
          (x - 1.2, y + 0.8),
          (x + 1.2, y - 0.8),
          (x + 1.2, y + 0.8),
          (x - 1.2, y - 0.8),
          (x - 1.2, y + 0.8),
      ],
      dxfattribs={"layer": layer},
  )
  msp.add_text(
      tag, dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}
  ).set_placement((x - 1.5, y + 1.0))


def draw_control_valve(msp, x, y, tag="MCV", layer="VALVES"):
  msp.add_lwpolyline(
      [
          (x - 1.2, y + 0.8),
          (x + 1.2, y - 0.8),
          (x + 1.2, y + 0.8),
          (x - 1.2, y - 0.8),
          (x - 1.2, y + 0.8),
      ],
      dxfattribs={"layer": layer},
  )
  msp.add_line((x, y + 0.8), (x, y + 2.2), dxfattribs={"layer": layer})
  msp.add_lwpolyline(
      [
          (x - 1.0, y + 2.2),
          (x + 1.0, y + 2.2),
          (x + 1.0, y + 3.2),
          (x - 1.0, y + 3.2),
          (x - 1.0, y + 2.2),
      ],
      dxfattribs={"layer": layer},
  )
  msp.add_text(
      tag, dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}
  ).set_placement((x - 1.5, y + 3.4))


def draw_strainer(msp, x, y, layer="VALVES"):
  msp.add_circle((x, y), radius=1.0, dxfattribs={"layer": layer})
  msp.add_line((x - 1.0, y + 1.0), (x + 1.0, y - 1.0), dxfattribs={"layer": layer})
  msp.add_text(
      "STR", dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}
  ).set_placement((x - 1.2, y + 1.3))


def draw_instrument(msp, x, y, label="PI/TI", layer="INSTRUMENTATION"):
  msp.add_circle((x, y), radius=1.2, dxfattribs={"layer": layer})
  msp.add_text(
      label, dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}
  ).set_placement((x - 1.5, y + 1.5))


# --- STAGE TABS ---
tab1, tab2 = st.tabs(
    ["Stage 1: Generate Schedule Template", "Stage 2: Compile Final Package"]
)

with tab1:
  st.header("Stage 1: Raw Summary Ingestion & Template Export")
  st.markdown(
      "Upload your raw design summary or load sheet. The app will parse the"
      " data and generate a standardized AHU schedule template for your review"
      " and grouping."
  )

  raw_summary_file = st.file_uploader(
      "Upload Raw Design Summary (.xlsx)", type=["xlsx"], key="raw_upload"
  )

  if raw_summary_file:
    try:
      df_raw = pd.read_excel(raw_summary_file)
      df_raw.columns = df_raw.columns.str.strip()

      # Map columns intelligently
      rename_map = {}
      for col in df_raw.columns:
        c_lower = col.lower()
        if "riser" in c_lower:
          rename_map[col] = "Riser_ID"
        elif "floor" in c_lower:
          rename_map[col] = "Floor"
        elif "tag" in c_lower or "ahu" in c_lower or "equipment" in c_lower:
          rename_map[col] = "AHU_Tag"
        elif c_lower in ["gpm", "flow", "design_gpm", "flow_gpm"]:
          rename_map[col] = "Design_GPM"
        elif c_lower in ["tr", "ton", "tons", "rt", "cooling_tr"]:
          rename_map[col] = "TR"

      df_raw = df_raw.rename(columns=rename_map)

      if "TR" in df_raw.columns and "Design_GPM" not in df_raw.columns:
        df_raw["Design_GPM"] = df_raw["TR"] * gpm_factor
      elif "Design_GPM" in df_raw.columns and "TR" not in df_raw.columns:
        df_raw["TR"] = df_raw["Design_GPM"] / gpm_factor

      # Ensure standard template columns exist
      template_cols = [
          "Riser_ID",
          "Floor",
          "AHU_Tag",
          "TR",
          "Design_GPM",
          "Notes / Grouping",
      ]
      for c in template_cols:
        if c not in df_raw.columns:
          df_raw[c] = (
              ""
              if c != "Riser_ID" and c != "Floor"
              else (1 if c == "Riser_ID" else 1)
          )

      df_template = df_raw[template_cols].sort_values(
          by=["Riser_ID", "Floor"]
      )

      st.success("✅ Raw summary parsed successfully into template format!")
      st.dataframe(df_template, use_container_width=True)

      # Export to Excel buffer for download
      template_buffer = io.BytesIO()
      with pd.ExcelWriter(template_buffer, engine="openpyxl") as writer:
        df_template.to_excel(writer, index=False, sheet_name="AHU_Schedule")
      template_data = template_buffer.getvalue()

      st.download_button(
          label="📥 Download Standardized AHU Schedule Template (.xlsx)",
          data=template_data,
          file_name="AHU_Schedule_Review_Template.xlsx",
          mime=(
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ),
      )
      st.info(
          "👉 Download this template, review/edit the risers and floors offline,"
          " and proceed to **Stage 2** when ready."
      )

    except Exception as e:
      st.error(f"Error parsing raw summary file: {e}")

with tab2:
  st.header("Stage 2: Upload Edited Schedule & Compile Final Package")
  st.markdown(
      "Upload your reviewed, grouped, and enhanced AHU schedule Excel sheet."
      " The application will execute precise hydraulic sizing, plant room"
      " layout generation, and package creation."
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

      if st.button(
          "🚀 Run Hydraulics & Compile Submittal Package", type="primary"
      ):
        with st.spinner(
            "Executing hydraulic calculations, friction modeling, and package"
            " compilation..."
        ):

          total_chw_gpm = df_edit["Design_GPM"].sum()
          max_floor_num = df_edit["Floor"].max()
          unique_risers = df_edit["Riser_ID"].unique()
          actual_num_risers = len(unique_risers)

          header_length_ft = plant_to_riser_ft + (actual_num_risers * 120)
          total_riser_length_ft = (
              max_floor_num * floor_height_ft * actual_num_risers * 2
          )
          total_branch_length_ft = len(df_edit) * avg_branch_ft * 2
          grand_total_chw_pipe_ft = (
              header_length_ft + total_riser_length_ft + total_branch_length_ft
          )

          effective_friction_length_ft = grand_total_chw_pipe_ft * 1.5
          chw_friction_head_ft = (
              effective_friction_length_ft / 100.0
          ) * design_friction_rate

          total_chw_pump_tdh_ft = (
              chw_friction_head_ft
              + 14.0  # Evaporator drop
              + 12.0  # AHU coil drop
              + 10.0  # Control valves
              + 5.0  # Balancing valves
              + 5.0  # Strainer
          )

          ct_lift_ft = max_floor_num * floor_height_ft * 0.45 + 40.0
          cw_pipe_length_ft = num_chillers * 200.0
          cw_friction_head_ft = (cw_pipe_length_ft * 1.5 / 100.0) * 3.0
          total_cw_pump_tdh_ft = (
              ct_lift_ft
              + cw_friction_head_ft
              + 14.0  # Condenser drop
              + 10.0  # Cooling tower spray head
          )

          # --- DXF CREATION ---
          doc = ezdxf.new(dxfversion="R2010")
          doc.header["$LTSCALE"] = 100.0
          doc.header["$INSUNITS"] = units.MM
          msp = doc.modelspace()

          # Layers
          doc.layers.add("CHWS_PIPE", color=5)
          doc.layers.add("CHWR_PIPE", color=1)
          doc.layers.add("CDWS_PIPE", color=4)
          doc.layers.add("CDWR_PIPE", color=6)
          doc.layers.add("VALVES", color=3)
          doc.layers.add("INSTRUMENTATION", color=2)
          doc.layers.add("PLANT_EQUIP", color=7)
          doc.layers.add("ANNOTATIONS", color=7)

          # AHU Block definition
          ahu_blk = doc.blocks.new(name="EQ-AHU-STD")
          ahu_blk.add_lwpolyline(
              [(0, 0), (24, 0), (24, 16), (0, 16), (0, 0)],
              dxfattribs={"layer": "PLANT_EQUIP"},
          )
          ahu_blk.add_circle(
              (12, 8), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"}
          )
          ahu_blk.add_attdef(
              "EQUIP_TAG",
              (12, 12),
              "Tag:",
              dxfattribs={"height": 1.2, "layer": "ANNOTATIONS"},
          )
          ahu_blk.add_attdef(
              "CAPACITY",
              (12, 4),
              "Capacity:",
              dxfattribs={"height": 0.9, "layer": "ANNOTATIONS"},
          )

          boq_dict = {}

          def add_csi_item(csi_code, desc, size_rating, qty, unit="EA"):
            key = (csi_code, desc, size_rating, unit)
            boq_dict[key] = boq_dict.get(key, 0.0) + qty

          # Plant Room Layout
          plant_origin_x = -160
          plant_origin_y = 0
          chiller_capacity_tr = total_plant_tr / num_chillers
          chiller_gpm = chiller_capacity_tr * gpm_factor
          chiller_pipe = calc_pipe_size(chiller_gpm)

          msp.add_text(
              f"CHILLER PLANT ROOM | ARCHITECTURE: {chw_system_type.upper()}",
              dxfattribs={"height": 2.2, "layer": "ANNOTATIONS"},
          ).set_placement((plant_origin_x, plant_origin_y + 55))
          msp.add_text(
              (
                  f"DESIGN PUMP HEADS -> Primary CHW TDH:"
                  f" {total_chw_pump_tdh_ft:.1f} ft | Condenser Water TDH:"
                  f" {total_cw_pump_tdh_ft:.1f} ft"
              ),
              dxfattribs={"height": 1.4, "layer": "ANNOTATIONS"},
          ).set_placement((plant_origin_x, plant_origin_y + 50))

          ct_gpm = chiller_gpm * 1.25
          ct_pipe = calc_pipe_size(ct_gpm)

          for c in range(num_chillers):
            cx = plant_origin_x + (c * 65)
            cy = plant_origin_y + 15

            msp.add_lwpolyline(
                [(cx, cy), (cx + 40, cy), (cx + 40, cy + 20), (cx, cy + 20), (cx, cy)],
                dxfattribs={"layer": "PLANT_EQUIP"},
            )
            msp.add_text(
                f"CH-{c+1}\n{chiller_capacity_tr:.0f}TR",
                dxfattribs={"height": 0.9, "layer": "ANNOTATIONS"},
            ).set_placement((cx + 5, cy + 6))
            add_csi_item(
                "23 64 23",
                "Water-Chillers (Water Cooled Packaged Unit)",
                f"{chiller_capacity_tr:.1f} TR",
                1,
                "EA",
            )

            px = cx + 20
            py = cy - 8
            msp.add_circle(
                (px, py), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"}
            )
            msp.add_text(
                f"P-CH-{c+1}", dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}
            ).set_placement((px - 5, py - 5))
            add_csi_item(
                "23 21 23",
                "Hydronic Pumps (Primary End-Suction Centrifugal)",
                f'{chiller_pipe}" Size @ {total_chw_pump_tdh_ft:.1f} ft TDH',
                1,
                "EA",
            )

            cty = plant_origin_y + 65
            msp.add_lwpolyline(
                [(cx, cty), (cx + 40, cty), (cx + 40, cty + 20), (cx, cty + 20), (cx, cty)],
                dxfattribs={"layer": "PLANT_EQUIP"},
            )
            msp.add_text(
                f"CT-{c+1}", dxfattribs={"height": 0.9, "layer": "ANNOTATIONS"}
            ).set_placement((cx + 10, cty + 6))
            add_csi_item(
                "23 65 00",
                "Induced-Draft Crossflow Cooling Towers",
                f"{ct_gpm:.1f} GPM",
                1,
                "EA",
            )

            cwp_y = cty - 10
            msp.add_circle(
                (px, cwp_y), radius=3.5, dxfattribs={"layer": "PLANT_EQUIP"}
            )
            msp.add_text(
                f"P-CW-{c+1}", dxfattribs={"height": 0.8, "layer": "ANNOTATIONS"}
            ).set_placement((px - 5, cwp_y - 5))
            add_csi_item(
                "23 21 23",
                "Condenser Water Centrifugal Pumps",
                f'{ct_pipe}" Size @ {total_cw_pump_tdh_ft:.1f} ft TDH',
                1,
                "EA",
            )

            msp.add_line(
                (px, cy + 20), (px, cty), dxfattribs={"layer": "CDWS_PIPE"}
            )
            add_csi_item(
                "23 21 13",
                "Condenser Water Piping (Carbon Steel ASTM A53 Gr. B)",
                f'{ct_pipe}" Dia',
                140,
                "ft",
            )

          # Main Headers & Risers
          header_gpm = total_chw_gpm
          header_pipe = calc_pipe_size(header_gpm)
          riser_spacing = 90
          floor_height = 25
          header_offset = 15
          header_length = (actual_num_risers * riser_spacing) + 50

          msp.add_line(
              (0, 0), (header_length, 0), dxfattribs={"layer": "CHWS_PIPE"}
          )
          msp.add_line(
              (0, -header_offset),
              (header_length, -header_offset),
              dxfattribs={"layer": "CHWR_PIPE"},
          )

          add_csi_item(
              "23 21 13",
              "Hydronic Piping - Chilled Water Main Header (Supply & Return)",
              f'{header_pipe}" Dia',
              header_length_ft,
              "ft",
          )
          add_csi_item(
              "23 07 19",
              f"HVAC Piping Insulation ({insulation_thickness} Elastomeric Nitril)",
              f'{header_pipe}" Size',
              header_length_ft,
              "ft",
          )

          draw_valve(msp, 20, 0, "BFV", "VALVES")
          draw_valve(msp, 20, -header_offset, "BFV", "VALVES")
          add_csi_item(
              "23 05 23",
              "Butterfly Valve (Isolation - Main Header)",
              f'{header_pipe}" Size',
              2,
              "EA",
          )

          for i, riser_id in enumerate(unique_risers):
            riser_data = df_edit[df_edit["Riser_ID"] == riser_id].sort_values(
                by="Floor"
            )
            riser_gpm = riser_data["Design_GPM"].sum()
            riser_tr = riser_data["TR"].sum()
            riser_pipe = calc_pipe_size(riser_gpm)

            r_chws_x = (i + 1) * riser_spacing
            r_chwr_x = r_chws_x + 10
            max_floor = riser_data["Floor"].max()
            riser_top_y = (max_floor * floor_height) + 15

            msp.add_line(
                (r_chws_x, 0),
                (r_chws_x, riser_top_y),
                dxfattribs={"layer": "CHWS_PIPE"},
            )
            msp.add_line(
                (r_chwr_x, -header_offset),
                (r_chwr_x, riser_top_y),
                dxfattribs={"layer": "CHWR_PIPE"},
            )

            add_csi_item(
                "23 21 13",
                (
                    f"Hydronic Piping - Chilled Water Riser {riser_id} (Supply"
                    " & Return)"
                ),
                f'{riser_pipe}" Dia',
                riser_top_y * 2,
                "ft",
            )
            add_csi_item(
                "23 07 19",
                f"HVAC Piping Insulation ({insulation_thickness} Elastomeric Nitril)",
                f'{riser_pipe}" Size',
                riser_top_y * 2,
                "ft",
            )

            draw_valve(msp, r_chws_x, 5, "BFV", "VALVES")
            draw_valve(msp, r_chwr_x, 5, "BFV", "VALVES")
            draw_instrument(
                msp, r_chws_x, riser_top_y - 5, "DPT", "INSTRUMENTATION"
            )
            add_csi_item(
                "23 05 19",
                (
                    "Differential Pressure Transmitter (DPT) - Riser"
                    f" {riser_id}"
                ),
                f'{riser_pipe}" Loop',
                1,
                "EA",
            )

            for _, row in riser_data.iterrows():
              floor_y = row["Floor"] * floor_height
              ahu_tag = row["AHU_Tag"]
              ahu_gpm = row["Design_GPM"]
              ahu_tr = row["TR"]
              ahu_pipe = calc_pipe_size(ahu_gpm)
              branch_end_x = r_chwr_x + 35

              msp.add_line(
                  (r_chws_x, floor_y),
                  (branch_end_x, floor_y),
                  dxfattribs={"layer": "CHWS_PIPE"},
              )
              msp.add_line(
                  (r_chwr_x, floor_y - 6),
                  (branch_end_x, floor_y - 6),
                  dxfattribs={"layer": "CHWR_PIPE"},
              )

              ahu_ref = msp.add_blockref(
                  "EQ-AHU-STD", insert=(branch_end_x + 2, floor_y - 8)
              )
              ahu_ref.add_attrib("EQUIP_TAG", str(ahu_tag))
              ahu_ref.add_attrib("CAPACITY", f"{ahu_tr:.1f}TR")

              add_csi_item(
                  "23 73 13",
                  f"Indoor Central-Station Air-Handling Unit ({ahu_tag})",
                  f"{ahu_tr:.1f} TR / {ahu_gpm:.1f} GPM",
                  1,
                  "EA",
              )
              add_csi_item(
                  "23 21 13",
                  f"Hydronic Piping - AHU Branch Line ({ahu_tag})",
                  f'{ahu_pipe}" Dia',
                  avg_branch_ft * 2,
                  "ft",
              )
              add_csi_item(
                  "23 07 19",
                  f"HVAC Piping Insulation ({insulation_thickness} Elastomeric Nitril)",
                  f'{ahu_pipe}" Size',
                  avg_branch_ft * 2,
                  "ft",
              )

              draw_valve(msp, r_chws_x + 8, floor_y, "BFV", "VALVES")
              draw_strainer(msp, r_chws_x + 15, floor_y, "VALVES")
              draw_control_valve(msp, r_chws_x + 22, floor_y, "MCV", "VALVES")
              draw_instrument(
                  msp, r_chws_x + 28, floor_y + 2, "PI/TI", "INSTRUMENTATION"
              )

              draw_valve(msp, r_chwr_x + 8, floor_y - 6, "BFV", "VALVES")
              draw_instrument(
                  msp, r_chwr_x + 20, floor_y - 4, "PI/TI", "INSTRUMENTATION"
              )

              add_csi_item(
                  "23 05 23",
                  "Butterfly Valve (Isolation - Equipment Drop)",
                  f'{ahu_pipe}" Size',
                  2,
                  "EA",
              )
              add_csi_item(
                  "23 21 16",
                  "Y-Strainer with SS Screen",
                  f'{ahu_pipe}" Size',
                  1,
                  "EA",
              )
              add_csi_item(
                  "23 09 23",
                  "Motorized 2-Way Control Valve with Actuator",
                  f'{ahu_pipe}" Size',
                  1,
                  "EA",
              )
              add_csi_item(
                  "23 05 23",
                  "Manual Hydronic Balancing Valve",
                  f'{ahu_pipe}" Size',
                  1,
                  "EA",
              )
              add_csi_item(
                  "23 05 19",
                  "Pressure & Temperature Gauge Assembly (PI/TI Set)",
                  f'{ahu_pipe}" Size',
                  2,
                  "SET",
              )

          dxf_stream = io.StringIO()
          doc.write(dxf_stream)

          boq_rows = []
          for (csi_code, desc, size_rating, unit), qty in sorted(
              boq_dict.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])
          ):
            boq_rows.append({
                "CSI Section": csi_code,
                "Item Description": desc,
                "Size / Rating": size_rating,
                "Quantity": round(qty, 1) if unit == "ft" else int(qty),
                "Unit": unit,
            })
          boq_df = pd.DataFrame(boq_rows)

          excel_buffer = io.BytesIO()
          with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            boq_df.to_excel(
                writer, index=False, sheet_name="CSI_Division_23_BOQ"
            )

          zip_buffer = io.BytesIO()
          with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "Plant_and_Riser_HVAC_Schematic.dxf", dxf_stream.getvalue()
            )
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
    c1.metric(
        "Calculated Primary CHW Pump TDH",
        f"{st.session_state['tdh_chw']:.1f} ft",
    )
    c2.metric(
        "Calculated Condenser Water Pump TDH",
        f"{st.session_state['tdh_cw']:.1f} ft",
    )

    st.download_button(
        "📥 Download Complete Submittal Package (.zip)",
        data=st.session_state["zip_data"],
        file_name="HVAC_Enterprise_Submittal_Package.zip",
        mime="application/zip",
    )

    st.subheader("CSI MasterFormat Division 23 Bill of Quantities Preview")
    st.dataframe(st.session_state["boq_df"], use_container_width=True)
