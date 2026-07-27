import streamlit as st
import ezdxf
import pandas as pd
import math
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="MEP Schematic Automator", layout="wide")
st.title("❄️ Dynamic CHW Schematic & BOQ Automator")
st.markdown("Upload your AHU Design Summary to instantly generate an annotated DXF and BOQ.")

# --- SIZING CRITERIA ---
with st.expander("Hydraulic Design Criteria", expanded=False):
    col1, col2 = st.columns(2)
    delta_t_f = col1.number_input("Delta T (°F)", value=12)
    max_vel_fps = col2.number_input("Max Velocity (fps)", value=8.0)

standard_sizes = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 30.0, 36.0]

def calc_gpm(tr): return round((tr * 24) / delta_t_f, 1)
def calc_pipe_size(gpm):
    if gpm <= 0: return 0
    theoretical_dia = math.sqrt(gpm / (2.448 * max_vel_fps))
    for size in standard_sizes:
        if size >= theoretical_dia: return size
    return standard_sizes[-1]

# --- FILE UPLOAD WORKFLOW ---
uploaded_file = st.file_uploader("Upload Design Summary (Excel)", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.str.strip()
        
        # --- SMART COLUMN MAPPING (Prevents KeyErrors) ---
        rename_map = {}
        for col in df.columns:
            c_lower = col.lower()
            if 'riser' in c_lower:
                rename_map[col] = 'Riser_ID'
            elif 'floor' in c_lower:
                rename_map[col] = 'Floor'
            elif 'tag' in c_lower or 'ahu' in c_lower:
                rename_map[col] = 'AHU_Tag'
            elif c_lower in ['tr', 'ton', 'tons', 'rt', 'cooling_tr']:
                rename_map[col] = 'TR'
        
        df = df.rename(columns=rename_map)
        
        # Verify required columns exist
        required_cols = ['Riser_ID', 'Floor', 'AHU_Tag', 'TR']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            st.error(f"❌ Missing required columns: {missing_cols}. Your Excel columns were detected as: {list(df.columns)}")
            st.stop()
            
        st.success("Data successfully loaded and mapped!")
        st.dataframe(df.head(), use_container_width=True)
    except Exception as e:
        st.error(f"Error reading file. Please ensure it is a valid Excel sheet. Error: {e}")
        st.stop()

    if st.button("Generate Schematic & BOQ", type="primary"):
        with st.spinner("Parsing data, running hydraulics, and drafting CAD..."):
            
            header_tr = df['TR'].sum()
            header_gpm = calc_gpm(header_tr)
            header_pipe = calc_pipe_size(header_gpm)
            
            unique_risers = df['Riser_ID'].unique()
            num_risers = len(unique_risers)

            doc = ezdxf.new(dxfversion='R2010')
            msp = doc.modelspace()
            
            doc.layers.add("CHWS_PIPE", color=5)
            doc.layers.add("CHWR_PIPE", color=6)
            doc.layers.add("VALVES", color=2)
            doc.layers.add("AHU_EQUIP", color=7)
            doc.layers.add("ANNOTATIONS", color=7)

            riser_spacing = 120
            floor_height = 40
            riser_offset = 12
            header_offset = 20
            
            header_length = (num_risers * riser_spacing) + 50
            msp.add_line((0, 0), (header_length, 0), dxfattribs={'layer': 'CHWS_PIPE'})
            msp.add_line((0, -header_offset), (header_length, -header_offset), dxfattribs={'layer': 'CHWR_PIPE'})
            
            msp.add_text(f"MAIN CHWS: {header_tr} TR | {header_gpm} GPM | {header_pipe}\" \u00D8", dxfattribs={'height': 3}).set_placement((10, 3))
            
            total_pipe_length = header_length * 2
            total_bfv = 0
            total_balancing = 0
            total_ystrainer = 0

            for i, riser_id in enumerate(unique_risers):
                riser_data = df[df['Riser_ID'] == riser_id].sort_values(by="Floor")
                riser_tr = riser_data['TR'].sum()
                riser_gpm = calc_gpm(riser_tr)
                riser_pipe = calc_pipe_size(riser_gpm)
                
                r_chws_x = (i + 1) * riser_spacing
                r_chwr_x = r_chws_x + riser_offset
                
                max_floor = riser_data['Floor'].max()
                riser_top_y = (max_floor * floor_height) + 15
                
                msp.add_line((r_chws_x, 0), (r_chws_x, riser_top_y), dxfattribs={'layer': 'CHWS_PIPE'})
                msp.add_line((r_chwr_x, -header_offset), (r_chwr_x, riser_top_y), dxfattribs={'layer': 'CHWR_PIPE'})
                total_pipe_length += (riser_top_y * 2)
                
                msp.add_text(f"RISER {riser_id}: {riser_tr} TR | {riser_pipe}\" \u00D8", dxfattribs={'height': 2.5}).set_placement((r_chws_x - 10, riser_top_y + 2))
                total_bfv += 2 
                
                for _, row in riser_data.iterrows():
                    floor_y = row['Floor'] * floor_height
                    ahu_tag = row['AHU_Tag']
                    ahu_tr = row['TR']
                    ahu_gpm = calc_gpm(ahu_tr)
                    ahu_pipe = calc_pipe_size(ahu_gpm)
                    
                    branch_end_x = r_chwr_x + 40
                    
                    msp.add_line((r_chws_x, floor_y), (branch_end_x, floor_y), dxfattribs={'layer': 'CHWS_PIPE'})
                    msp.add_line((r_chwr_x, floor_y - 8), (branch_end_x, floor_y - 8), dxfattribs={'layer': 'CHWR_PIPE'})
                    total_pipe_length += 80 
                    
                    msp.add_text(f"TAG: {ahu_tag}", dxfattribs={'height': 2}).set_placement((branch_end_x + 2, floor_y + 2))
                    msp.add_text(f"{ahu_tr} TR | {ahu_gpm} GPM | {ahu_pipe}\" \u00D8", dxfattribs={'height': 1.5}).set_placement((branch_end_x + 2, floor_y - 2))
                    
                    total_bfv += 2
                    total_balancing += 1
                    total_ystrainer += 1

            stream = io.StringIO()
            doc.write(stream)
            dxf_data = stream.getvalue()

            boq_df = pd.DataFrame({
                "Item Description": [
                    "Total Chilled Water Piping (Mixed Sizes)",
                    "Butterfly Valves (Isolation)",
                    "Balancing Valves (AHU Return)",
                    "Y-Strainers (AHU Supply)"
                ],
                "Quantity": [round(total_pipe_length, 0), total_bfv, total_balancing, total_ystrainer],
                "Unit": ["ft", "EA", "EA", "EA"]
            })
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                boq_df.to_excel(writer, index=False, sheet_name='BOQ')
            excel_data = excel_buffer.getvalue()

            st.success("✅ Delivery Package Generated Successfully!")
            col1, col2 = st.columns(2)
            col1.download_button("📥 Download Annotated DXF", data=dxf_data, file_name="Dynamic_CHW_Schematic.dxf", mime="image/vnd.dxf")
            col2.download_button("📥 Download Excel BOQ", data=excel_data, file_name="CHW_BOQ.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            st.subheader("BOQ Preview")
            st.table(boq_df)
else:
    st.info("👆 Please upload your Excel Design Summary to begin.")
