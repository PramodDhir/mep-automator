import streamlit as st
import ezdxf
import pandas as pd
import math
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="Professional HVAC P&ID & Schematic Automator", layout="wide")
st.title("❄️ Advanced HVAC P&ID Schematic & BOQ Automator")
st.markdown("Generate consultant-grade HVAC schematics, instrumentation loops, and comprehensive BOQ from your design summary.")

# --- SIZING CRITERIA ---
with st.expander("Hydraulic Design & Sizing Criteria", expanded=False):
    col1, col2, col3 = st.columns(3)
    delta_t_f = col1.number_input("Design Delta T (°F)", value=12.0)
    max_vel_fps = col2.number_input("Max Allowable Velocity (fps)", value=8.0)
    default_tr_to_gpm = col3.number_input("GPM per TR Factor", value=2.0)

standard_sizes = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 30.0, 36.0]

def calc_pipe_size(gpm):
    if gpm <= 0: return 0.5
    theoretical_dia = math.sqrt(gpm / (2.448 * max_vel_fps))
    for size in standard_sizes:
        if size >= theoretical_dia: return size
    return standard_sizes[-1]

# --- FILE UPLOAD WORKFLOW ---
uploaded_file = st.file_uploader("Upload Design Summary Excel Sheet (.xlsx)", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.str.strip()
        
        # --- SMART COLUMN MAPPING ---
        rename_map = {}
        for col in df.columns:
            c_lower = col.lower()
            if 'riser' in c_lower:
                rename_map[col] = 'Riser_ID'
            elif 'floor' in c_lower:
                rename_map[col] = 'Floor'
            elif 'tag' in c_lower or 'ahu' in c_lower or 'equipment' in c_lower:
                rename_map[col] = 'AHU_Tag'
            elif c_lower in ['gpm', 'flow', 'design_gpm', 'flow_gpm']:
                rename_map[col] = 'Design_GPM'
            elif c_lower in ['tr', 'ton', 'tons', 'rt', 'cooling_tr']:
                rename_map[col] = 'TR'
        
        df = df.rename(columns=rename_map)
        
        # Ensure both Design_GPM and TR exist
        if 'Design_GPM' not in df.columns and 'TR' in df.columns:
            df['Design_GPM'] = df['TR'] * default_tr_to_gpm
        elif 'TR' not in df.columns and 'Design_GPM' in df.columns:
            df['TR'] = df['Design_GPM'] / default_tr_to_gpm
        elif 'Design_GPM' not in df.columns and 'TR' not in df.columns:
            st.error("❌ Excel sheet must contain either a 'Flow/GPM' column or a 'TR/Tonnage' column.")
            st.stop()

        required_cols = ['Riser_ID', 'Floor', 'AHU_Tag', 'Design_GPM', 'TR']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            st.error(f"❌ Missing required columns: {missing_cols}. Detected columns: {list(df.columns)}")
            st.stop()
            
        st.success("✅ Design Data successfully loaded, mapped, and verified!")
        st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.error(f"Error reading file. Please ensure it is a valid Excel sheet. Error: {e}")
        st.stop()

    if st.button("Generate Professional P&ID Schematic & BOQ", type="primary"):
        with st.spinner("Executing hydraulic calculations and drafting professional MEP schematics..."):
            
            header_gpm = df['Design_GPM'].sum()
            header_tr = df['TR'].sum()
            header_pipe = calc_pipe_size(header_gpm)
            
            unique_risers = df['Riser_ID'].unique()
            num_risers = len(unique_risers)

            doc = ezdxf.new(dxfversion='R2010')
            msp = doc.modelspace()
            
            # Layers setup following consultant standards
            doc.layers.add("CHWS_PIPE", color=5)       # Blue - Chilled Water Supply
            doc.layers.add("CHWR_PIPE", color=1)       # Red - Chilled Water Return
            doc.layers.add("VALVES", color=3)          # Green - Valves & Fittings
            doc.layers.add("INSTRUMENTATION", color=2) # Yellow - DPT, Gauges, Sensors
            doc.layers.add("AHU_EQUIP", color=7)       # White - Equipment outlines
            doc.layers.add("ANNOTATIONS", color=7)     # White - Text & Tags

            riser_spacing = 150
            floor_height = 45
            riser_offset = 15
            header_offset = 25
            
            header_length = (num_risers * riser_spacing) + 60
            
            # Draw Main Header Pipes
            msp.add_line((0, 0), (header_length, 0), dxfattribs={'layer': 'CHWS_PIPE'})
            msp.add_line((0, -header_offset), (header_length, -header_offset), dxfattribs={'layer': 'CHWR_PIPE'})
            
            msp.add_text(f"MAIN CHWS HEADER: {header_tr:.1f} TR | {header_gpm:.1f} GPM | SIZE: {header_pipe}\" DIA", dxfattribs={'height': 3.5, 'layer': 'ANNOTATIONS'}).set_placement((10, 4))
            msp.add_text(f"MAIN CHWR HEADER: {header_tr:.1f} TR | {header_gpm:.1f} GPM | SIZE: {header_pipe}\" DIA", dxfattribs={'height': 3.5, 'layer': 'ANNOTATIONS'}).set_placement((10, -header_offset - 5))

            total_pipe_length = header_length * 2
            total_bfv = 2 # Main header isolation
            total_cv = 0
            total_balancing = 0
            total_ystrainer = 0
            total_dpt = 0
            total_pi_ti = 0

            for i, riser_id in enumerate(unique_risers):
                riser_data = df[df['Riser_ID'] == riser_id].sort_values(by="Floor")
                riser_gpm = riser_data['Design_GPM'].sum()
                riser_tr = riser_data['TR'].sum()
                riser_pipe = calc_pipe_size(riser_gpm)
                
                r_chws_x = (i + 1) * riser_spacing
                r_chwr_x = r_chws_x + riser_offset
                
                max_floor = riser_data['Floor'].max()
                riser_top_y = (max_floor * floor_height) + 20
                
                # Draw Riser Stacks
                msp.add_line((r_chws_x, 0), (r_chws_x, riser_top_y), dxfattribs={'layer': 'CHWS_PIPE'})
                msp.add_line((r_chwr_x, -header_offset), (r_chwr_x, riser_top_y), dxfattribs={'layer': 'CHWR_PIPE'})
                total_pipe_length += (riser_top_y * 2)
                
                total_bfv += 2 
                total_dpt += 1 
                
                msp.add_text(f"RISER {riser_id}: {riser_tr:.1f} TR | {riser_gpm:.1f} GPM | {riser_pipe}\" DIA", dxfattribs={'height': 2.5, 'layer': 'ANNOTATIONS'}).set_placement((r_chws_x - 10, riser_top_y + 3))
                msp.add_text("[DPT]", dxfattribs={'height': 2, 'layer': 'INSTRUMENTATION'}).set_placement((r_chws_x - 5, riser_top_y - 5))

                for _, row in riser_data.iterrows():
                    floor_y = row['Floor'] * floor_height
                    ahu_tag = row['AHU_Tag']
                    ahu_gpm = row['Design_GPM']
                    ahu_tr = row['TR']
                    ahu_pipe = calc_pipe_size(ahu_gpm)
                    
                    branch_end_x = r_chwr_x + 50
                    
                    msp.add_line((r_chws_x, floor_y), (branch_end_x, floor_y), dxfattribs={'layer': 'CHWS_PIPE'})
                    msp.add_line((r_chwr_x, floor_y - 10), (branch_end_x, floor_y - 10), dxfattribs={'layer': 'CHWR_PIPE'})
                    total_pipe_length += 100
                    
                    msp.add_text(f"TAG: {ahu_tag} ({ahu_tr:.1f} TR | {ahu_gpm:.1f} GPM)", dxfattribs={'height': 2.2, 'layer': 'ANNOTATIONS'}).set_placement((branch_end_x + 2, floor_y + 2))
                    msp.add_text(f"Supply Line: {ahu_pipe}\" DIA", dxfattribs={'height': 1.5, 'layer': 'ANNOTATIONS'}).set_placement((branch_end_x + 2, floor_y - 3))
                    
                    total_bfv += 2     
                    total_ystrainer += 1 
                    total_cv += 1      
                    total_balancing += 1 
                    total_pi_ti += 2   

            stream = io.StringIO()
            doc.write(stream)
            dxf_data = stream.getvalue()

            boq_df = pd.DataFrame({
                "Item Description": [
                    "Chilled Water Piping (Total Mixed Header, Riser & Branch Sizes)",
                    "Butterfly Valves (Isolation - Mains & Risers & Equipment)",
                    "Motorized Control Valves (AHU Coil Control)",
                    "Manual Balancing Valves (AHU Return Line)",
                    "Y-Strainers with SS Screen (AHU Supply Line)",
                    "Differential Pressure Transmitters (DPT Loops)",
                    "Pressure & Temperature Gauge Assemblies (PI/TI Sets)"
                ],
                "Quantity": [
                    round(total_pipe_length, 0),
                    total_bfv,
                    total_cv,
                    total_balancing,
                    total_ystrainer,
                    total_dpt,
                    total_pi_ti
                ],
                "Unit": ["ft", "EA", "EA", "EA", "EA", "EA", "SET"]
            })
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                boq_df.to_excel(writer, index=False, sheet_name='HVAC_BOQ')
            excel_data = excel_buffer.getvalue()

            st.success("🎉 Professional P&ID Schematic & Detailed BOQ Generated Successfully!")
            col1, col2 = st.columns(2)
            col1.download_button("📥 Download Consultant P&ID DXF", data=dxf_data, file_name="Professional_HVAC_Schematic.dxf", mime="image/vnd.dxf")
            col2.download_button("📥 Download Updated Excel BOQ", data=excel_data, file_name="HVAC_Detailed_BOQ.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            st.subheader("Comprehensive Bill of Quantities (BOQ) Preview")
            st.dataframe(boq_df, use_container_width=True)
else:
    st.info("👆 Please upload your Excel Design Summary (containing design flow rates or tonnage) to generate the professional schematic and BOQ.")
