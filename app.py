import io
import ezdxf
from ezdxf import units
import streamlit as st

st.set_page_config(
    page_title="HVAC Schematic & DXF Generator", layout="wide"
)

st.title("HVAC P&ID & Schematic Generator")
st.markdown(
    "Configure your equipment parameters in the sidebar and generate a professional DXF schematic complete with standardized layers, `LTSCALE` configurations, and uniform AHU/FCU blocks with schedule-ready attributes."
)

# Sidebar for Project & Equipment Inputs
st.sidebar.header("Project & Drawing Parameters")
project_name = st.sidebar.text_input("Project Name", "Commercial Complex HVAC")
drawn_by = st.sidebar.text_input("Consultant / Designer", "MEP Consultant")

st.sidebar.subheader("Air Handling Unit (AHU) Configuration")
ahu_tag = st.sidebar.text_input("AHU Tag", "AHU-01")
ahu_capacity = st.sidebar.text_input("AHU Cooling Capacity (TR)", "15.0 TR")
ahu_airflow = st.sidebar.text_input("AHU Airflow (CFM)", "5000 CFM")

st.sidebar.subheader("Fan Coil Unit (FCU) Configuration")
fcu_tag = st.sidebar.text_input("FCU Tag", "FCU-01")
fcu_capacity = st.sidebar.text_input("FCU Cooling Capacity (TR)", "2.5 TR")
fcu_airflow = st.sidebar.text_input("FCU Airflow (CFM)", "800 CFM")


def generate_dxf_bytes(
    proj_name,
    designer,
    a_tag,
    a_cap,
    a_air,
    f_tag,
    f_cap,
    f_air,
):
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

  # 5. Insert Layout Entities & Chilled Water Piping into Modelspace
  ahu_ref = msp.add_blockref("EQ-AHU-STD", insert=(1000, 1000))
  ahu_ref.add_attrib("EQUIP_TAG", a_tag)
  ahu_ref.add_attrib("CAPACITY", a_cap)
  ahu_ref.add_attrib("AIRFLOW", a_air)

  fcu_ref = msp.add_blockref("EQ-FCU-STD", insert=(2500, 1000))
  fcu_ref.add_attrib("EQUIP_TAG", f_tag)
  fcu_ref.add_attrib("CAPACITY", f_cap)
  fcu_ref.add_attrib("AIRFLOW", f_air)

  msp.add_line(
      (500, 1500), (3500, 1500), dxfattribs={"layer": "M-Ac-Chw-Supply"}
  )
  msp.add_line((500, 800), (3500, 800), dxfattribs={"layer": "M-Ac-Chw-Return"})

  # Write to an in-memory string buffer, then encode to bytes for download
  string_stream = io.StringIO()
  doc.write(string_stream)
  stream = io.BytesIO(string_stream.getvalue().encode("utf-8"))
  stream.seek(0)
  return stream


# Streamlit UI Action Button
if st.button("Generate & Download Professional DXF Schematic"):
  dxf_stream = generate_dxf_bytes(
      project_name,
      drawn_by,
      ahu_tag,
      ahu_capacity,
      ahu_airflow,
      fcu_tag,
      fcu_capacity,
      fcu_airflow,
  )

  st.success(
      "DXF file compiled successfully with uniform equipment blocks and layers!"
  )
  st.download_button(
      label="Download Chilled_Water_Schematic.dxf",
      data=dxf_stream,
      file_name="Chilled_Water_Schematic.dxf",
      mime="application/dxf",
  )
