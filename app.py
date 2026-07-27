import io
import math
import zipfile
import ezdxf
from ezdxf import units
import pandas as pd
import streamlit as st

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Advanced HVAC P&ID, Hydraulics & Plant Suite", layout="wide"
)
st.title("❄️ Enterprise HVAC P&ID, Plant Hydraulics & CSI-Format BOQ Automator")
st.markdown(
    "Generate consultant-grade HVAC floor schematics, Chiller Plant Room"
    " layouts, Condenser Water circuits, exact pressure-drop pump sizing, and"
    " size-disaggregated CSI Division 23 BOQs."
)

# --- CONFIGURATION SIDEBAR ---
with st.sidebar:
  st.header("1. Plant System Architecture")
  chw_system_type = st.selectbox(
      "Chilled Water Flow System",
      ["Primary-Secondary Variable", "Primary Variable Flow (VPF)"],
  )

  st.header("2. Plant Capacities & Units")
  num_chillers = st.number_input(
      "Number of Chillers", min_value=1, max_value=4, value=2
  )
  total_plant_tr = st.number_input(
      "Total Plant Cooling Capacity (TR)", value=500.0
  )

  st.header("3. Building Layout & Geometry")
  floor_height_ft = st.number_input(
      "Floor-to-Floor Height (ft)", value=12.0, step=1.0
  )
  plant_to_riser_ft = st.number_input(
      "Plant Room to Riser Base Distance (ft)", value=120.0, step=10.0
  )
  avg_branch_ft = st.number_input(
      "Avg Riser-to-Equipment Branch Length (ft)", value=45.0, step=5.0
  )

  st.header("4. Hydraulic & Insulation Criteria")
  delta_t_f = st.number_input("Design Delta T (°F)", value=12.0)
  max_vel_fps = st.number_input("Max Allowable Velocity (fps)", value=8.0)
  default_tr_to_gpm = st.number_input("GPM per TR Factor", value=2.0)
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
          (x - 2, y + 1.2),
          (x + 2, y - 1.2),
          (x + 2, y + 1.2),
          (x - 2, y - 1.2),
          (x - 2, y + 1.2),
      ],
      dxfattribs={"layer": layer},
  )
  msp.add_text(
      tag, dxfattribs={"height": 1.2, "layer": "ANNOTATIONS"}
  ).set_placement((x - 2.5, y + 1.5))


def draw_control_valve(msp, x, y, tag="MCV", layer="VALVES"):
  msp.add_lwpolyline(
      [
          (x - 2, y + 1.2),
          (x + 2, y - 1.2),
          (x + 2, y + 1.2),
          (x - 2, y - 1.2),
          (x - 2, y + 1.2),
      ],
      dxfattribs={"layer": layer},
  )
  msp.add_line((x, y + 1.2), (x, y + 3.5), dxfattribs={"layer": layer})
  msp.add_lwpolyline(
      [
          (x - 1.5, y + 3.5),
          (x + 1.5, y + 3.5),
          (x + 1.5, y + 5),
          (x - 1.5, y + 5),
          (x - 1.5, y + 3.5),
      ],
      dxfattribs={"layer": layer},
  )
  msp.add_text(
      tag, dxfattribs={"height": 1.2, "layer": "ANNOTATIONS"}
  ).set_placement((x - 2.5, y + 5.2))


def draw_strainer(msp, x, y, layer="VALVES"):
  msp.add_circle((x, y), radius=1.5, dxfattribs={"layer": layer})
  msp.add_line((x - 1.5, y + 1.5), (x + 1.5, y - 1.5), dxfattribs={"layer": layer})
  msp.add_text(
      "STR", dxfattribs={"height": 1.1, "layer": "ANNOTATIONS"}
  ).set_placement((x - 2, y + 2))


