import io
import ezdxf
from ezdxf import units
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="HVAC P&ID & Schematic Generator", layout="wide"
)

st.title("HVAC P&ID & Schematic Generator")
st.markdown(
    "Upload your equipment schedule (Excel or CSV) to automatically generate a professional DXF schematic with standardized layers, `LTSCALE` configurations, and uniform AHU/FCU blocks with schedule-ready attributes."
)

# Sidebar - File Upload & Global Settings
st.sidebar.header("1. Upload Equipment Schedule")
uploaded_file = st.sidebar.file_uploader(
    "Upload AHU/FCU Schedule (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"]
)

st.sidebar.header("2. Drawing Parameters")
project_name = st.sidebar.text_input("Project Name", "Commercial Complex HVAC")
drawn_by = st.sidebar.text_input("Consultant / Designer", "MEP Consultant")


def generate_dxf_bytes(df_equipment):
  # Create DXF document targeting AutoCAD 2013/2014 format (AC1032)
  doc = ezdxf.new(dxfversion="AC1032", setup=True)
  doc.header["$LTSCALE"] = 500.0
  doc.header["$INSUNITS"] = units.MM

  msp = doc.modelspace()

  # 1. Setup Layers matching professional sample standards
  layers = [
      ("M-Ac-Chw-Supply", 3, "CONTINUOUS"),  # Green / Supply
      ("CHWS", 3, "CONTINUOUS"),
      ("M-Ac-Chw-Return", 5, "CONTINUOUS"),  # Blue / Return
      ("CHWR", 5, "CONTINUOUS"),
      ("M-Ac-Equipment", 7, "CONTINUOUS"),  # White / Equipment geometry
      ("M-Ac-Valve", 2, "CONTINUOUS"),  # Yellow / Valves
  ]

  for name, color, linetype in layers:
    if name not in doc.layers:
      doc.layers.new(name, dxfattribs={"color": color, "linetype": linetype})

  # 2. Setup Text Styles
  if "ROMANS" not in doc.styles:
    doc.styles.new("ROMANS", dxfattribs={"font": "romans.shx"})
  if "Ac-Text" not in doc.styles:
    doc.styles.new("Ac-Text", dxfattribs={"font": "txt.shx"})

  # 3. Create Standardized AHU Block Definition
  ahu_block = doc.blocks.new(name="EQ-AHU-STD")
  ahu_block.add_lwpolyline(
      [(0, 0), (800, 0), (800, 500), (0, 500), (0, 0)],
      dxfattribs={"layer": "M-Ac-Equipment"},
  )
  ahu_block.add_lwpolyline(
      [(200, 100), (250, 400), (300, 100), (350, 400), (400, 100)],
      dxfattribs={"layer": "M-Ac-Equipment"},
  )
  ahu_block.add_circle(
      (600, 250), radius=100, dxfattribs={"layer": "M-Ac-Equipment"}
  )

  ahu_block.add_attdef(
      "EQUIP_TAG",
      (400, 420),
      "Equipment Tag:",
      dxfattribs={"height": 35, "style": "ROMANS", "layer": "0"},
  )
  ahu_block.add_attdef(
      "CAPACITY",
      (400, 370),
      "Cooling Capacity (TR):",
      dxfattribs={"height": 25, "style": "ROMANS", "layer": "0"},
  )
  ahu_block.add_attdef(
      "AIRFLOW",
      (400, 320),
      "Airflow (CFM):",
      dxfattribs={"height": 25, "style": "ROMANS", "layer": "0"},
  )

  # 4. Create Standardized FCU Block Definition
  fcu_block = doc.blocks.new(name="EQ-FCU-STD")
  fcu_block.add_lwpolyline(
      [(0, 0), (500, 0), (500, 350), (0, 350), (0, 0)],
      dxfattribs={"layer": "M-Ac-Equipment"},
  )
  fcu_block.add_lwpolyline(
      [(150, 80), (190, 270), (230, 80), (270, 270)],
      dxfattribs={"layer": "M-Ac-Equipment"},
  )
  fcu_block.add_circle(
      (380, 175), radius=70, dxfattribs={"layer": "M-Ac-Equipment"}
  )

  fcu_block.add_attdef(
      "EQUIP_TAG",
      (250, 290),
      "Equipment Tag:",
      dxfattribs={"height": 30, "style": "ROMANS", "layer": "0"},
  )
  fcu_block.add_attdef(
      "CAPACITY",
      (250, 250),
      "Cooling Capacity (TR):",
      dxfattribs={"height": 20, "style": "ROMANS", "layer": "0"},
  )
  fcu_block.add_attdef(
      "AIRFLOW",
      (250, 210),
      "Airflow (CFM):",
      dxfattribs={"height": 20, "style": "ROMANS", "layer": "0"},
  )

  # 5. Process Equipment Schedule and Place Blocks Dynamically
  start_x = 1000
  spacing_x = 1800
  y_pos = 1000

  for index, row in df_equipment.iterrows():
    eq_type = str(row.get("Type", "AHU")).upper()
    eq_tag = str(row.get("Tag", f"EQ-{index+1}"))
    eq_cap = str(row.get("Capacity", "10.0 TR"))
    eq_air = str(row.get("Airflow", "2000 CFM"))

    current_x = start_x + (index * spacing_x)

    if "FCU" in eq_type:
      ref = msp.add_blockref("EQ-FCU-STD", insert=(current_x, y_pos))
    else:
      ref = msp.add_blockref("EQ-AHU-STD", insert=(current_x, y_pos))

    ref.add_attrib("EQUIP_TAG", eq_tag)
    ref.add_attrib("CAPACITY", eq_cap)
    ref.add_attrib("AIRFLOW", eq_air)

    # Draw localized connection line stub to main headers
    msp.add_line(
        (current_x + 250, y_pos + 500),
        (current_x + 250, y_pos + 1500),
        dxfattribs={"layer": "M-Ac-Chw-Supply"},
    )
    msp.add_line(
        (current_x + 250, y_pos),
        (current_x + 250, y_pos - 200),
        dxfattribs={"layer": "M-Ac-Chw-Return"},
    )

  # Draw Chilled Water Main Piping Headers spanning across all units
  total_width = max(3500, start_x + (len(df_equipment) * spacing_x))
  msp.add_line(
      (500, y_pos + 1500),
      (total_width, y_pos + 1500),
      dxfattribs={"layer": "M-Ac-Chw-Supply"},
  )
  msp.add_line(
      (500, y_pos - 200),
      (total_width, y_pos - 200),
      dxfattribs={"layer": "M-Ac-Chw-Return"},
  )

  # Write to string buffer and convert to bytes
  string_stream = io.StringIO()
  doc.write(string_stream)
  stream = io.BytesIO(string_stream.getvalue().encode("utf-8"))
  stream.seek(0)
  return stream


# Main App UI Workflow
if uploaded_file is not None:
  try:
    if uploaded_file.name.endswith(".csv"):
      df = pd.read_csv(uploaded_file)
    else:
      df = pd.read_excel(uploaded_file)

    st.subheader("Uploaded Equipment Schedule Preview")
    st.dataframe(df, use_container_width=True)

    if st.button("Generate & Download Professional DXF Schematic"):
      dxf_stream = generate_dxf_bytes(df)
      st.success(
          "DXF schematic generated successfully from your equipment schedule!"
      )
      st.download_button(
          label="Download Chilled_Water_Schematic.dxf",
          data=dxf_stream,
          file_name="Chilled_Water_Schematic.dxf",
          mime="application/dxf",
      )

  except Exception as e:
    st.error(
        f"Error reading the uploaded file. Please ensure columns match ('Type', 'Tag', 'Capacity', 'Airflow'). Details: {e}"
    )
else:
  st.info(
      "👈 Please upload your Excel or CSV equipment schedule in the sidebar to"
      " get started."
  )