def draw_instrument(msp, x, y, label="PI/TI", layer="INSTRUMENTATION"):
  msp.add_circle((x, y), radius=1.8, dxfattribs={"layer": layer})
  msp.add_text(
      label, dxfattribs={"height": 1.1, "layer": "ANNOTATIONS"}
  ).set_placement((x - 2, y + 2.2))


# --- FILE UPLOAD WORKFLOW ---
uploaded_file = st.file_uploader(
    "Upload Building Thermal/Air Load Summary Excel Sheet (.xlsx)",
    type=["xlsx"],
)

if uploaded_file:
  try:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.str.strip()

    rename_map = {}
    for col in df.columns:
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

    df = df.rename(columns=rename_map)

    if "Design_GPM" not in df.columns and "TR" in df.columns:
      df["Design_GPM"] = df["TR"] * default_tr_to_gpm
    elif "TR" not in df.columns and "Design_GPM" in df.columns:
      df["TR"] = df["Design_GPM"] / default_tr_to_gpm
    elif "Design_GPM" not in df.columns and "TR" not in df.columns:
      st.error(
          "❌ Excel sheet must contain either a 'Flow/GPM' column or a"
          " 'TR/Tonnage' column."
      )
      st.stop()

    required_cols = ["Riser_ID", "Floor", "AHU_Tag", "Design_GPM", "TR"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
      st.error(f"❌ Missing required columns: {missing_cols}")
      st.stop()

    st.success("✅ Design Data successfully loaded, mapped, and verified!")
    st.dataframe(df, use_container_width=True)

    if st.button(
        "Run Hydraulic Calculations & Generate Submittal Package",
        type="primary",
    ):
      with st.spinner(
          "Calculating precise pipe friction, pump heads, layout, and BOQ..."
      ):

        # --- PRECISE HYDRAULIC & LENGTH CALCULATIONS ---
        total_chw_gpm = df["Design_GPM"].sum()
        max_floor_num = df["Floor"].max()
        unique_risers = df["Riser_ID"].unique()
        num_risers = len(unique_risers)

        # 1. Physical Pipe Length Totals (Feet)
        header_length_ft = plant_to_riser_ft + (num_risers * 180)
        total_riser_length_ft = (
            max_floor_num * floor_height_ft * num_risers * 2
        )  # Supply + Return
        total_branch_length_ft = (
            len(df) * avg_branch_ft * 2
        )  # Supply + Return drops

        grand_total_chw_pipe_ft = (
            header_length_ft + total_riser_length_ft + total_branch_length_ft
        )

        # 2. Equivalent Length Friction Loss (Including 50% fitting allowance)
        effective_friction_length_ft = grand_total_chw_pipe_ft * 1.5
        chw_friction_head_ft = (
            effective_friction_length_ft / 100.0
        ) * design_friction_rate

        # 3. Component Pressure Drops (Feet of Head)
        chiller_evap_drop_ft = 12.0
        ahu_coil_drop_ft = 12.0
        control_valves_drop_ft = 10.0
        balancing_valves_drop_ft = 5.0
        strainer_drop_ft = 5.0

        total_chw_pump_tdh_ft = (
            chw_friction_head_ft
            + chiller_evap_drop_ft
            + ahu_coil_drop_ft
            + control_valves_drop_ft
            + balancing_valves_drop_ft
            + strainer_drop_ft
        )

        # Condenser Water Hydraulics
        ct_lift_ft = (
            max_floor_num * floor_height_ft * 0.45 + 30.0
        )  # Estimated tower height above plant room
        cw_pipe_length_ft = num_chillers * 250.0
        cw_friction_head_ft = (cw_pipe_length_ft * 1.5 / 100.0) * 3.0
        total_cw_pump_tdh_ft = (
            ct_lift_ft
            + cw_friction_head_ft
            + chiller_evap_drop_ft
            + 8.0  # condenser drop
            + 10.0  # cooling tower nozzle head
        )

        # --- DXF CREATION ---
        doc = ezdxf.new(dxfversion="R2010")
        doc.header["$LTSCALE"] = 500.0
        doc.header["$INSUNITS"] = units.MM
        msp = doc.modelspace()

        # Define Layers
        doc.layers.add("CHWS_PIPE", color=5)
        doc.layers.add("CHWR_PIPE", color=1)
        doc.layers.add("CDWS_PIPE", color=4)
        doc.layers.add("CDWR_PIPE", color=6)
        doc.layers.add("VALVES", color=3)
        doc.layers.add("INSTRUMENTATION", color=2)
        doc.layers.add("PLANT_EQUIP", color=7)
        doc.layers.add("ANNOTATIONS", color=7)

        # --- CREATE UNIFORM BLOCKS WITH ATTRIBUTES ---
        ahu_blk = doc.blocks.new(name="EQ-AHU-STD")
        ahu_blk.add_lwpolyline(
            [(0, 0), (600, 0), (600, 400), (0, 400), (0, 0)],
            dxfattribs={"layer": "PLANT_EQUIP"},
        )
        ahu_blk.add_circle((300, 200), radius=60, dxfattribs={"layer": "PLANT_EQUIP"})
        ahu_blk.add_attdef(
            "EQUIP_TAG",
            (300, 350),
            "Tag:",
            dxfattribs={"height": 25, "layer": "ANNOTATIONS"},
        )
        ahu_blk.add_attdef(
            "CAPACITY",
            (300, 300),
            "Capacity:",
            dxfattribs={"height": 18, "layer": "ANNOTATIONS"},
        )

        boq_dict = {}

        def add_csi_item(csi_code, desc, size_rating, qty, unit="EA"):
          key = (csi_code, desc, size_rating, unit)
          boq_dict[key] = boq_dict.get(key, 0.0) + qty

        # --- CHILLER PLANT ROOM DRAWING SECTION ---
        plant_origin_x = -300
        plant_origin_y = -150
        chiller_capacity_tr = total_plant_tr / num_chillers
        chiller_gpm = chiller_capacity_tr * default_tr_to_gpm
        chiller_pipe = calc_pipe_size(chiller_gpm)

        msp.add_text(
            f"CHILLER PLANT ROOM | ARCHITECTURE: {chw_system_type.upper()}",
            dxfattribs={"height": 4.0, "layer": "ANNOTATIONS"},
        ).set_placement((plant_origin_x, plant_origin_y + 90))

        msp.add_text(
            (
                f"DESIGN PUMP HEADS -> Primary CHW TDH:"
                f" {total_chw_pump_tdh_ft:.1f} ft | Condenser Water TDH:"
                f" {total_cw_pump_tdh_ft:.1f} ft"
            ),
            dxfattribs={"height": 2.5, "layer": "ANNOTATIONS"},
        ).set_placement((plant_origin_x, plant_origin_y + 82))

        for c in range(num_chillers):
          cx = plant_origin_x + (c * 160)
          cy = plant_origin_y + 40
          msp.add_lwpolyline(
              [(cx, cy), (cx + 100, cy), (cx + 100, cy + 50), (cx, cy + 50), (cx, cy)],
              dxfattribs={"layer": "PLANT_EQUIP"},
          )
          msp.add_text(
              f"CH-{c+1}\n({chiller_capacity_tr} TR)",
              dxfattribs={"height": 2.0, "layer": "ANNOTATIONS"},
          ).set_placement((cx + 15, cy + 20))
          add_csi_item(
              "23 64 23",
              "Water-Chillers (Centrifugal / Screw Packaged Unit)",
              f"{chiller_capacity_tr} TR",
              1,
              "EA",
          )

          # Primary Pump with calculated head
          px = cx + 40
          py = cy - 25
          msp.add_circle(
              (px, py), radius=8, dxfattribs={"layer": "PLANT_EQUIP"}
          )
          msp.add_text(
              f"P-CH-{c+1}", dxfattribs={"height": 1.5, "layer": "ANNOTATIONS"}
          ).set_placement((px - 6, py - 14))
          add_csi_item(
              "23 21 23",
              "Hydronic Pumps (Primary End-Suction Centrifugal)",
              f'{chiller_pipe}" Size @ {total_chw_pump_tdh_ft:.1f} ft TDH',
              1,
              "EA",
          )

        if "Primary-Secondary" in chw_system_type:
          for sp in range(2):
            spx = plant_origin_x + 360 + (sp * 60)
            spy = plant_origin_y + 40
            msp.add_circle(
                (spx, spy), radius=8, dxfattribs={"layer": "PLANT_EQUIP"}
            )
            msp.add_text(
                f"P-SEC-{sp+1}", dxfattribs={"height": 1.5, "layer": "ANNOTATIONS"}
            ).set_placement((spx - 8, spy - 14))
            add_csi_item(
                "23 21 23",
                "Hydronic Pumps (Secondary Variable Speed Package)",
                f'{chiller_pipe}" Size @ {(total_chw_pump_tdh_ft * 0.7):.1f} ft TDH',
                1,
                "EA",
            )

        # Cooling Towers & Condenser Circuit
        ct_gpm = chiller_gpm * 1.25
        ct_pipe = calc_pipe_size(ct_gpm)
        for ct in range(num_chillers):
          ctx = plant_origin_x + (ct * 160)
          cty = plant_origin_y + 130
          msp.add_lwpolyline(
              [(ctx, cty), (ctx + 80, cty), (ctx + 80, cty + 40), (ctx, cty + 40), (ctx, cty)],
              dxfattribs={"layer": "PLANT_EQUIP"},
          )
          msp.add_text(
              f"CT-{ct+1}", dxfattribs={"height": 2.0, "layer": "ANNOTATIONS"}
          ).set_placement((ctx + 20, cty + 15))
          add_csi_item(
              "23 65 00",
              "Induced-Draft Crossflow Cooling Towers",
              f"{ct_gpm:.1f} GPM",
              1,
              "EA",
          )

          cwp_x = ctx + 40
          cwp_y = cty - 20
          msp.add_circle(
              (cwp_x, cwp_y), radius=7, dxfattribs={"layer": "PLANT_EQUIP"}
          )
          msp.add_text(
              f"P-CW-{ct+1}", dxfattribs={"height": 1.5, "layer": "ANNOTATIONS"}
          ).set_placement((cwp_x - 6, cwp_y - 12))
          add_csi_item(
              "23 21 23",
              "Condenser Water Centrifugal Pumps",
              f'{ct_pipe}" Size @ {total_cw_pump_tdh_ft:.1f} ft TDH',
              1,
              "EA",
          )

          msp.add_line(
              (ctx + 40, cty),
              (ctx + 40, cty + 40),
              dxfattribs={"layer": "CDWS_PIPE"},
          )
          add_csi_item(
              "23 21 13",
              "Condenser Water Piping (Carbon Steel ASTM A53 Gr. B)",
              f'{ct_pipe}" Dia',
              150,
              "ft",
          )

        # --- MAIN CHILLED WATER RISERS & DISTRIBUTION ---
        header_gpm = total_chw_gpm
        header_tr = df["TR"].sum()
        header_pipe = calc_pipe_size(header_gpm)

        riser_spacing = 180
        floor_height = 55
        header_offset = 30
        header_length = (num_risers * riser_spacing) + 80

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

        draw_valve(msp, 40, 0, "BFV-MAIN", "VALVES")
        draw_valve(msp, 40, -header_offset, "BFV-MAIN", "VALVES")
        add_csi_item(
            "23 05 23",
            "Butterfly Valve (Isolation - Main Header)",
            f'{header_pipe}" Size',
            2,
            "EA",
        )

        # Loop through Risers & Floors
        for i, riser_id in enumerate(unique_risers):
          riser_data = df[df["Riser_ID"] == riser_id].sort_values(by="Floor")
          riser_gpm = riser_data["Design_GPM"].sum()
          riser_tr = riser_data["TR"].sum()
          riser_pipe = calc_pipe_size(riser_gpm)

          r_chws_x = (i + 1) * riser_spacing
          r_chwr_x = r_chws_x + 20
          max_floor = riser_data["Floor"].max()
          riser_top_y = (max_floor * floor_height) + 25

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
                  f"Hydronic Piping - Chilled Water Riser {riser_id} (Supply &"
                  " Return)"
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

          draw_valve(msp, r_chws_x, 10, f"BFV-R{riser_id}", "VALVES")
          draw_valve(msp, r_chwr_x, 10, f"BFV-R{riser_id}", "VALVES")
          draw_instrument(
              msp, r_chws_x, riser_top_y - 10, "DPT", "INSTRUMENTATION"
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
            branch_end_x = r_chwr_x + 65

            msp.add_line(
                (r_chws_x, floor_y),
                (branch_end_x, floor_y),
                dxfattribs={"layer": "CHWS_PIPE"},
            )
            msp.add_line(
                (r_chwr_x, floor_y - 12),
                (branch_end_x, floor_y - 12),
                dxfattribs={"layer": "CHWR_PIPE"},
            )

            # Insert Attributed Block for AHU
            ahu_ref = msp.add_blockref(
                "EQ-AHU-STD", insert=(branch_end_x + 5, floor_y - 20)
            )
            ahu_ref.add_attrib("EQUIP_TAG", str(ahu_tag))
            ahu_ref.add_attrib("CAPACITY", f"{ahu_tr:.1f} TR")

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

            # Valves and Instrumentation on Branch
            draw_valve(msp, r_chws_x + 15, floor_y, "BFV", "VALVES")
            draw_strainer(msp, r_chws_x + 28, floor_y, "VALVES")
            draw_control_valve(msp, r_chws_x + 42, floor_y, "MCV", "VALVES")
            draw_instrument(
                msp, r_chws_x + 55, floor_y + 4, "PI/TI", "INSTRUMENTATION"
            )

            draw_valve(msp, r_chwr_x + 15, floor_y - 12, "BFV", "VALVES")
            draw_valve(msp, r_chwr_x + 35, floor_y - 12, "BV", "VALVES")
            draw_instrument(
                msp, r_chwr_x + 50, floor_y - 8, "PI/TI", "INSTRUMENTATION"
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

        # Output DXF to Memory String
        dxf_stream = io.StringIO()
        doc.write(dxf_stream)

        # Build CSI BOQ DataFrame
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

        # --- CREATE ZIP SUBMITTAL PACKAGE ---
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
        st.session_state["package_ready"] = True

  except Exception as e:
    st.error(
        "Error generating submittal package. Please check input sheet formatting."
        f" Details: {e}"
    )

# --- RESULTS DISPLAY WORKFLOW ---
if st.session_state.get("package_ready", False):
  st.success(
      "🎉 Enterprise Hydraulic Calculations, Plant Room P&ID & CSI BOQ Package"
      " Compiled Successfully!"
  )

  col_m1, col_m2 = st.columns(2)
  col_m1.metric(
      "Calculated Primary CHW Pump TDH",
      f"{st.session_state['tdh_chw']:.1f} ft of Head",
  )
  col_m2.metric(
      "Calculated Condenser Water Pump TDH",
      f"{st.session_state['tdh_cw']:.1f} ft of Head",
  )

  st.download_button(
      label="📥 Download Complete Submittal Package (.zip containing DXF &"
      " Excel BOQ)",
      data=st.session_state["zip_data"],
      file_name="HVAC_Consultant_Hydraulic_Submittal.zip",
      mime="application/zip",
  )

  st.subheader("CSI MasterFormat Division 23 Bill of Quantities Preview")
  st.dataframe(st.session_state["boq_df"], use_container_width=True)
else:
  st.info(
      "👆 Please configure your building geometry and upload your design load"
      " sheet in the sidebar to run hydraulic calculations and generate the"
      " package."
  )
